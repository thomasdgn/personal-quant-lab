"""Campagne bornée : compte en parts entières, validation temporelle, registre d'essais.

Les conditions actuelles Bourso sont rejouées sur les cours historiques ajustés.
Ce contrefactuel est une exploration, sans promotion automatique en politique réelle.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.account_simulator import simulate_account
from src.costs import load_fee_model
from src.data_loader import load_prices
from src.investor_profile import load_profile
from src.macro import load_observations, macro_risk_filter
from src.provenance import code_revision, project_revision, record_trial
from src.research import block_bootstrap_sharpe_diff, sharpe
from src.results import to_jsonable
from src.robustness import deflated_sharpe, monthly_sharpe
from src.trading_calendar import last_session_of_month


def configurations() -> list[dict]:
    configs: list[dict] = [{"name": "world", "family": "fixed", "world": 1., "mode": "contribution"},
               {"name": "fixed_85_15", "family": "fixed", "world": .85, "mode": "contribution"},
               {"name": "cash", "family": "cash_mix", "world": 0., "mode": "contribution"},
               {"name": "fixed_85_15_bands", "family": "fixed", "world": .85, "mode": "bands"}]
    for ma, lookback, target_vol in itertools.product((6, 10, 12), (6, 9, 12), (None, .10, .12, .15)):
        configs.append({"name": f"trend_ma{ma}_mom{lookback}_vol{target_vol}", "family": "trend",
                        "ma": ma, "lookback": lookback, "target_vol": target_vol, "mode": "target"})
    for lookback, top_n, core in itertools.product((6, 9, 12), (1, 2), (0., .5, .8)):
        configs.append({"name": f"momentum_l{lookback}_n{top_n}_core{core}", "family": "momentum",
                        "lookback": lookback, "ma": 10, "top_n": top_n, "core": core, "mode": "target"})
    for world, band in itertools.product((.6, .8, 1.), (.05, .10)):
        configs.append({"name": f"equity_cash_w{world}_band{band}", "family": "cash_mix", "world": world,
                        "band": band, "mode": "bands"})
    return configs


def build_targets(prices: pd.DataFrame, config: dict) -> pd.DataFrame:
    monthly = prices.resample("ME").last()
    if prices.index[-1] < last_session_of_month(monthly.index[-1]):
        monthly = monthly.iloc[:-1]
    # Expositions uniques ; WPEA et CW8 ne sont jamais deux candidats Momentum.
    world, em, us = "CW8.PA", "PAEEM.PA", "ESE.PA"
    pool = [t for t in (world, em, us) if t in monthly]
    target = pd.DataFrame(0., index=monthly.index, columns=[*prices.columns, "CASH"])
    lb, ma = config.get("lookback", 12), config.get("ma", 10)
    momentum = monthly[pool].shift(1) / monthly[pool].shift(lb) - 1
    average = monthly[pool].rolling(ma, min_periods=ma).mean()
    for day in monthly.index:
        allocation = {}
        family = config["family"]
        if family == "fixed":
            allocation = {world: config["world"], em: 1 - config["world"]}
        elif family == "cash_mix":
            allocation = {world: config["world"]}
        elif family == "trend":
            if monthly.at[day, world] > average.at[day, world] and momentum.at[day, world] > 0:
                exposure = 1.0
                if config.get("target_vol"):
                    vol = monthly[world].pct_change(fill_method=None).loc[:day].tail(12).std() * np.sqrt(12)
                    exposure = min(1., config["target_vol"] / vol) if pd.notna(vol) and vol > 0 else 0.
                allocation = {world: exposure}
        else:
            eligible = momentum.loc[day].where((monthly.loc[day, pool] > average.loc[day]) & (momentum.loc[day] > 0)).dropna()
            picked = eligible.nlargest(config["top_n"]).index
            core = config["core"]
            allocation = {world: core}
            for ticker in picked:
                allocation[ticker] = allocation.get(ticker, 0.) + (1 - core) / len(picked)
        # Les parts World abordables sont accessibles seulement depuis leur cotation réelle.
        if monthly.get("WPEA.PA") is not None and pd.notna(monthly.at[day, "WPEA.PA"]) and world in allocation:
            allocation["WPEA.PA"] = allocation.pop(world)
        for ticker, weight in allocation.items():
            if ticker in monthly and pd.notna(monthly.at[day, ticker]):
                target.at[day, ticker] = weight
        target.at[day, "CASH"] = 1. - target.loc[day].sum()
    return target


def metrics(simulation: dict) -> dict:
    curve, orders = simulation["curve"], simulation["orders"]
    returns = curve["return"]
    equity = (1 + returns).cumprod()
    dd = equity / equity.cummax().clip(lower=1) - 1
    peak_date, recovery, longest = equity.index[0], 0, 0
    high = 1.0
    for day, value in equity.items():
        if value >= high:
            high, peak_date = value, day
        else:
            recovery = (day - peak_date).days
            longest = max(longest, recovery)
    years = max((curve.index[-1] - curve.index[0]).days / 365.25, 1 / 365.25)
    monthly = (1 + returns).resample("ME").prod() - 1
    sigma = returns.std()
    return {"final_value": float(curve["nav"].iloc[-1]), "contributed": float(curve["contributed"].iloc[-1]),
            "cagr_twr": float(equity.iloc[-1] ** (1 / years) - 1),
            "volatility": float(sigma * np.sqrt(252)),
            "sharpe": float(returns.mean() / sigma * np.sqrt(252)) if sigma > 0 else 0.,
            "max_drawdown": float(dd.min()), "recovery_days": longest,
            "cash_fraction": float((curve["cash"] / curve["nav"]).mean()),
            "orders": len(orders), "fees": float(orders["fee"].sum()) if not orders.empty else 0.,
            "monthly_returns": monthly}


def chronological_choices(monthly_returns: dict, runs: dict, *, train_months: int, block: int, risk_limit: float) -> dict:
    """Meilleur Sharpe passé parmi les comptes respectant le DD quotidien passé.

    Ce critère est figé dans la configuration ; il ne garantit pas le risque futur.
    Le candidat cash sert de repli lorsque les actifs risqués échouent au filtre.
    """
    frame = pd.DataFrame(monthly_returns)
    choices = []
    months = frame.index[train_months:]
    for offset in range(0, len(months), block):
        test = months[offset:offset + block]
        first_day = test[0].to_period("M").start_time
        scores, drawdowns = {}, {}
        for name in frame:
            past = frame.loc[frame.index < test[0], name].dropna()
            if len(past) < train_months:
                continue
            curve = runs[name]["curve"]
            daily = curve.loc[curve.index < first_day, "return"]
            growth = (1 + daily).cumprod()
            dd = float((growth / growth.cummax().clip(lower=1) - 1).min())
            if abs(dd) <= risk_limit:
                scores[name] = sharpe(past) or 0.
                drawdowns[name] = dd
        if not scores:
            raise ValueError("Aucun candidat compatible avec le risque passé, ajouter une référence cash.")
        best = max(scores, key=lambda name: (scores[name], str(name)))
        choices.append({"test_start": str(test[0].date()), "test_end": str(test[-1].date()), "config": best,
                        "train_sharpe": scores[best], "train_max_drawdown_daily": drawdowns[best],
                        "eligible_candidates": len(scores)})
    if not choices:
        raise ValueError("Historique trop court pour le walk-forward.")
    return {"choices": choices}


def run_campaign(root: Path, *, output_dir, limit=80) -> dict:
    if not 3 <= limit <= 250:
        raise ValueError("La campagne doit autoriser entre 3 et 250 variantes.")
    root, output = Path(root), Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    settings = yaml.safe_load((root / "config/tactical.yaml").read_text(encoding="utf-8"))
    profile = load_profile(root / "config/profil.yaml")
    if profile is None:
        raise ValueError("Profil personnel requis.")
    fees = load_fee_model(root / "config/strategy_params.yaml")
    daily_all = load_prices(root / "data/processed/universe_prices.csv")
    columns = [t for t in ("CW8.PA", "WPEA.PA", "PAEEM.PA", "ESE.PA") if t in daily_all]
    if "CW8.PA" not in columns or "PAEEM.PA" not in columns:
        raise ValueError("World et émergents réels requis pour une comparaison commune.")
    prices = daily_all[columns]
    common_start = max(prices[t].first_valid_index() for t in ("CW8.PA", "PAEEM.PA", "ESE.PA"))
    # Les signaux sont calculés avec la préhistoire, mais tous les comptes démarrent ensemble.
    start = common_start + pd.offsets.MonthBegin(1)
    complete = prices.resample("ME").last().index[-1]
    if prices.index[-1] < last_session_of_month(complete):
        complete -= pd.offsets.MonthEnd(1)
    history = prices.loc[start:complete]
    excluded = {}
    for ticker in columns:
        first = history[ticker].first_valid_index()
        missing = history.loc[first:, ticker].isna() if first is not None else pd.Series([True])
        if missing.any():
            if ticker != "WPEA.PA":
                raise ValueError(f"Historique incomplet de {ticker} : campagne interrompue.")
            excluded[ticker] = "Historique incomplet : " + ", ".join(str(d.date()) for d in missing[missing].index)
    if excluded:
        prices = prices.drop(columns=list(excluded))
        history = history.drop(columns=list(excluded))
    if len(history) < 252 * 4:
        raise ValueError("Au moins quatre ans communs nécessaires pour cette campagne.")
    provenance = {"code_sha256": code_revision(root), "inputs_sha256": project_revision(root),
                  "data_end": str(history.index[-1].date()), "price_basis": "adjusted_research_proxy",
                  "tariff": "barème actuel constant, pas les tarifs historiques",
                  "monthly": profile.versement_mensuel_eur, "initial": profile.capital_initial_eur,
                  "drawdown_objective": settings["drawdown_objective"], "excluded_vehicles": excluded}
    configs: list[dict] = configurations()[:min(limit, settings["max_variants"])]
    targets = {c["name"]: build_targets(prices.loc[:complete], c) for c in configs}
    macro_settings = yaml.safe_load((root / "config/macro_sources.yaml").read_text(encoding="utf-8"))
    macro = load_observations(root / "data/macro/observations.csv")
    overlay = macro_settings.get("research_filter")
    cfg: dict
    if not macro.empty and overlay and len(configs) < limit:
        cfg = {"name": "world_macro", "family": "fixed", "world": 1., "mode": "target"}
        t = targets["world"].copy()
        scale = macro_risk_filter(macro, t.index, overlay["series_id"], overlay["threshold"])
        if scale.notna().any():
            for column in t.columns.drop("CASH"):
                t[column] *= scale.fillna(1.)
            t["CASH"] = 1 - t.drop(columns="CASH").sum(axis=1)
            configs.append(cfg)
            targets[cfg["name"]] = t
    ids: dict[str, str] = {}
    results: dict[str, dict] = {}
    stats: dict[str, dict] = {}
    trial_count = 0
    common_kwargs = {"initial_capital": profile.capital_initial_eur, "monthly_contribution": profile.versement_mensuel_eur,
                     "max_trades": settings["max_trades_per_month"]}

    def simulate(cfg, fee=fees, delay=1, weights=None, data=history):
        return simulate_account(data, targets[cfg["name"]] if weights is None else weights,
                                fee_model=fee, execution_delay=delay, mode=cfg["mode"],
                                band=cfg.get("band", .05), **common_kwargs)

    for cfg in configs:
        ids[cfg["name"]], trial_count = record_trial(root / "reports/experiments.sqlite3", cfg, provenance)
        results[cfg["name"]] = simulate(cfg)
        stats[cfg["name"]] = metrics(results[cfg["name"]])
    monthly_returns: dict[str, pd.Series] = {str(k): v["monthly_returns"] for k, v in stats.items()}
    benchmark = monthly_returns["world"]
    sharpe_dispersion = float(np.std([monthly_sharpe(r) or 0 for r in monthly_returns.values()], ddof=1))
    rows = []
    for cfg in configs:
        name = str(cfg["name"])
        item = {k: v for k, v in stats[name].items() if k != "monthly_returns"}
        item.update({"name": name, "trial_id": ids[name], "parameters": cfg,
                     "risk_objective_met_in_sample": abs(item["max_drawdown"]) <= settings["drawdown_objective"],
                     "final_real_value": item["final_value"] / (1 + settings["inflation_annual"]) ** (len(history) / 252),
                     "dsr": deflated_sharpe(monthly_returns[name], trial_count, sharpe_dispersion),
                     "status": "exploratory"})
        if name != "world":
            item["sharpe_gap_ci90"] = block_bootstrap_sharpe_diff(monthly_returns[name], benchmark,
                                                                 samples=settings["bootstrap_samples"])
            # Intervalle simultané conservateur : tous les essais déjà enregistrés comptent.
            item["sharpe_gap_familywise_ci"] = block_bootstrap_sharpe_diff(
                monthly_returns[name], benchmark, samples=settings["bootstrap_samples"], level=1 - .05 / trial_count)
            item["bootstrap_tail_resolution_limited"] = settings["bootstrap_samples"] * .025 / trial_count < 10
        rows.append(item)
    # La sélection ne consulte que les rendements des mois précédents.
    wf = chronological_choices(monthly_returns, results, train_months=settings["train_months"],
                                 block=settings["test_months"], risk_limit=settings["drawdown_objective"])
    cfg_by_name = {c["name"]: c for c in configs}
    # Fusion des cibles de chaque bloc puis rejeu : pas de collage de courbes de comptes.
    combined = targets["world"].copy() * 0
    combined["CASH"] = 1.
    rules = {}
    for choice in wf["choices"]:
        first = pd.Timestamp(choice["test_start"]) - pd.offsets.MonthEnd(1)
        last = pd.Timestamp(choice["test_end"])
        chosen = targets[choice["config"]].loc[first:last]
        combined.loc[chosen.index] = chosen
        selected_cfg = cfg_by_name[choice["config"]]
        rules.update({day: (selected_cfg["mode"], selected_cfg.get("band", .05)) for day in chosen.index})
    first_test = pd.Timestamp(wf["choices"][0]["test_start"]) - pd.offsets.MonthBegin(1)
    oos_history = history.loc[first_test:]
    oos = simulate_account(oos_history, combined, fee_model=fees, rules_by_signal=rules, **common_kwargs)
    oos_bench = simulate(cfg_by_name["world"], data=oos_history)
    # Les comparaisons exploratoires par variante incluent le coût réel du compte.
    oos_stats, bench_stats = metrics(oos), metrics(oos_bench)
    oos_gap = block_bootstrap_sharpe_diff(oos_stats.pop("monthly_returns"), bench_stats.pop("monthly_returns"),
                                         samples=settings["bootstrap_samples"])
    ranked = sorted(rows, key=lambda r: (-r["final_value"], r["name"]))
    finalists = []
    seen_families = set()
    for row in ranked:
        family = row["parameters"]["family"]
        if row["risk_objective_met_in_sample"] and family not in seen_families and row["name"] != "cash":
            finalists.append(cfg_by_name[row["name"]])
            seen_families.add(family)
        if len(finalists) == 3:
            break
    sensitivities = []
    for cfg in [cfg_by_name["world"], *finalists]:
        for delay, spread in ((1, 0), (2, 30), (3, 50)):
            scenario = {"delay": delay, "spread_bps": spread}
            _, trial_count = record_trial(root / "reports/experiments.sqlite3", {**cfg, "stress": scenario}, provenance)
            run = simulate(cfg, replace(fees, spread_bps={"default": spread}), delay)
            m = metrics(run)
            sensitivities.append({"name": cfg["name"], **scenario, **{k: v for k, v in m.items() if k != "monthly_returns"}})
    # Risque de séquence : mêmes finalistes, démarrages décalés d'un an.
    starts = []
    for cfg in [cfg_by_name["world"], *finalists]:
        for years in (1, 2):
            shifted = history.loc[history.index[0] + pd.DateOffset(years=years):]
            _, trial_count = record_trial(root / "reports/experiments.sqlite3", {**cfg, "start_shift_years": years}, provenance)
            m = metrics(simulate(cfg, data=shifted))
            starts.append({"name": cfg["name"], "start_shift_years": years,
                           **{k: v for k, v in m.items() if k != "monthly_returns"}})
    # Recalculer les corrections avec TOUTES les sensibilités, pas seulement la grille.
    for row in rows:
        name = row["name"]
        row["dsr"] = deflated_sharpe(monthly_returns[name], trial_count, sharpe_dispersion)
        if name != "world":
            row["sharpe_gap_familywise_ci"] = block_bootstrap_sharpe_diff(
                monthly_returns[name], benchmark, samples=settings["bootstrap_samples"], level=1 - .05 / trial_count)
            row["bootstrap_tail_resolution_limited"] = settings["bootstrap_samples"] * .025 / trial_count < 10
    stress_windows: dict[str, dict] = {}
    for period, first, last in (("covid_2020", "2020-02-01", "2020-04-30"),
                               ("rates_2022", "2022-01-01", "2022-12-31")):
        stress_windows[period] = {}
        for name, run in results.items():
            r = run["curve"].loc[first:last, "return"]
            if not r.empty:
                growth = (1 + r).cumprod()
                stress_windows[period][name] = {"return_twr": float(growth.iloc[-1] - 1),
                                                "max_drawdown": float((growth / growth.cummax().clip(lower=1) - 1).min())}
    for row in rows:
        spec = row["parameters"]
        comparable = [r for r in rows if r["parameters"]["family"] == spec["family"] and
                      sum(spec.get(k) != r["parameters"].get(k) for k in ("ma", "lookback", "target_vol", "core", "top_n", "band", "world")) == 1]
        row["parameter_neighborhood"] = {"count": len(comparable),
                                          "median_sharpe": float(np.median([r["sharpe"] for r in comparable])) if comparable else None,
                                          "worst_sharpe": min((r["sharpe"] for r in comparable), default=None)}
    campaign_id = hashlib.sha256(json.dumps({"provenance": provenance, "configs": configs,
                                             "settings": settings}, sort_keys=True).encode()).hexdigest()[:16]
    payload: dict = {"campaign_id": campaign_id, "provenance": provenance, "variants": len(configs),
               "cumulative_unique_trials": trial_count, "start": str(history.index[0].date()),
               "end": str(history.index[-1].date()), "results": ranked,
               "walk_forward": {"choices": wf["choices"], "account": oos_stats, "benchmark": bench_stats, "gap_ci90": oos_gap},
               "sensitivities": sensitivities, "start_dates": starts,
               "stress_windows": stress_windows,
               "finalists": [c["name"] for c in finalists],
               "macro_status": "evaluated_experimentally" if "world_macro" in targets else "not_evaluated_no_real_vintages_or_filter",
               "conclusion": "Aucune stratégie promue automatiquement ; confirmer les cours bruts, produits et résultats prospectifs.",
               "limitations": ["Cours ajustés : approximation des parts historiques et événements sur titres.",
                               "Véhicules exclus pour trous de cotation : " + (str(excluded) if excluded else "aucun"),
                               "Tarifs actuels appliqués à toute la période : étude contrefactuelle.",
                               "Historique déjà examiné : aucun test final totalement indépendant revendiqué.",
                               "Sensibilités choisies après le classement : diagnostics exploratoires.",
                               "Bootstrap extrême peu résolu : ne pas revendiquer de significativité familiale.",
                               "Les configurations ont été définies après examen historique : validation prospective encore nécessaire."]}
    document = to_jsonable(payload)
    (output / f"{campaign_id}.json").write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "latest.json").write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(monthly_returns).to_csv(output / f"{campaign_id}-monthly.csv")
    for cfg in finalists:
        results[cfg["name"]]["orders"].to_csv(output / f"{campaign_id}-{cfg['name']}-orders.csv", index=False)
    lines = ["# Recherche tactique PEA — exploration", "", f"Campagne : {campaign_id}",
             f"Période : {payload['start']} → {payload['end']} ; {len(configs)} variantes ; {trial_count} essais cumulés.",
             f"Budget : {profile.versement_mensuel_eur:.0f} €/mois ; départ hypothétique {profile.capital_initial_eur:.0f} € ; objectif DD {settings['drawdown_objective']:.0%}.",
             "", "## Classement exploratoire", "", "| Variante | Capital final | DD quotidien TWR | Frais | Ordres |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for row in ranked:
        lines.append(f"| {row['name']} | {row['final_value']:.2f} € | {row['max_drawdown']:.1%} | {row['fees']:.2f} € | {row['orders']} |")
    lines += ["", "## Sélection walk-forward rejouée", "", f"Capital : {oos_stats['final_value']:.2f} € contre {bench_stats['final_value']:.2f} € pour World sur les mêmes flux.",
              f"Écart Sharpe : {oos_gap['diff']:+.2f}, IC 90 % [{oos_gap['low']:+.2f} ; {oos_gap['high']:+.2f}].",
              "", "## Limites", "", *[f"- {v}" for v in payload["limitations"]], "", payload["conclusion"]]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"campaign_id": campaign_id, "variants": len(configs), "cumulative_unique_trials": trial_count,
            "report": str(output / "report.md"), "status": "exploratory", "macro_status": payload["macro_status"]}

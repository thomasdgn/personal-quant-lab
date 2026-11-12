"""Étude « rendement maximal » : que rapporte, et que coûte, chaque cran de risque ?

Options de l'univers PEA, de la plus sage à la plus risquée : le plan suivi,
100 % Monde, S&P 500, Nasdaq-100, momentum concentré (un seul ETF à la fois),
puis levier x2 sur le Monde et sur le Nasdaq-100. Chacune est simulée comme un
plan (versement mensuel, frais, fiscalité, inflation) dans les trois scénarios
de rendement de ``config/plans.yaml``.

Garde-fous d'honnêteté :

- **Scénarios central et défavorable** : aucune zone ne garde son avance passée
  à risque égal (rendement de chaque ETF actions recentré sur le Sharpe du
  MSCI World, volatilité et krachs conservés), et les stratégies n'ont aucune
  surperformance supposée. Sinon le Nasdaq (2005-2026 exceptionnel) gagnerait
  d'office par simple rétroviseur. Le scénario historique, lui, rejoue le passé.
- **Levier x2 synthétique** : 2 × le rendement mensuel de l'indice, moins le
  coût de financement de la part empruntée et les frais de l'ETF. Les ETF réels
  se rééquilibrent chaque jour : l'érosion due à la volatilité est plus forte
  que dans cette approximation mensuelle (pertes sous-estimées).

Ce sont des ordres de grandeur pour voir le prix du rendement, pas des
recommandations. Aucun ordre n'est passé.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.costs import FeeModel
from src.investor_profile import InvestorProfile
from src.plans import (
    Hypotheses,
    PlanDef,
    PlanInputs,
    Pocket,
    Scenario,
    build_inputs,
    historical_windows,
    pocket_key,
    remove_alpha,
    shift_prices,
    simulate_plan,
    strategy_net_returns,
)
from src.robustness import cagr, max_drawdown
from src.taxes import TaxConfig

LEVERAGE = 2.0
FINANCING_PCT = 1.0   # coût annuel moyen de la part empruntée (taux court euro, 2005-2026 : ~1 %)
LEVERAGED_TER_PCT = 0.6
RUIN_DRAWDOWN = 0.50  # « perdre plus de la moitié en cours de route »


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    allocation: dict[str, float] | None = None
    strategy: str | None = None
    note: str = ""

    def plan(self) -> PlanDef:
        if self.strategy:
            pocket = Pocket(self.label, "pea", 1.0, "strategie", strategie=self.strategy)
        else:
            pocket = Pocket(self.label, "pea", 1.0, "etf", dict(self.allocation or {}))
        return PlanDef(id=self.key, nom=self.label, resume=self.note, pour_qui="", temps="5min", complexite=1,
                       horizon_min_ans=1, zones=("monde",), poches=(pocket,), routine=())


def default_options(policy_allocation: dict[str, float] | None) -> list[Option]:
    allocation = dict(policy_allocation) if policy_allocation else {"CW8.PA": 1.0}
    return [
        Option("ton_plan", "Ton plan (" + " + ".join(f"{w:.0%} {t}" for t, w in allocation.items()) + ")",
               allocation, note="La référence : l'allocation de ta politique."),
        Option("monde", "100 % Monde", {"CW8.PA": 1.0}, note="Un seul ETF MSCI World."),
        Option("sp500", "100 % S&P 500", {"ESE.PA": 1.0}, note="Concentration sur les États-Unis."),
        Option("nasdaq", "100 % Nasdaq-100", {"PUST.PA": 1.0}, note="Concentration sur la tech américaine."),
        Option("momentum", "Momentum concentré (1 ETF à la fois)", strategy="momentum",
               note="Rotation mensuelle vers l'ETF le plus fort, cash si tendance baissière."),
        Option("levier_monde", "Levier x2 Monde (synthétique)", {"LEV2:CW8.PA": 1.0},
               note="Deux fois les mouvements du MSCI World, chaque mois."),
        Option("levier_nasdaq", "Levier x2 Nasdaq-100 (synthétique)", {"LEV2:PUST.PA": 1.0},
               note="Deux fois les mouvements du Nasdaq-100 : l'option la plus risquée."),
    ]


def _rebuild(prices: pd.Series, log_returns: pd.Series) -> pd.Series:
    first = prices.first_valid_index()
    if first is None:
        return prices
    rebuilt = prices.loc[first] * np.exp(log_returns.loc[first:].fillna(0.0).cumsum())
    return rebuilt.where(prices.loc[first:].notna()).reindex(prices.index)


def neutralize_equities(prices: pd.DataFrame, roles: dict[str, str], benchmark: str,
                        window_start: pd.Timestamp | None = None) -> pd.DataFrame:
    """Chaque ETF actions au même Sharpe que le benchmark (aucune avance de zone à risque égal)."""
    logs = np.log1p(prices.pct_change(fill_method=None))
    window = logs.loc[window_start:] if window_start is not None else logs
    bench_mean, bench_vol = float(window[benchmark].mean()), float(window[benchmark].std())
    out = {}
    for column in prices.columns:
        if column == benchmark or roles.get(column, "candidate") != "candidate" or window[column].dropna().empty:
            out[column] = prices[column]
            continue
        target = bench_mean * float(window[column].std()) / bench_vol
        out[column] = _rebuild(prices[column], logs[column] + target - float(window[column].mean()))
    return pd.DataFrame(out, index=prices.index)


def add_leveraged(prices: pd.DataFrame, tickers: list[str], *, leverage: float = LEVERAGE,
                  financing_pct: float = FINANCING_PCT, ter_pct: float = LEVERAGED_TER_PCT) -> pd.DataFrame:
    """Ajoute des colonnes ``LEV2:<ticker>`` : levier mensuel synthétique, frais de financement et TER inclus."""
    out = prices.copy()
    for ticker in tickers:
        r = prices[ticker].pct_change(fill_method=None)
        lev = (leverage * r - (leverage - 1) * financing_pct / 100 / 12 - ter_pct / 100 / 12).clip(lower=-0.999)
        first = prices[ticker].first_valid_index()
        series = (1 + lev.loc[first:].fillna(0.0)).cumprod() * 100.0
        out[f"LEV{leverage:g}:{ticker}"] = series.reindex(prices.index)
    return out


def build_option_inputs(options: list[Option], monthly: pd.DataFrame, *, roles: dict[str, str], ctx,
                        transaction_cost: float, hyp: Hypotheses, scenario: Scenario,
                        window_start: pd.Timestamp | None = None) -> PlanInputs:
    """Rendements des options pour un scénario (mêmes conventions que les plans)."""
    benchmark = ctx.benchmark
    prices = monthly
    if not scenario.is_historical:
        prices = shift_prices(prices, roles, benchmark=benchmark, scenario=scenario, window_start=window_start)
        if scenario.surperformance == "nulle":
            prices = neutralize_equities(prices, roles, benchmark, window_start)
    leveraged = sorted({t.split(":", 1)[1] for o in options for t in (o.allocation or {}) if t.startswith("LEV")})
    universe = add_leveraged(prices, leveraged)
    names = {o.strategy for o in options if o.strategy}
    strategy_returns = strategy_net_returns(names, prices, ctx, transaction_cost) if names else {}
    plans = [o.plan() for o in options]
    inputs = build_inputs(plans, universe, strategy_returns=strategy_returns, crypto_monthly=None, hyp=hyp)
    inputs.scenario = scenario
    if not scenario.is_historical and scenario.surperformance == "nulle":
        bench = prices[benchmark].pct_change(fill_method=None).reindex(inputs.main.index)
        for plan in plans:
            if plan.poches[0].type == "strategie":
                key = pocket_key(plan, 0)
                inputs.main[key] = remove_alpha(inputs.main[key], bench)
    return inputs


def run_max_return_study(options: list[Option], monthly: pd.DataFrame, *, roles: dict[str, str], ctx,
                         transaction_cost: float, scenarios: dict[str, Scenario], profile: InvestorProfile,
                         hyp: Hypotheses, taxes: TaxConfig, fee_model: FeeModel, n_sims: int = 1000,
                         seed: int = 42) -> dict:
    kwargs: dict[str, Any] = {"capital": profile.capital_initial_eur, "monthly": profile.versement_mensuel_eur,
              "horizon_years": profile.horizon_ans, "hyp": hyp, "taxes": taxes, "fee_model": fee_model}
    historical = build_option_inputs(options, monthly, roles=roles, ctx=ctx, transaction_cost=transaction_cost,
                                     hyp=hyp, scenario=scenarios.get("historique", Scenario("historique", "Historique")))
    window_start = historical.main.index.min()
    by_scenario = {}
    for key, scenario in scenarios.items():
        inputs = historical if scenario.is_historical else build_option_inputs(
            options, monthly, roles=roles, ctx=ctx, transaction_cost=transaction_cost, hyp=hyp, scenario=scenario,
            window_start=window_start)
        rows = {}
        for option in options:
            sim = simulate_plan(option.plan(), inputs, **kwargs, n_sims=n_sims, seed=seed,
                                drawdown_tolerance=RUIN_DRAWDOWN)
            final = sim["final"]["net_real"]
            rows[option.key] = {"p10": final["p10"], "p50": final["p50"], "p90": final["p90"],
                                "p5": final["p5"], "p95": final["p95"],
                                "prob_loss": sim["prob_loss"], "prob_ruin": sim["drawdown"]["prob_beyond_tolerance"],
                                "drawdown_median": sim["drawdown"]["p50"], "drawdown_bad": sim["drawdown"]["p10"],
                                "implied_return": sim["implied_return_median"]}
        by_scenario[key] = {"label": scenario.label, "rows": rows}
    history = {}
    for option in options:
        series = historical.main[pocket_key(option.plan(), 0)]
        windows = historical_windows(option.plan(), historical, **kwargs)
        yearly = (1 + series).groupby(series.index.year).prod() - 1
        history[option.key] = {"cagr": cagr(series), "max_drawdown": max_drawdown(series),
                               "worst_year": float(yearly.min()), "best_year": float(yearly.max()),
                               "windows": windows}
    contributed = profile.capital_initial_eur + profile.versement_mensuel_eur * profile.horizon_ans * 12
    return {"options": options, "scenarios": by_scenario, "history": history, "window": historical.main.index,
            "contributed": contributed, "profile": profile, "ruin_threshold": RUIN_DRAWDOWN}


# --------------------------------------------------------------------------- #
# Sorties
# --------------------------------------------------------------------------- #
def _eur(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.0f} €".replace(",", " ")


def _pct(value: float | None, digits: int = 0) -> str:
    return "n/a" if value is None else f"{value:.{digits}%}"


def conclusion_lines(study: dict, scenario: str = "central") -> list[str]:
    rows = study["scenarios"][scenario]["rows"]
    base = rows["ton_plan"]
    labels = {o.key: o.label for o in study["options"]}
    best = max(rows, key=lambda k: rows[k]["p50"])
    riskiest = max(rows, key=lambda k: rows[k]["prob_ruin"] or 0.0)
    lines = [f"Scénario {study['scenarios'][scenario]['label'].lower()} : médiane la plus haute pour « {labels[best]} » "
             f"({_eur(rows[best]['p50'])} contre {_eur(base['p50'])} pour ton plan), mais "
             f"1 scénario sur 10 finit sous {_eur(rows[best]['p10'])}.",
             f"Option la plus risquée : « {labels[riskiest]} », avec {_pct(rows[riskiest]['prob_ruin'])} de probabilité "
             f"de perdre plus de la moitié en cours de route (ton plan : {_pct(base['prob_ruin'])})."]
    hist = study["scenarios"].get("historique")
    if hist:
        h = hist["rows"]
        top = max(h, key=lambda k: h[k]["p50"])
        lines.append(f"Sur le passé 2005-2026 seulement, « {labels[top]} » aurait mené ({_eur(h[top]['p50'])}) : c'est "
                     "le rétroviseur d'une période exceptionnelle pour la tech américaine, pas une prévision.")
    return lines


def generate_max_return_report(study: dict, output_path: str | Path, *, figure: bool = True) -> Path:
    path = Path(output_path)
    profile = study["profile"]
    window = study["window"]
    lines = ["# Rendement maximal : gains et pertes possibles", "", f"Date de génération : {date.today().isoformat()}",
             "", f"{_eur(profile.versement_mensuel_eur)}/mois pendant {profile.horizon_ans} ans (départ "
             f"{_eur(profile.capital_initial_eur)}), {_eur(study['contributed'])} versés. Valeur nette d'impôts en euros "
             f"d'aujourd'hui. Historique {window.min():%Y-%m} → {window.max():%Y-%m} (partiellement synthétique).", "",
             "**Étude pédagogique, pas une recommandation.** Plus de rendement espéré = plus de risque : "
             "cette page montre le prix de chaque cran. Aucun ordre n'est passé.", "", "## Constats", ""]
    lines += [f"- {line}" for line in conclusion_lines(study)]
    if figure:
        fig = _figure(study, path.parent / "figures" / "rendement_max.png")
        lines += ["", f"![Gains et pertes]({fig.relative_to(path.parent).as_posix()})"]
    for block in study["scenarios"].values():
        lines += ["", f"## Scénario {block['label']}", "",
                  "| Option | Défavorable (1/10) | **Médiane** | Favorable (1/10) | Rendement annuel implicite | "
                  "Pire baisse médiane | 1 scénario sur 10 | P(perdre > 50 % en route) | P(finir sous le versé) |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for option in study["options"]:
            r = block["rows"][option.key]
            lines.append(f"| {option.label} | {_eur(r['p10'])} | **{_eur(r['p50'])}** | {_eur(r['p90'])} | "
                         f"{_pct(r['implied_return'], 1)} | {_pct(r['drawdown_median'])} | {_pct(r['drawdown_bad'])} | "
                         f"{_pct(r['prob_ruin'])} | {_pct(r['prob_loss'])} |")
    lines += ["", "## Le vrai passé de chaque option", "",
              "| Option | Rendement annuel | Pire baisse | Pire année | Meilleure année | Pire départ (15 ans) |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for option in study["options"]:
        h = study["history"][option.key]
        w = h["windows"]
        worst = _eur(w["net_real"]["min"]) if w.get("available") else "n/a"
        lines.append(f"| {option.label} | {_pct(h['cagr'], 1)} | {_pct(h['max_drawdown'])} | {_pct(h['worst_year'])} | "
                     f"{_pct(h['best_year'])} | {worst} |")
    lines += ["", "## Méthode et limites", "",
              "- Scénarios central et défavorable : aucune zone ne garde son avance passée à risque égal, aucune "
              "stratégie n'a de surperformance supposée ; seul le risque pris change le rendement espéré.",
              f"- Levier x{LEVERAGE:g} synthétique : mensuel, financement {FINANCING_PCT:.1f} %/an sur la part empruntée, "
              f"frais {LEVERAGED_TER_PCT:.1f} %/an. Les ETF à levier réels se rééquilibrent chaque jour : leurs pertes "
              "en marché agité sont plus fortes que ici.",
              "- Concentration : un seul pays ou secteur peut sous-performer une décennie entière (Japon après 1990, "
              "Nasdaq 2000-2015).",
              "- **La fenêtre 2005-2026 ne contient pas l'éclatement de la bulle internet** : le Nasdaq-100 a perdu "
              "~80 % en 2000-2002 et un levier x2 aurait perdu ~95 %, sans jamais se remettre sur 15 ans. Les "
              "tirages ne peuvent pas produire un krach plus violent que ceux de la fenêtre.",
              "- Hypothèse des scénarios central et défavorable : même rendement par unité de risque pour toutes les "
              "options (plus de volatilité = plus de rendement espéré). C'est une convention neutre, pas une loi.",
              "- Les options concentrées ou à levier demandent de supporter des baisses de 60 à 90 % sans vendre : "
              "relis ta règle de krach avant d'y penser.", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def _figure(study: dict, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = study["scenarios"]["central"]["rows"] if "central" in study["scenarios"] else \
        next(iter(study["scenarios"].values()))["rows"]
    options = study["options"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(12, 0.6 * len(options) + 1.8))
    for i, option in enumerate(options[::-1]):
        r = rows[option.key]
        left.plot([r["p10"], r["p90"]], [i, i], color="#2563eb", linewidth=7, alpha=0.3, solid_capstyle="round")
        left.plot(r["p50"], i, "o", color="#1d4ed8", markersize=8)
        right.barh(i, r["prob_ruin"] * 100, color="#dc2626", alpha=0.75)
    left.axvline(study["contributed"], color="#64748b", linestyle="--", linewidth=1)
    left.set_yticks(range(len(options)), [o.label for o in options[::-1]])
    left.set_title("Gains possibles (central) : 1/10 défavorable, médiane, 1/10 favorable", fontsize=9)
    left.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v / 1000:.0f} k€"))
    right.set_yticks(range(len(options)), [""] * len(options))
    right.set_title("Risque : probabilité de perdre plus de 50 % en cours de route (%)", fontsize=9)
    for ax in (left, right):
        ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path

"""Stress tests sur historique long et distribution des résultats d'un DCA.

- **Fenêtres de crise** (2008-09, 2011, 2015-16, T4 2018, 2020, 2022) : pour
  chaque stratégie du registre, rendement sur la fenêtre, drawdown maximal
  (depuis le plus haut antérieur) et délai de récupération du plus haut.
- **Versements programmés** sur l'horizon de la politique : distribution des
  valeurs finales par bootstrap par blocs des rendements mensuels historiques
  (5e / 50e / 95e centiles), avant et après frais et impôts, et probabilité de
  subir un drawdown pire que la limite de la politique.

Les données antérieures aux ETF réels sont **synthétiques** (proxys) : la part
synthétique de chaque fenêtre est toujours affichée. Aucun ordre, aucune
modification automatique de la politique.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.engine import first_invested, run_strategies
from src.costs import FeeModel
from src.strategies import StrategyContext
from src.strategies import label as strategy_label
from src.taxes import TaxConfig, pea_net_value

STRESS_WINDOWS = (
    ("Crise financière 2008-09", "2007-11-30", "2009-03-31"),
    ("Crise de la dette euro 2011", "2011-05-31", "2011-12-31"),
    ("Chine / pétrole 2015-16", "2015-05-31", "2016-02-29"),
    ("T4 2018", "2018-09-30", "2018-12-31"),
    ("Covid 2020", "2020-01-31", "2020-04-30"),
    ("Inflation et taux 2022", "2021-12-31", "2022-10-31"),
)


def strategy_backtests(monthly: pd.DataFrame, ctx: StrategyContext, *, transaction_cost: float,
                       cash_return: float = 0.0) -> dict[str, pd.DataFrame]:
    """Backtests de toutes les stratégies du registre calculables sur ``monthly``."""
    runs = run_strategies(monthly, ctx, cost=transaction_cost, cash_return=cash_return)
    return {name: run.backtest for name, run in runs.items()}


_first_invested = first_invested


def stress_table(backtests: dict[str, pd.DataFrame], synthetic: pd.Series | None = None,
                 windows=STRESS_WINDOWS) -> pd.DataFrame:
    """Une ligne par (fenêtre, stratégie).

    ``synthetic`` : part des prix synthétiques par mois (0 à 1), pour signaler
    les fenêtres reposant sur des proxys.
    """
    rows = []
    for title, start, end in windows:
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        share = None
        if synthetic is not None:
            window_share = synthetic.loc[start:end]
            share = float(window_share.mean()) if not window_share.empty else None
        for name, bt in backtests.items():
            equity = bt["Equity Curve"]
            first = _first_invested(bt)
            if first is None or first > start or equity.index.max() < end or start not in equity.index:
                rows.append({"fenêtre": title, "stratégie": name, "actif": False, "rendement": None,
                             "drawdown_max": None, "mois_recuperation": None, "part_synthetique": share})
                continue
            before_peak = equity.loc[:start].max()
            window = equity.loc[start:end]
            ret = float(window.iloc[-1] / equity.loc[start] - 1.0)
            drawdown = float((window / np.maximum(before_peak, window.cummax()) - 1.0).min())
            trough = window.idxmin()
            peak_level = max(before_peak, window.loc[:trough].max())
            after = equity.loc[trough:]
            recovered = after[after >= peak_level]
            months = None if recovered.empty else int(len(equity.loc[trough:recovered.index[0]]) - 1)
            rows.append({"fenêtre": title, "stratégie": name, "actif": True, "rendement": ret,
                         "drawdown_max": drawdown, "mois_recuperation": months, "part_synthetique": share})
    return pd.DataFrame(rows)


def dca_outcomes(returns: pd.Series, *, monthly_contribution: float, horizon_months: int,
                 fee_model: FeeModel | None = None, taxes: TaxConfig | None = None,
                 drawdown_limit: float = 0.25, n_sims: int = 2000, block: int = 12, seed: int = 42) -> dict:
    """Distribution des résultats d'un versement mensuel sur ``horizon_months``.

    Bootstrap par blocs circulaires de ``block`` mois des rendements mensuels
    nets historiques (préserve une partie de l'autocorrélation des crises).
    """
    series = returns.dropna().to_numpy(dtype=float)
    if len(series) < 2 * block:
        raise ValueError("Historique trop court pour simuler des versements.")
    fee_model = fee_model or FeeModel()
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(horizon_months / block))
    starts = rng.integers(0, len(series), size=(n_sims, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_sims, -1)[:, :horizon_months] % len(series)
    paths = series[idx]
    fee = fee_model.order_cost(monthly_contribution)
    value = np.zeros(n_sims)
    unit = np.ones(n_sims)
    peak = np.ones(n_sims)
    worst = np.zeros(n_sims)
    for t in range(horizon_months):
        value = (value + monthly_contribution - fee) * (1.0 + paths[:, t])
        unit = unit * (1.0 + paths[:, t])
        peak = np.maximum(peak, unit)
        worst = np.minimum(worst, unit / peak - 1.0)
    contributed = monthly_contribution * horizon_months
    years = horizon_months / 12.0
    net = np.array([pea_net_value(v, contributed, years, taxes) for v in value])
    pct = lambda values: {f"p{q}": float(np.percentile(values, q)) for q in (5, 50, 95)}  # noqa: E731
    return {
        "n_sims": n_sims, "horizon_months": horizon_months, "monthly_contribution": monthly_contribution,
        "contributed": contributed, "fees_total": fee * horizon_months,
        "final_gross": pct(value), "final_net": pct(net),
        "prob_loss": float((net < contributed).mean()),
        "prob_drawdown_beyond_limit": float((worst < -drawdown_limit).mean()),
        "median_worst_drawdown": float(np.median(worst)),
    }


def synthetic_share_by_month(sources: pd.DataFrame, columns: list[str]) -> pd.Series:
    """Part des tickers dont le prix du mois est synthétique (parmi ceux cotés)."""
    subset = sources[[c for c in columns if c in sources.columns]]
    available = subset.notna()
    synthetic = available & subset.ne(pd.DataFrame({c: c for c in subset.columns}, index=subset.index))
    counts = available.sum(axis=1).replace(0, np.nan)
    return (synthetic.sum(axis=1) / counts).fillna(0.0)


def run_stress(monthly: pd.DataFrame, sources: pd.DataFrame, ctx: StrategyContext, *, transaction_cost: float,
               monthly_contribution: float, horizon_months: int, fee_model: FeeModel, taxes: TaxConfig,
               drawdown_limit: float, followed: str, n_sims: int = 2000) -> dict:
    backtests = strategy_backtests(monthly, ctx, transaction_cost=transaction_cost)
    synthetic = synthetic_share_by_month(sources, list(monthly.columns))
    table = stress_table(backtests, synthetic)
    outcomes = {}
    for name, bt in backtests.items():
        first = _first_invested(bt)
        returns = bt["Net Return"].loc[first:] if first is not None else bt["Net Return"]
        outcomes[name] = {
            "history_start": None if first is None else first.date().isoformat(),
            **dca_outcomes(returns, monthly_contribution=monthly_contribution, horizon_months=horizon_months,
                           fee_model=fee_model, taxes=taxes, drawdown_limit=drawdown_limit, n_sims=n_sims),
        }
    return {"start": monthly.index.min().date().isoformat(), "end": monthly.index.max().date().isoformat(),
            "labels": {n: strategy_label(n, ctx) for n in backtests}, "followed": followed,
            "drawdown_limit": drawdown_limit, "table": table, "outcomes": outcomes,
            "synthetic_share": synthetic}


def _pct(value, digits: int = 1) -> str:
    return "n/a" if value is None or (isinstance(value, float) and np.isnan(value)) else f"{value:.{digits}%}"


def _eur(value: float) -> str:
    return f"{value:,.0f} €".replace(",", " ")


def stress_conclusion(study: dict) -> list[str]:
    table = study["table"][study["table"]["actif"]]
    lines = []
    for title, _, _ in STRESS_WINDOWS:
        rows = table[table["fenêtre"] == title]
        if rows.empty:
            continue
        best = rows.loc[rows["drawdown_max"].idxmax()]
        worst = rows.loc[rows["drawdown_max"].idxmin()]
        lines.append(f"- {title} : drawdown le plus limité {study['labels'][best['stratégie']]} "
                     f"({_pct(best['drawdown_max'])}), le plus profond {study['labels'][worst['stratégie']]} "
                     f"({_pct(worst['drawdown_max'])}).")
    followed = study["outcomes"].get(study["followed"])
    if followed:
        lines.append(f"- Stratégie suivie ({study['followed']}) : probabilité simulée de dépasser un drawdown de "
                     f"{study['drawdown_limit']:.0%} sur l'horizon = {followed['prob_drawdown_beyond_limit']:.0%}.")
    lines.append("- Résultats indicatifs : données partiellement synthétiques, passé non représentatif du futur.")
    return lines


def generate_stress_report(study: dict, output_path: str | Path, *, research_short: dict | None = None,
                           research_long: dict | None = None, proxy_chains: dict | None = None) -> Path:
    table = study["table"]
    lines = [
        "# Stress tests et versements sur longue période", "",
        f"Date de génération : {date.today().isoformat()}", "",
        f"Historique mensuel en EUR : {study['start']} → {study['end']}. **Avant la cotation des ETF PEA, les prix "
        "sont synthétiques** (proxys de même exposition, `config/long_history.yaml`) : la colonne « part "
        "synthétique » indique leur poids dans chaque fenêtre. Aucun ordre, aucune modification de la politique.", "",
        "## Fenêtres de crise", "",
    ]
    for title, start, end in STRESS_WINDOWS:
        rows = table[table["fenêtre"] == title]
        share = rows["part_synthetique"].iloc[0] if not rows.empty else None
        lines += [f"### {title} ({start[:7]} → {end[:7]}, part synthétique {_pct(share, 0)})", "",
                  "| Stratégie | Rendement | Drawdown max | Récupération (mois après le creux) |",
                  "| --- | ---: | ---: | ---: |"]
        for _, row in rows.iterrows():
            label = study["labels"][row["stratégie"]] + (" **(suivie)**" if row["stratégie"] == study["followed"] else "")
            if not row["actif"]:
                lines.append(f"| {label} | non active | — | — |")
                continue
            recovery = "non récupéré" if row["mois_recuperation"] is None or pd.isna(row["mois_recuperation"]) \
                else f"{int(row['mois_recuperation'])}"
            lines.append(f"| {label} | {_pct(row['rendement'])} | {_pct(row['drawdown_max'])} | {recovery} |")
        lines.append("")
    any_outcome = next(iter(study["outcomes"].values()))
    lines += [
        "## Versements programmés : distribution des résultats", "",
        f"{_eur(any_outcome['monthly_contribution'])} par mois pendant {any_outcome['horizon_months'] // 12} ans "
        f"({_eur(any_outcome['contributed'])} versés), {any_outcome['n_sims']} trajectoires par bootstrap par blocs de "
        "12 mois des rendements historiques de chaque stratégie. Valeur nette : frais d'ordre du barème et "
        "prélèvements sociaux (PEA > 5 ans) sur le gain.", "",
        "| Stratégie | Historique depuis | Valeur nette p5 | p50 | p95 | P(perte) | P(drawdown > limite) | "
        "Drawdown médian du pire épisode |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, item in study["outcomes"].items():
        label = study["labels"][name] + (" **(suivie)**" if name == study["followed"] else "")
        lines.append(f"| {label} | {item['history_start']} | {_eur(item['final_net']['p5'])} | "
                     f"{_eur(item['final_net']['p50'])} | {_eur(item['final_net']['p95'])} | {_pct(item['prob_loss'], 0)} | "
                     f"{_pct(item['prob_drawdown_beyond_limit'], 0)} | {_pct(item['median_worst_drawdown'])} |")
    if research_short and research_long:
        short = {r["key"]: r for r in research_short.get("strategies", [])}
        long_ = {r["key"]: r for r in research_long.get("strategies", [])}
        lines += ["", "## Étude de robustesse : fenêtre courte vs historique long", "",
                  f"Courte : {research_short['start']} → {research_short['end']} (données réelles). "
                  f"Longue : {research_long['start']} → {research_long['end']} (partiellement synthétique).", "",
                  "| Stratégie | Sharpe court | Sharpe long | Écart vs B&H long [IC 90 %] | Max DD long |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        for key, row in long_.items():
            s = short.get(key, {})
            gap = "—" if row.get("sharpe_diff") is None else \
                f"{row['sharpe_diff']:+.2f} [{row['sharpe_diff_low']:+.2f} ; {row['sharpe_diff_high']:+.2f}]"
            sharpe_short = "n/a" if s.get("sharpe") is None else f"{s['sharpe']:.2f}"
            sharpe_long = "n/a" if row.get("sharpe") is None else f"{row['sharpe']:.2f}"
            lines.append(f"| {row['label']} | {sharpe_short} | {sharpe_long} | {gap} | {_pct(row.get('max_drawdown'))} |")
    if proxy_chains:
        lines += ["", "## Sources des données synthétiques", "",
                  "| ETF PEA | Proxys (du plus récent au plus ancien) |", "| --- | --- |"]
        for target, chain in proxy_chains.items():
            links = " ; ".join(f"{link['ticker']} ({link['currency']}) — {link.get('note', '')}" for link in chain)
            lines.append(f"| {target} | {links} |")
        lines += ["", "_Avant 2009, le proxy MSCI World est un indice de prix : un rendement de dividende **estimé** "
                      "(`dividend_yield_pct`) lui est ajouté ; l'erreur résiduelle est de l'ordre de ±0,5 point par an._"]
    lines += ["", "## Conclusion", ""] + stress_conclusion(study) + [""]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def save_stress_json(study: dict, output_path: str | Path) -> Path:
    from src.results import write_results_json

    table = study["table"].astype(object).where(study["table"].notna(), None)
    payload = {"generated": date.today().isoformat(), "start": study["start"], "end": study["end"],
               "followed": study["followed"], "drawdown_limit": study["drawdown_limit"], "labels": study["labels"],
               "windows": table.to_dict(orient="records"), "outcomes": study["outcomes"],
               "conclusion": stress_conclusion(study)}
    synthetic = study.get("synthetic_share")
    return write_results_json(payload, output_path, kind="stress", start=study["start"], end=study["end"],
                              synthetic_share=None if synthetic is None else float(synthetic.mean()))

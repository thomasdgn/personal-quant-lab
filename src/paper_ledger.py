"""Portefeuille fictif de paper trading : mesure des décisions dans le temps.

Reconstitue, à partir du journal (``reports/paper_trading/*-paper-entry.json``)
et des prix locaux, trois portefeuilles **hypothétiques** évalués sur les mêmes
mois :

- ``paper``     : l'allocation que j'ai réellement choisie (décisions humaines) ;
- ``system``    : « toujours suivre la proposition du système » ;
- ``benchmark`` : Buy & Hold du benchmark (100 % CW8.PA par défaut).

Règles de décision (clé = ``signal_date`` de l'entrée, fin de mois ``S``) :

- ``APPROVED_PAPER`` : les poids cibles de la stratégie choisie s'appliquent à
  partir du mois ``S+1`` ;
- ``REJECTED``, ``SKIPPED``, ``NEEDS_REVIEW``, ``PENDING`` : l'allocation
  précédente est conservée (aucun changement) ;
- plusieurs entrées pour le même signal : la plus récente (``report_month``)
  l'emporte.

Le suivi commence au premier signal approuvé. Seuls les mois **complets**
disponibles dans les prix locaux sont évalués. Mêmes conventions que le
backtest : rendements mensuels, frais proportionnels au turnover, cash
rémunéré au rendement du proxy monétaire s'il est fourni. Aucun ordre réel.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.backtest import CASH_COLUMN, backtest_monthly_allocation
from src.features import to_monthly_prices

PORTFOLIOS = ("paper", "system", "benchmark")
PORTFOLIO_LABELS = {
    "paper": "Mes décisions (paper)",
    "system": "Proposition du système",
    "benchmark": "Buy & Hold benchmark",
}


def _complete_monthly_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Prix de fin de mois, mois en cours incomplet exclu."""
    monthly = to_monthly_prices(prices)
    last_observation = prices.dropna(how="all").index.max().normalize()
    if len(monthly) and last_observation < monthly.index[-1].normalize() + pd.offsets.MonthEnd(0):
        monthly = monthly.iloc[:-1]
    return monthly


def decision_points(entries: list[dict]) -> pd.DataFrame:
    """Une ligne par date de signal : allocation paper et allocation système.

    Les poids sont des dictionnaires ``{actif: poids}`` (``CASH`` compris).
    """
    by_signal: dict[str, dict] = {}
    for entry in sorted(entries, key=lambda e: (e.get("signal_date") or "", e.get("report_month") or "")):
        signal = entry.get("signal_date")
        if signal:
            by_signal[signal] = entry  # la plus récente pour un même signal l'emporte

    rows, paper_weights = [], None
    for signal, entry in sorted(by_signal.items()):
        targets = entry.get("target_weights") or {}
        status = entry.get("manual_decision_status")
        if status == "APPROVED_PAPER":
            chosen = entry.get("manual_selected_strategy")
            paper_weights = entry.get("manual_approved_weights") or targets.get(chosen)
        rows.append({
            "signal_date": pd.Timestamp(signal),
            "report_month": entry.get("report_month"),
            "status": status,
            "chosen_strategy": entry.get("manual_selected_strategy") if status == "APPROVED_PAPER" else None,
            "paper_weights": dict(paper_weights) if paper_weights else None,
            "system_weights": dict(targets.get(entry.get("system_suggested_strategy")) or {}) or None,
        })
    return pd.DataFrame(rows)


def _executed_weights(points: pd.DataFrame, column: str, index: pd.DatetimeIndex, assets: list[str]) -> pd.DataFrame:
    """Poids tenus chaque mois : dernière décision dont le signal précède le mois."""
    frame = pd.DataFrame(0.0, index=index, columns=[*assets, CASH_COLUMN])
    frame[CASH_COLUMN] = 1.0
    for month in index:
        known = points[(points["signal_date"] < month) & points[column].notna()]
        if known.empty:
            continue
        weights = known.iloc[-1][column]
        frame.loc[month] = 0.0
        for asset, weight in weights.items():
            frame.loc[month, asset if asset in frame.columns else CASH_COLUMN] += float(weight or 0.0)
    return frame


def build_paper_ledger(
    entries: list[dict],
    prices: pd.DataFrame,
    *,
    benchmark: str = "CW8.PA",
    transaction_cost: float = 0.001,
    cash_proxy: str | None = None,
    fallback_cash_return: float = 0.0,
) -> dict:
    """Évalue mois par mois les portefeuilles paper, système et benchmark.

    Returns
    -------
    dict
        ``start``, ``end``, ``n_months``, ``monthly`` (DataFrame des rendements
        et valeurs cumulées), ``metrics`` par portefeuille, ``value_added``
        (paper − système, en points), ``warnings`` et ``points`` (décisions).
    """
    points = decision_points(entries)
    empty = {"start": None, "end": None, "n_months": 0, "monthly": pd.DataFrame(), "metrics": {},
             "value_added": None, "warnings": [], "points": points}
    approved = points[points["paper_weights"].notna()] if not points.empty else points
    if approved.empty:
        empty["warnings"].append("Aucune décision APPROVED_PAPER : pas encore de portefeuille paper à suivre.")
        return empty

    monthly = _complete_monthly_prices(prices)
    start_signal = approved["signal_date"].iloc[0]
    months = monthly.index[monthly.index > start_signal]
    if months.empty:
        empty["warnings"].append(
            f"Premier signal suivi au {start_signal.date()} : aucun mois complet après ce signal dans les prix locaux."
        )
        return empty

    assets = sorted({a for col in ("paper_weights", "system_weights") for w in points[col].dropna()
                     for a in w if a != CASH_COLUMN} | {benchmark})
    warnings: list[str] = []
    missing = [a for a in assets if a not in monthly.columns]
    if missing:
        warnings.append(f"Pas de prix locaux pour {', '.join(missing)} : leur poids est traité comme du cash.")
    priced = [a for a in assets if a in monthly.columns]
    if benchmark not in priced:
        raise ValueError(f"Benchmark {benchmark} absent des prix locaux : suivi impossible.")

    # Mois évaluables : tous les actifs détenus ont un rendement (prix t et t-1).
    returns_ok = monthly[priced].pct_change(fill_method=None).notna()
    cash_return: float | pd.Series = fallback_cash_return
    if cash_proxy and cash_proxy in monthly.columns:
        cash_return = monthly[cash_proxy].pct_change(fill_method=None).fillna(fallback_cash_return)

    index = monthly.index[monthly.index >= months[0] - pd.offsets.MonthEnd(1)]
    frames = {
        "paper": _executed_weights(points, "paper_weights", index, priced),
        "system": _executed_weights(points, "system_weights", index, priced),
    }
    bench = pd.DataFrame(0.0, index=index, columns=[*priced, CASH_COLUMN])
    bench[benchmark] = 1.0
    frames["benchmark"] = bench
    # Le mois de référence (fin du mois du signal) sert de point de départ : 100 % cash, sans frais.
    for frame in frames.values():
        frame.iloc[0] = 0.0
        frame.iloc[0, frame.columns.get_loc(CASH_COLUMN)] = 1.0

    evaluable = []
    for month in index[1:]:
        held = set()
        for frame in frames.values():
            held |= {a for a in priced if frame.at[month, a] > 0}
        if all(returns_ok.at[month, a] for a in held):
            evaluable.append(month)
        else:
            warnings.append(f"Mois {month:%Y-%m} non évaluable (rendement indisponible) : suivi arrêté.")
            break
    if not evaluable:
        empty["warnings"] = warnings
        return empty
    index = index[: len(evaluable) + 1]

    results = {}
    for name, frame in frames.items():
        bt = backtest_monthly_allocation(
            monthly.loc[index, priced], frame.loc[index], initial_capital=1.0,
            transaction_cost=transaction_cost, cash_return=cash_return,
        )
        results[name] = bt.iloc[1:]

    table = pd.DataFrame({
        **{f"{name}_return": bt["Net Return"] for name, bt in results.items()},
        **{f"{name}_value": bt["Equity Curve"] for name, bt in results.items()},
        "paper_selection": results["paper"]["Selected Assets"],
        "system_selection": results["system"]["Selected Assets"],
    })
    metrics = {}
    for name, bt in results.items():
        growth = bt["Equity Curve"]
        metrics[name] = {
            "total_return": float(growth.iloc[-1] - 1.0),
            "max_drawdown": float((growth / growth.cummax().clip(lower=1.0) - 1.0).min()),
            "costs": float(bt["Transaction Cost"].sum()),
        }
    return {
        "start": table.index.min().date().isoformat(),
        "end": table.index.max().date().isoformat(),
        "n_months": int(len(table)),
        "monthly": table,
        "metrics": metrics,
        "value_added": metrics["paper"]["total_return"] - metrics["system"]["total_return"],
        "warnings": warnings,
        "points": points,
    }


def _pct(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value * 100:+.{digits}f} %"


def ledger_summary_lines(ledger: dict) -> list[str]:
    """Résumé texte (compatible console cp1252) pour la CLI."""
    if not ledger["n_months"]:
        return ledger["warnings"] or ["Pas encore de mois évaluable."]
    lines = [f"Période suivie : {ledger['start']} -> {ledger['end']} ({ledger['n_months']} mois complets)"]
    for name in PORTFOLIOS:
        m = ledger["metrics"][name]
        lines.append(f"  {PORTFOLIO_LABELS[name]:26}: {_pct(m['total_return'])} (max DD {_pct(m['max_drawdown'])})")
    lines.append(f"  Valeur ajoutée de mes choix vs système : {_pct(ledger['value_added'])}")
    lines += [f"  Note : {w}" for w in ledger["warnings"]]
    return lines


def generate_performance_report(ledger: dict, output_path: str | Path, *, benchmark: str = "CW8.PA") -> Path:
    """Rapport Markdown de la performance du paper trading."""
    lines = [
        "# Performance du paper trading", "",
        "Portefeuilles **fictifs** reconstitués à partir du journal de décisions. Aucun ordre réel.", "",
        "- Mes décisions : allocation de la stratégie approuvée, conservée tant qu'aucune nouvelle "
        "approbation n'intervient (REJECTED / SKIPPED / PENDING = pas de changement).",
        "- Proposition du système : allocation suggérée chaque mois, suivie sans exception.",
        f"- Benchmark : Buy & Hold {benchmark}.",
        "- Allocation d'un signal de fin de mois M appliquée au mois M+1 ; mois en cours exclu.", "",
    ]
    if not ledger["n_months"]:
        lines += ["Pas encore de mois évaluable.", ""] + [f"- {w}" for w in ledger["warnings"]]
    else:
        lines += [
            f"## Synthèse ({ledger['start']} → {ledger['end']}, {ledger['n_months']} mois)", "",
            "| Portefeuille | Rendement cumulé | Max drawdown | Frais cumulés |", "| --- | ---: | ---: | ---: |",
        ]
        for name in PORTFOLIOS:
            m = ledger["metrics"][name]
            label = PORTFOLIO_LABELS[name].replace("benchmark", benchmark)
            lines.append(f"| {label} | {_pct(m['total_return'])} | {_pct(m['max_drawdown'])} | {_pct(m['costs'])} |")
        lines += [
            "", f"**Valeur ajoutée de mes choix par rapport au système : {_pct(ledger['value_added'])}.**", "",
            "## Détail mensuel", "",
            "| Mois | Mes décisions | Système | Benchmark | Détenu (paper) | Détenu (système) |",
            "| --- | ---: | ---: | ---: | --- | --- |",
        ]
        for month, row in ledger["monthly"].iterrows():
            lines.append(
                f"| {month:%Y-%m} | {_pct(row['paper_return'])} | {_pct(row['system_return'])} | "
                f"{_pct(row['benchmark_return'])} | {row['paper_selection']} | {row['system_selection']} |"
            )
        if ledger["warnings"]:
            lines += ["", "## Remarques", ""] + [f"- {w}" for w in ledger["warnings"]]
    points = ledger["points"]
    if not points.empty:
        lines += ["", "## Décisions prises en compte", "", "| Signal | Rapport | Statut | Stratégie choisie |",
                  "| --- | --- | --- | --- |"]
        for _, row in points.iterrows():
            lines.append(f"| {row['signal_date']:%Y-%m-%d} | {row['report_month']} | {row['status']} | "
                         f"{row['chosen_strategy'] or '—'} |")
    lines += ["", "_Quelques mois ne suffisent pas à juger une stratégie : lecture indicative._", ""]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path

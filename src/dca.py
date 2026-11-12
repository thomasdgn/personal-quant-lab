"""Simulation de versements mensuels programmés (DCA) — Projet 1B.

Rejoue un versement mensuel fixe dans des stratégies déjà backtestées
(Buy & Hold, Momentum, Momentum + VT) pour estimer ce qu'aurait donné la
démarche réelle d'épargne. Aucun ordre n'est exécuté.

Convention de calcul
--------------------
Le versement du mois ``t`` est effectué au début du mois (juste après la fin
du mois ``t-1``) et bénéficie donc du rendement net du mois ``t`` :

    V(t) = (V(t-1) + C - frais_versement(t)) × (1 + r_net(t))

- ``r_net(t)`` : rendement mensuel net de la stratégie (frais de rotation
  inclus par le backtest, modèle proportionnel au turnover) ;
- ``frais_versement(t)`` : coût d'achat de la part investie du versement
  (``C × exposition(t)``), la part laissée en cash ne paie pas de frais.
  Sans modèle de frais : ``frais × C × exposition(t)``. Avec un ``FeeModel``
  (forfait, minimum, spread) : un ordre par ETF détenu, soit
  ``n × frais_ordre(C × exposition(t) / n)`` — un forfait pèse donc lourd sur
  un petit versement.

Le rendement annualisé « argent investi » est un TRI (taux de rendement
interne) mensuel annualisé : il tient compte du calendrier des versements,
contrairement au CAGR d'une stratégie.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.costs import FeeModel
from src.taxes import TaxConfig, pea_net_value

STRATEGY_LABELS = {
    "buy_and_hold": "Buy & Hold benchmark",
    "momentum": "Momentum défensif",
    "momentum_vt": "Momentum + VT",
}


def simulate_dca(
    net_returns: pd.Series,
    monthly_contribution: float,
    *,
    invested_exposure: pd.Series | None = None,
    transaction_cost: float = 0.0,
    initial_capital: float = 0.0,
    fee_model: FeeModel | None = None,
    orders_per_month: pd.Series | None = None,
) -> pd.DataFrame:
    """Simule un versement mensuel fixe dans une série de rendements nets.

    Parameters
    ----------
    net_returns:
        Rendements mensuels nets de la stratégie (index = fins de mois). Les
        ``NaN`` initiaux sont retirés ; un ``NaN`` interne est une erreur.
    monthly_contribution:
        Versement mensuel en euros (>= 0).
    invested_exposure:
        Exposition investie par mois (0 à 1) pour le coût d'achat du versement.
        ``None`` : 100 % investi.
    transaction_cost:
        Coût proportionnel d'achat (ex. 0,001 = 0,10 %).
    initial_capital:
        Capital déjà investi au début (>= 0), sans frais d'entrée.
    fee_model:
        Modèle de frais par ordre ; remplace ``transaction_cost`` s'il est fourni.
    orders_per_month:
        Nombre d'ETF achetés chaque mois (défaut 1) pour ``fee_model``.

    Returns
    -------
    pd.DataFrame
        Colonnes ``Contribution``, ``Contribution Fees``,
        ``Cumulative Contributions``, ``Value``, ``Gain``.
    """
    if monthly_contribution < 0 or initial_capital < 0 or transaction_cost < 0:
        raise ValueError("Versement, capital initial et frais doivent être positifs ou nuls.")
    first = net_returns.first_valid_index()
    if first is None:
        raise ValueError("Aucun rendement exploitable pour la simulation DCA.")
    returns = net_returns.loc[first:]
    if returns.isna().any():
        raise ValueError("Les rendements contiennent des valeurs manquantes après le début de la série.")
    exposure = (
        pd.Series(1.0, index=returns.index)
        if invested_exposure is None
        else invested_exposure.reindex(returns.index).fillna(1.0).clip(0.0, 1.0)
    )

    value = float(initial_capital)
    contributed = float(initial_capital)
    rows = []
    orders = (pd.Series(1, index=returns.index) if orders_per_month is None
              else orders_per_month.reindex(returns.index).fillna(1).clip(lower=1).astype(int))
    for date_, ret in returns.items():
        invested = monthly_contribution * float(exposure.loc[date_])
        if fee_model is None:
            fees = transaction_cost * invested
        else:
            n = int(orders.loc[date_])
            fees = n * fee_model.order_cost(invested / n) if invested > 0 else 0.0
        value = (value + monthly_contribution - fees) * (1.0 + float(ret))
        contributed += monthly_contribution
        rows.append((date_, monthly_contribution, fees, contributed, value, value - contributed))
    frame = pd.DataFrame(rows, columns=["Date", "Contribution", "Contribution Fees", "Cumulative Contributions",
                                       "Value", "Gain"])
    return frame.set_index("Date")


def money_weighted_return(simulation: pd.DataFrame, initial_capital: float = 0.0) -> float | None:
    """TRI annualisé des flux (versements en début de mois, valeur finale en fin).

    Résolu par dichotomie sur le taux mensuel ; ``None`` si non défini.
    """
    contributions = simulation["Contribution"].to_numpy(dtype=float).copy()
    if contributions.size == 0:
        return None
    contributions[0] += initial_capital
    final_value = float(simulation["Value"].iloc[-1])
    n = contributions.size
    if contributions.sum() <= 0:
        return None

    def npv(rate: float) -> float:
        # Versement du mois k (début de mois) capitalisé jusqu'à la fin du mois n.
        periods = np.arange(n, 0, -1)
        return float(np.sum(contributions * (1.0 + rate) ** periods) - final_value)

    low, high = -0.99, 1.0
    if npv(low) * npv(high) > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2.0
        if npv(low) * npv(mid) <= 0:
            high = mid
        else:
            low = mid
    monthly = (low + high) / 2.0
    return float((1.0 + monthly) ** 12 - 1.0)


def summarize_dca(simulation: pd.DataFrame, net_returns: pd.Series, initial_capital: float = 0.0,
                  taxes: TaxConfig | None = None) -> dict:
    """Résumé chiffré d'une simulation DCA."""
    returns = net_returns.reindex(simulation.index)
    growth = (1.0 + returns).cumprod()
    drawdown = growth / growth.cummax() - 1.0
    value_drawdown = simulation["Value"] / simulation["Value"].cummax() - 1.0
    total = float(simulation["Cumulative Contributions"].iloc[-1])
    final = float(simulation["Value"].iloc[-1])
    years = len(simulation) / 12.0
    return {
        "contribution_fees_eur": float(simulation["Contribution Fees"].sum()),
        "final_value_net_eur": pea_net_value(final, total, years, taxes),
        "years": years,
        "start": simulation.index.min().date().isoformat(),
        "end": simulation.index.max().date().isoformat(),
        "n_months": int(len(simulation)),
        "total_contributed_eur": total,
        "final_value_eur": final,
        "gain_eur": final - total,
        "gain_pct": (final / total - 1.0) if total else None,
        "money_weighted_return": money_weighted_return(simulation, initial_capital),
        "strategy_max_drawdown": float(drawdown.min()),
        "worst_value_drawdown": float(value_drawdown.min()),
    }


def run_dca_comparison(
    strategy_returns: dict[str, pd.Series],
    monthly_contribution: float,
    *,
    exposures: dict[str, pd.Series] | None = None,
    transaction_cost: float = 0.0,
    start: str | pd.Timestamp | None = None,
    fee_model: FeeModel | None = None,
    orders: dict[str, pd.Series] | None = None,
    taxes: TaxConfig | None = None,
) -> dict:
    """Compare le DCA sur plusieurs stratégies, sur les **mêmes mois**.

    La fenêtre commune commence au premier mois où toutes les stratégies ont un
    rendement (ou à ``start`` si plus tardif).
    """
    if not strategy_returns:
        raise ValueError("Aucune stratégie à comparer.")
    exposures = exposures or {}
    orders = orders or {}
    first = max(series.first_valid_index() for series in strategy_returns.values())
    last = min(series.last_valid_index() for series in strategy_returns.values())
    if start is not None:
        first = max(first, pd.Timestamp(start))
    if first > last:
        raise ValueError("Pas de période commune entre les stratégies.")
    results: dict = {"monthly_contribution": float(monthly_contribution),
                     "transaction_cost": float(transaction_cost), "fee_model": fee_model,
                     "taxes": taxes or TaxConfig(), "strategies": {}, "values": {}}
    for name, series in strategy_returns.items():
        window = series.loc[first:last]
        simulation = simulate_dca(window, monthly_contribution, invested_exposure=exposures.get(name),
                                  transaction_cost=transaction_cost, fee_model=fee_model,
                                  orders_per_month=orders.get(name))
        results["strategies"][name] = summarize_dca(simulation, window, taxes=results["taxes"])
        results["values"][name] = simulation["Value"]
    any_summary = next(iter(results["strategies"].values()))
    results.update(start=any_summary["start"], end=any_summary["end"], n_months=any_summary["n_months"])
    return results


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _fees_line(results: dict) -> str:
    model = results.get("fee_model")
    if model is None:
        return (f"- Frais : {results['transaction_cost']:.2%} sur la part investie de chaque versement, "
                "plus les frais de rotation déjà inclus dans les rendements nets des stratégies.")
    return (f"- Frais des versements (barème configuré) : {model.proportional:.2%} + {model.fixed_per_order:.2f} € "
            f"par ordre (minimum {model.minimum_per_order:.2f} €), un ordre par ETF acheté ; frais de rotation "
            "des stratégies inclus dans leurs rendements nets (modèle proportionnel).")


def generate_dca_report(results: dict, output_path: str | Path, *, benchmark: str = "benchmark") -> Path:
    """Écrit le rapport Markdown du DCA et renvoie son chemin."""
    lines = [
        "# Versements mensuels programmés (DCA) — Projet 1B", "",
        f"Date de génération : {date.today().isoformat()}", "",
        "Simulation d'un versement mensuel fixe dans chaque stratégie, sur les mêmes mois. "
        "Usage éducatif : aucun ordre n'est exécuté.", "",
        "## Hypothèses", "",
        f"- Période : {results['start']} → {results['end']} ({results['n_months']} versements)",
        f"- Versement mensuel : {results['monthly_contribution']:,.2f} €",
        _fees_line(results),
        "- Versement en début de mois, rendement net du mois appliqué ensuite.",
        f"- Fiscalité : retrait total en fin de période ; PEA de plus de 5 ans = prélèvements sociaux "
        f"{results['taxes'].prelevements_sociaux_pct:.1f} % sur le gain (sinon flat tax "
        f"{results['taxes'].flat_tax_pct:.0f} %). Inflation non modélisée.", "",
        "## Résultats", "",
        "| Stratégie | Total versé | Valeur finale | Valeur nette d'impôt | Plus-value | TRI annualisé | "
        "Frais des versements | Max DD stratégie | Pire recul du capital |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, summary in results["strategies"].items():
        label = STRATEGY_LABELS.get(name, name).replace("benchmark", benchmark)
        lines.append(
            f"| {label} | {summary['total_contributed_eur']:,.2f} € | {summary['final_value_eur']:,.2f} € | "
            f"{summary['final_value_net_eur']:,.2f} € | "
            f"{summary['gain_eur']:,.2f} € ({_pct(summary['gain_pct'])}) | {_pct(summary['money_weighted_return'])} | "
            f"{summary['contribution_fees_eur']:,.2f} € | "
            f"{_pct(summary['strategy_max_drawdown'])} | {_pct(summary['worst_value_drawdown'])} |"
        )
    best = max(results["strategies"].items(), key=lambda item: item[1]["final_value_eur"])
    lines += [
        "",
        "## Lecture", "",
        f"- Valeur finale la plus élevée : {STRATEGY_LABELS.get(best[0], best[0]).replace('benchmark', benchmark)}.",
        "- Le « pire recul du capital » mesure la baisse maximale de la valeur du portefeuille (versements "
        "inclus) : c'est la perte que tu aurais vue sur ton relevé.",
        "- Une valeur finale plus élevée sur une seule période ne prouve pas la supériorité d'une stratégie.", "",
        "## Limites", "",
        "- Historique court (depuis 2015) et majoritairement haussier.",
        "- Données Yahoo Finance non officielles ; frais réels du courtier à vérifier.",
        "- Les performances passées ne préjugent pas des performances futures.", "",
    ]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path

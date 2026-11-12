"""Moteur de backtest unique des études (recherche, robustesse, stress, plans).

Un seul chemin pour transformer des poids en rendements, avec les conventions
du laboratoire : poids **exécutés** (déjà décalés d'un mois), frais au
turnover, cash explicite éventuellement rémunéré, et période de chauffe
exclue (les mois antérieurs à la première exposition investie ne comptent
pas dans les statistiques). Le pipeline mensuel garde son orchestration
propre (alertes, rapport) mais s'appuie sur la même fonction de backtest.

Aucun ordre n'est passé : ce module ne fait que des calculs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.backtest import CASH_COLUMN, backtest_monthly_allocation
from src.strategies import StrategyContext, available_strategies, build_strategy


def run_backtest(monthly: pd.DataFrame, weights: pd.DataFrame, cost: float,
                 cash_return: float | pd.Series = 0.0) -> pd.DataFrame:
    """Backtest mensuel de poids exécutés (colonnes = actifs + ``CASH``)."""
    assets = [c for c in weights.columns if c != CASH_COLUMN]
    # Un actif non encore coté a un poids nul par construction ; son rendement NaN compte pour 0.
    return backtest_monthly_allocation(monthly[assets], weights, transaction_cost=cost, cash_return=cash_return)


def first_invested(backtest: pd.DataFrame) -> pd.Timestamp | None:
    invested = backtest["Invested Exposure"] > 0
    return invested[invested].index.min() if invested.any() else None


def active_returns(backtest: pd.DataFrame) -> pd.Series:
    """Rendements nets, NaN avant la première exposition investie (chauffe exclue)."""
    returns = backtest["Net Return"].copy()
    start = first_invested(backtest)
    if start is not None:
        returns.loc[returns.index < start] = np.nan
    return returns


def net_returns(monthly: pd.DataFrame, weights: pd.DataFrame, cost: float,
                cash_return: float | pd.Series = 0.0) -> pd.Series:
    """Raccourci : rendements nets actifs d'un jeu de poids exécutés."""
    return active_returns(run_backtest(monthly, weights, cost, cash_return))


@dataclass(frozen=True)
class StrategyRun:
    """Résultat d'une stratégie du registre sur un jeu de prix mensuels."""

    name: str
    target: pd.DataFrame
    executed: pd.DataFrame
    backtest: pd.DataFrame

    @property
    def first_invested(self) -> pd.Timestamp | None:
        return first_invested(self.backtest)

    @property
    def returns(self) -> pd.Series:
        return active_returns(self.backtest)


def run_strategy(name: str, monthly: pd.DataFrame, ctx: StrategyContext, *, cost: float,
                 cash_return: float | pd.Series = 0.0) -> StrategyRun:
    bundle = build_strategy(name, monthly, ctx)
    executed = bundle["executed_weights"]
    return StrategyRun(name=name, target=bundle["target_weights"], executed=executed,
                       backtest=run_backtest(monthly, executed, cost, cash_return))


def run_strategies(monthly: pd.DataFrame, ctx: StrategyContext, *, cost: float, names=None,
                   cash_return: float | pd.Series = 0.0) -> dict[str, StrategyRun]:
    """Toutes les stratégies calculables (ou ``names``), dans l'ordre du registre."""
    wanted = available_strategies(monthly, ctx) if names is None else list(names)
    return {name: run_strategy(name, monthly, ctx, cost=cost, cash_return=cash_return) for name in wanted}

"""Modèle de données typé du rapport mensuel (sérialisé par ``src/reporting.py``).

Extrait de ``src/monthly_pipeline.py`` (v6) ; les noms restent importables depuis ce dernier.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd


@dataclass
class Alert:
    level: str  # INFO | WARNING | CRITICAL
    code: str
    title: str
    message: str
    timestamp: str
    context: dict


@dataclass
class StrategyReport:
    name: str
    description: str
    selected_assets: list[str]
    target_weights: dict[str, float] | None
    executed_weights: dict[str, float] | None
    cash_weight: float | None
    invested_exposure: float | None
    momentum: dict[str, float] | None
    trend_filter: dict[str, bool] | None
    realized_volatility: float | None
    target_volatility: float | None
    cagr: float | None
    annualized_volatility: float | None
    sharpe: float | None
    max_drawdown: float | None
    recent_return: float | None
    theoretical_capital: float | None
    turnover: float | None
    cumulative_cost: float | None
    signal_date: str
    enabled: bool = True
    status: str = "ACTIVE"


@dataclass
class MonthlyReport:
    metadata: dict
    data_quality: dict
    universe: dict
    benchmark: StrategyReport
    momentum_strategy: StrategyReport
    volatility_targeted_strategy: StrategyReport
    allocation_comparison: dict
    risk: dict
    alerts: list[Alert]
    manual_decision: dict
    previous_comparison: dict | None = None
    policy: dict | None = None  # 1.3 : politique suivie et son allocation cible
    strategies: dict | None = None  # 1.3 : toutes les stratégies du registre


@dataclass
class MonthlyPipelineResult:
    report: MonthlyReport
    # Artefacts bruts pour inspection dans le notebook (non sérialisés en JSON).
    monthly_prices: pd.DataFrame
    momentum_backtest: pd.DataFrame
    vt_backtest: pd.DataFrame | None  # None si le VT est désactivé
    benchmark_backtest: pd.DataFrame
    # Poids exécutés et volatilité réalisée (graphiques du rapport).
    momentum_weights: pd.DataFrame | None = None
    vt_weights: pd.DataFrame | None = None
    realized_volatility: pd.Series | None = None
    # Backtests de toutes les stratégies du registre (clé = nom) et nom suivi.
    strategy_backtests: dict | None = None
    followed_strategy: str | None = None


def _clean_float(value: object) -> float | None:
    """Convertit en float Python, en remplaçant NaN/inf par None."""
    if value is None:
        return None
    number = float(value)  # type: ignore[arg-type]
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _weights_to_dict(weights: pd.Series) -> dict[str, float]:
    return {str(k): float(v) for k, v in weights.items()}

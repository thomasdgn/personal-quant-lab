"""Registre unique des stratégies (rapport mensuel, recherche, journal, plan).

Chaque stratégie produit des **poids cibles** décidés en fin de mois ``M`` avec
l'information disponible en ``M`` (colonnes = actifs + ``CASH``, somme = 1).
Les poids **exécutés** s'en déduisent par un décalage d'un mois
(``lag_weights_for_execution``) : même convention anti look-ahead partout.

Stratégies disponibles :

- ``benchmark``      : 100 % benchmark (Buy & Hold rebalancé) ;
- ``momentum``       : momentum 12-1 + filtre MA, top N (paramètres de la config) ;
- ``momentum_vt``    : momentum + volatility targeting (exposition décidée avec la
  volatilité connue en fin de mois) ;
- ``inverse_vol``    : actions pondérées par 1 / volatilité 12 mois ;
- ``static_80_20`` / ``static_60_40`` : benchmark / obligataire, rebalancés ;
- ``dual_momentum``  : meilleure action vs obligataire vs cash ;
- ``top3_trend``     : top 3 équipondéré + filtre de tendance ;
- ``core_satellite`` : part cœur (benchmark) + part satellite (autre stratégie) ;
- ``allocation_fixe`` : allocation fixe définie dans la politique (``allocation_fixe``
  de ``config/policy.yaml``), par exemple 85 % Monde / 15 % émergents.

Aucune stratégie ne passe d'ordre : ce module ne calcule que des poids.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

import numpy as np
import pandas as pd

from src.backtest import CASH_COLUMN
from src.features import compute_momentum
from src.portfolio import apply_volatility_target, build_vol_targeted_weights
from src.signals import build_momentum_weights, lag_weights_for_execution


@dataclass(frozen=True)
class StrategyContext:
    """Paramètres partagés par les stratégies.

    ``config`` est un ``MonthlyPipelineConfig`` ; ``equities`` les actions
    candidates (hors obligataire) ; ``bond`` l'obligataire de référence.
    """

    config: object
    equities: tuple[str, ...] = ()
    bond: str | None = "OBLI.PA"
    core_weight: float = 0.8
    satellite: str = "momentum_vt"
    extras: dict = field(default_factory=dict)
    fixed_allocation: tuple[tuple[str, float], ...] = ()  # (ticker, poids) de la politique

    @property
    def benchmark(self) -> str:
        return self.config.benchmark_ticker  # type: ignore[attr-defined]


Builder = Callable[[pd.DataFrame, StrategyContext], pd.DataFrame]


@dataclass(frozen=True)
class StrategyDef:
    name: str
    label: str
    description: str
    builder: Builder
    needs_bond: bool = False


def cash_frame(index: pd.Index, columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(0.0, index=index, columns=[*columns, CASH_COLUMN])
    frame[CASH_COLUMN] = 1.0
    return frame


# --------------------------------------------------------------------------- #
# Constructeurs de poids cibles
# --------------------------------------------------------------------------- #
def momentum_target(monthly: pd.DataFrame, config, *, lookback: int | None = None, skip: int | None = None,
                    ma: int | None = None, top_n: int | None = None, vt: bool = False) -> pd.DataFrame:
    """Momentum (+ VT) ; paramètres par défaut = configuration."""
    m = config.momentum
    lookback = m.lookback_months if lookback is None else lookback
    skip = m.skip_months if skip is None else skip
    bundle = build_momentum_weights(
        monthly, lookback_months=lookback, skip_months=skip,
        ma_window=m.moving_average_window if ma is None else ma,
        top_n=m.top_n if top_n is None else top_n,
        require_positive_momentum=m.require_positive_momentum, already_monthly=True,
    )
    if not vt:
        return bundle["target_weights"]
    v = config.volatility_targeting
    vt_bundle = build_vol_targeted_weights(
        monthly, bundle["executed_weights"], target_volatility=v.target_volatility,
        vol_window=v.volatility_window, min_exposure=v.min_exposure, max_exposure=v.max_exposure,
    )
    # Cible VT = cible Momentum × exposition connue en fin de mois (NaN -> cash).
    exposure = cast(pd.Series, vt_bundle["target_exposure"])
    return apply_volatility_target(bundle["target_weights"], exposure.fillna(0.0))


def static_target(monthly: pd.DataFrame, allocation: dict[str, float]) -> pd.DataFrame:
    """Allocation fixe, active seulement quand tous les actifs cotent."""
    target = cash_frame(monthly.index, list(allocation))
    available = monthly[list(allocation)].notna().all(axis=1)
    for asset, weight in allocation.items():
        target.loc[available, asset] = weight
    target.loc[available, CASH_COLUMN] = 1.0 - sum(allocation.values())
    return target


def dual_momentum_target(monthly: pd.DataFrame, equities: list[str], bond: str, lookback: int = 12) -> pd.DataFrame:
    momentum = compute_momentum(monthly[[*equities, bond]], lookback, 1)
    target = cash_frame(monthly.index, [*equities, bond])
    eq = momentum[equities]
    bond_mom = momentum[bond]
    has_equity = eq.notna().any(axis=1)
    best_value = eq.max(axis=1)
    # idxmax sur -inf pour les NaN : premier maximum, comme la version ligne à ligne.
    best_asset = eq.fillna(-np.inf).idxmax(axis=1)
    choose_equity = has_equity & (best_value > bond_mom.fillna(0.0).clip(lower=0.0))
    choose_bond = ~choose_equity & bond_mom.notna() & (bond_mom > 0)
    columns = list(target.columns)
    values = target.to_numpy(copy=True)
    cash_col = columns.index(CASH_COLUMN)
    for rows, picks in ((np.flatnonzero(choose_equity.to_numpy()), best_asset[choose_equity]),
                        (np.flatnonzero(choose_bond.to_numpy()), pd.Series(bond, index=bond_mom.index)[choose_bond])):
        if len(rows):
            values[rows, :] = 0.0
            values[rows, [columns.index(p) for p in picks]] = 1.0
    values[:, cash_col] = 1.0 - np.delete(values, cash_col, axis=1).sum(axis=1)
    return pd.DataFrame(values, index=target.index, columns=columns)


def inverse_vol_target(monthly: pd.DataFrame, equities: list[str], window: int = 12) -> pd.DataFrame:
    vol = monthly[equities].pct_change(fill_method=None).rolling(window, min_periods=window).std()
    inverse = (1.0 / vol).replace([np.inf, -np.inf], np.nan)
    target = cash_frame(monthly.index, equities)
    valid = inverse.notna().any(axis=1)
    scaled = inverse.div(inverse.sum(axis=1), axis=0).fillna(0.0)
    target.loc[valid, equities] = scaled.loc[valid]
    target.loc[valid, CASH_COLUMN] = 0.0
    return target


def core_satellite_target(monthly: pd.DataFrame, ctx: StrategyContext) -> pd.DataFrame:
    if ctx.satellite == "core_satellite" or ctx.satellite not in REGISTRY:
        raise ValueError(f"Satellite invalide : {ctx.satellite}.")
    core = static_target(monthly, {ctx.benchmark: 1.0})
    satellite = build_target(ctx.satellite, monthly, ctx)
    columns = list(dict.fromkeys([*core.columns, *satellite.columns]))
    core = core.reindex(columns=columns, fill_value=0.0)
    satellite = satellite.reindex(columns=columns, fill_value=0.0)
    return ctx.core_weight * core + (1.0 - ctx.core_weight) * satellite


def _fixed(ctx: StrategyContext) -> dict[str, float]:
    if not ctx.fixed_allocation:
        raise ValueError("allocation_fixe : aucune allocation définie dans la politique (config/policy.yaml).")
    return dict(ctx.fixed_allocation)


def _bond(ctx: StrategyContext) -> str:
    if not ctx.bond:
        raise ValueError("Cette stratégie nécessite un obligataire (rôle defensive).")
    return ctx.bond


def _equities(monthly: pd.DataFrame, ctx: StrategyContext) -> list[str]:
    equities = [c for c in ctx.equities if c in monthly.columns] if ctx.equities else \
        [c for c in monthly.columns if c != ctx.bond]
    if not equities:
        raise ValueError("Aucune action candidate pour la stratégie.")
    return equities


REGISTRY: dict[str, StrategyDef] = {
    "benchmark": StrategyDef("benchmark", "Buy & Hold {benchmark}",
                             "100 % benchmark, toujours investi.",
                             lambda m, c: static_target(m, {c.benchmark: 1.0})),
    "momentum": StrategyDef("momentum", "Momentum défensif",
                            "Meilleur(s) ETF au-dessus de leur moyenne mobile, sinon cash.",
                            lambda m, c: momentum_target(m, c.config)),
    "momentum_vt": StrategyDef("momentum_vt", "Momentum + Volatility Targeting",
                               "Momentum dont l'exposition est ajustée par la volatilité réalisée.",
                               lambda m, c: momentum_target(m, c.config, vt=True)),
    "inverse_vol": StrategyDef("inverse_vol", "Inverse volatilité (actions)",
                               "Actions pondérées par l'inverse de leur volatilité 12 mois.",
                               lambda m, c: inverse_vol_target(m, _equities(m, c))),
    "static_80_20": StrategyDef("static_80_20", "80/20 {benchmark} / {bond}",
                                "80 % benchmark, 20 % obligataire, rebalancés chaque mois.",
                                lambda m, c: static_target(m, {c.benchmark: 0.8, _bond(c): 0.2}), needs_bond=True),
    "static_60_40": StrategyDef("static_60_40", "60/40 {benchmark} / {bond}",
                                "60 % benchmark, 40 % obligataire, rebalancés chaque mois.",
                                lambda m, c: static_target(m, {c.benchmark: 0.6, _bond(c): 0.4}), needs_bond=True),
    "dual_momentum": StrategyDef("dual_momentum", "Dual momentum (actions / obligataire / cash)",
                                 "Meilleure action si elle bat l'obligataire et zéro, sinon obligataire ou cash.",
                                 lambda m, c: dual_momentum_target(m, _equities(m, c), _bond(c)), needs_bond=True),
    "top3_trend": StrategyDef("top3_trend", "Top 3 équipondéré + tendance",
                              "Trois meilleurs ETF (momentum 12-1) au-dessus de leur MA 10 mois.",
                              lambda m, c: momentum_target(m, c.config, lookback=12, skip=1, ma=10, top_n=3)),
    "core_satellite": StrategyDef("core_satellite", "Cœur / satellite",
                                  "Part cœur en benchmark, part satellite dans une autre stratégie du registre.",
                                  core_satellite_target),
    "allocation_fixe": StrategyDef("allocation_fixe", "Allocation fixe",
                                   "Allocation fixe choisie dans la politique, rééquilibrée par les versements.",
                                   lambda m, c: static_target(m, _fixed(c))),
}


def strategy_names() -> list[str]:
    return list(REGISTRY)


def available_strategies(monthly: pd.DataFrame, ctx: StrategyContext) -> list[str]:
    """Stratégies calculables avec les colonnes disponibles."""
    has_bond = ctx.bond is not None and ctx.bond in monthly.columns
    names = [n for n, d in REGISTRY.items() if has_bond or not d.needs_bond]
    if ctx.satellite not in names or ctx.satellite == "core_satellite":
        names.remove("core_satellite")
    if not ctx.fixed_allocation or any(t not in monthly.columns for t, _ in ctx.fixed_allocation):
        names.remove("allocation_fixe")
    return names


def label(name: str, ctx: StrategyContext) -> str:
    definition = REGISTRY[name]
    text = definition.label.format(benchmark=ctx.benchmark, bond=ctx.bond or "obligataire")
    if name == "core_satellite":
        text += f" ({ctx.core_weight:.0%} {ctx.benchmark} + {1 - ctx.core_weight:.0%} {ctx.satellite})"
    if name == "allocation_fixe" and ctx.fixed_allocation:
        text += " (" + " + ".join(f"{w:.0%} {t}" for t, w in ctx.fixed_allocation) + ")"
    return text


def build_target(name: str, monthly: pd.DataFrame, ctx: StrategyContext) -> pd.DataFrame:
    """Poids cibles d'une stratégie.

    ``ctx.extras["cache"]`` (optionnel) mémorise les cibles déjà calculées pour
    **ces** prix mensuels (un contexte par jeu de prix) : évite de recalculer le
    satellite du cœur/satellite ou des cibles fournies par l'appelant.
    """
    if name not in REGISTRY:
        raise ValueError(f"Stratégie inconnue : {name}. Disponibles : {', '.join(REGISTRY)}.")
    cache = ctx.extras.get("cache")
    if cache is not None and name in cache:
        return cache[name]
    target = REGISTRY[name].builder(monthly, ctx)
    if cache is not None:
        cache[name] = target
    if not np.allclose(target.sum(axis=1), 1.0, atol=1e-9):
        raise ValueError(f"Poids cibles de {name} ne sommant pas à 1.")
    return target


def build_strategy(name: str, monthly: pd.DataFrame, ctx: StrategyContext) -> dict[str, pd.DataFrame]:
    """``{"target_weights", "executed_weights"}`` (exécution décalée d'un mois)."""
    target = build_target(name, monthly, ctx)
    return {"target_weights": target, "executed_weights": lag_weights_for_execution(target)}

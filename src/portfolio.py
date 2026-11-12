"""Contrôle du risque par Volatility Targeting (Projet 3).

Objectif : ajuster la **taille** de l'exposition selon le risque observé, sans
chercher à prédire le rendement. Lorsque la volatilité réalisée monte,
l'exposition baisse ; lorsqu'elle baisse, l'exposition remonte, plafonnée à
100 % (aucun levier, aucun poids négatif). Le reste va au cash.

Fonctions :

- ``compute_target_exposure`` : ``clip(vol_cible / vol_réalisée, min, max)`` ;
- ``apply_volatility_target`` : met à l'échelle des poids Momentum par
  l'exposition, le reste en cash ;
- ``build_vol_targeted_weights`` : orchestration (vol de la stratégie de base ->
  exposition -> décalage d'un mois -> poids finaux).

Convention anti-look-ahead : l'exposition tenue pendant le mois ``t`` n'utilise
que la volatilité connue jusqu'à ``t-1`` (décalage explicite d'une période).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.backtest import CASH_COLUMN, backtest_monthly_allocation
from src.features import rolling_annualized_volatility


def compute_target_exposure(
    realized_volatility: pd.Series | pd.DataFrame,
    target_volatility: float = 0.10,
    min_exposure: float = 0.0,
    max_exposure: float = 1.0,
) -> pd.Series | pd.DataFrame:
    """Exposition cible ``clip(vol_cible / vol_réalisée, min, max)``.

    Comportements explicites :

    - volatilité **NaN** (historique insuffisant) -> exposition ``0`` (cash) ;
    - volatilité **nulle** -> exposition plafonnée à ``max_exposure`` (aucun
      risque observé ; jamais de levier puisque ``max_exposure <= 1``) ;
    - sinon, l'exposition décroît quand la volatilité réalisée augmente.

    Parameters
    ----------
    realized_volatility:
        Volatilité réalisée (annualisée), Series ou DataFrame.
    target_volatility:
        Volatilité annualisée visée (> 0).
    min_exposure, max_exposure:
        Bornes d'exposition. ``0 <= min <= max <= 1`` (version sans levier).

    Returns
    -------
    pd.Series | pd.DataFrame
        Exposition dans ``[min_exposure, max_exposure]``, même forme que
        l'entrée.

    Raises
    ------
    ValueError
        Paramètres invalides ou volatilité négative.
    """
    if target_volatility <= 0:
        raise ValueError("target_volatility doit être strictement positif.")
    if min_exposure < 0:
        raise ValueError("min_exposure ne peut pas être négatif.")
    if min_exposure > max_exposure:
        raise ValueError("min_exposure ne peut pas dépasser max_exposure.")
    if max_exposure > 1.0:
        raise ValueError("max_exposure ne peut pas dépasser 1 (aucun levier).")

    vol = realized_volatility
    vol_values = vol.to_numpy()
    finite = ~pd.isna(vol_values)
    if np.any(vol_values[finite] < 0):
        raise ValueError("La volatilité réalisée ne peut pas être négative.")

    # Division protégée : vol == 0 -> +inf -> ramené à max par le clip.
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = target_volatility / vol

    exposure = raw.clip(lower=min_exposure, upper=max_exposure)
    # Volatilité indisponible (NaN) -> pas de mesure de risque -> 0 % (cash).
    exposure = exposure.mask(vol.isna(), 0.0)
    return exposure


def apply_volatility_target(
    base_weights: pd.DataFrame,
    target_exposure: pd.Series,
    cash_column: str = CASH_COLUMN,
) -> pd.DataFrame:
    """Met à l'échelle des poids Momentum par l'exposition cible, reste en cash.

    Les poids d'actifs sont multipliés par l'exposition ; la part non investie
    (y compris ce que l'exposition retire) est allouée au cash. Un portefeuille
    100 % cash le reste. Les poids finaux sont dans ``[0, 1]`` et totalisent 1.

    Parameters
    ----------
    base_weights:
        Poids Momentum (colonnes = actifs + ``cash_column``), sommant à 1.
    target_exposure:
        Exposition par date, dans ``[0, 1]``, **déjà décalée** pour l'exécution.
        Un ``NaN`` est traité comme 0 (100 % cash).
    cash_column:
        Nom de la colonne de cash.

    Returns
    -------
    pd.DataFrame
        Poids finaux, mêmes colonnes que ``base_weights``.

    Raises
    ------
    ValueError
        Colonne cash absente, index désalignés, ou exposition hors ``[0, 1]``.
    """
    if cash_column not in base_weights.columns:
        raise ValueError(f"La colonne cash '{cash_column}' est absente des poids de base.")
    if not isinstance(target_exposure, pd.Series):
        raise ValueError("target_exposure doit être une Series indexée par date.")
    if not base_weights.index.equals(target_exposure.index):
        raise ValueError("base_weights et target_exposure doivent partager le même index.")

    exposure = target_exposure.fillna(0.0)
    if ((exposure < -1e-9) | (exposure > 1.0 + 1e-9)).any():
        raise ValueError("L'exposition doit être comprise entre 0 et 1.")

    asset_cols = [c for c in base_weights.columns if c != cash_column]

    final = base_weights.copy()
    final[asset_cols] = base_weights[asset_cols].mul(exposure, axis=0)
    # Le cash absorbe tout le reste : garantit une somme de poids égale à 1.
    final[cash_column] = 1.0 - final[asset_cols].sum(axis=1)
    return final


def build_vol_targeted_weights(
    monthly_prices: pd.DataFrame,
    base_executed_weights: pd.DataFrame,
    target_volatility: float = 0.10,
    vol_window: int = 3,
    periods_per_year: int = 12,
    min_exposure: float = 0.0,
    max_exposure: float = 1.0,
    cash_col: str = CASH_COLUMN,
) -> dict[str, object]:
    """Enchaîne vol de la stratégie de base -> exposition -> décalage -> poids.

    Étapes :

    1. rendements nets mensuels de la stratégie Momentum de base (via
       ``backtest_monthly_allocation``, frais nuls : on mesure le risque de la
       stratégie, pas son coût) ;
    2. volatilité réalisée glissante ``rolling_annualized_volatility`` ;
    3. exposition cible ``compute_target_exposure`` (connue en fin de mois) ;
    4. **décalage d'un mois** : l'exposition appliquée au mois ``t`` est celle
       connue en ``t-1`` (``shift(1)``) -> aucune anticipation ;
    5. poids finaux ``apply_volatility_target``.

    Parameters
    ----------
    monthly_prices:
        Prix mensuels des actifs (colonnes = tickers).
    base_executed_weights:
        Poids Momentum déjà exécutés (décalés), colonnes = actifs + ``cash_col``.
    target_volatility, vol_window, periods_per_year, min_exposure, max_exposure:
        Paramètres du volatility targeting.
    cash_col:
        Nom de la colonne de cash.

    Returns
    -------
    dict
        ``{"base_returns", "realized_volatility", "target_exposure",
        "executed_exposure", "final_weights"}``.
    """
    base_bt = backtest_monthly_allocation(
        monthly_prices, base_executed_weights, transaction_cost=0.0, cash_col=cash_col
    )
    base_returns = base_bt["Net Return"]

    realized_vol = rolling_annualized_volatility(base_returns, vol_window, periods_per_year)
    target_exposure = compute_target_exposure(
        realized_vol, target_volatility, min_exposure, max_exposure
    )

    # Décalage anti-look-ahead : la vol connue fin de mois t sert au mois t+1.
    executed_exposure = target_exposure.shift(1)

    final_weights = apply_volatility_target(base_executed_weights, executed_exposure, cash_col)

    return {
        "base_returns": base_returns,
        "realized_volatility": realized_vol,
        "target_exposure": target_exposure,
        "executed_exposure": executed_exposure,
        "final_weights": final_weights,
    }

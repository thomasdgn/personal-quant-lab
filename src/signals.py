"""Signaux et poids cibles pour la stratégie Momentum défensive PEA (Projet 2).

Chaîne logique :

1. ``compute_eligibility`` : quels actifs sont sélectionnables à chaque date
   (momentum disponible, tendance positive, momentum positif en option) ;
2. ``rank_by_momentum`` : classement des actifs éligibles, du meilleur au moins bon ;
3. ``select_top_n_weights`` : poids cibles équipondérés sur les ``top_n`` meilleurs,
   le reste en cash ;
4. ``lag_weights_for_execution`` : décalage d'un mois (le signal de fin de mois M
   est exécuté au mois M+1) ;
5. ``build_momentum_weights`` : orchestration légère (features -> poids exécutés).

Convention : une colonne dédiée ``CASH`` porte la part non investie. Les poids
sont compris entre 0 et 1 et totalisent 1 à chaque date valide.
"""

from __future__ import annotations

import pandas as pd

from src.features import (
    compute_momentum,
    compute_moving_average,
    compute_trend_filter,
    to_monthly_prices,
)

CASH_COLUMN = "CASH"


def _as_dataframe(data: pd.Series | pd.DataFrame) -> pd.DataFrame:
    """Convertit une Series en DataFrame à une colonne, sinon renvoie tel quel."""
    if isinstance(data, pd.Series):
        return data.to_frame()
    return data


def compute_eligibility(
    momentum: pd.DataFrame,
    trend_filter: pd.DataFrame,
    require_positive_momentum: bool = False,
) -> pd.DataFrame:
    """Masque booléen des actifs éligibles à chaque date.

    Un actif est éligible si son momentum est disponible **et** que le filtre de
    tendance est positif. En option, on exige aussi un momentum strictement
    positif.

    Parameters
    ----------
    momentum:
        Momentum par actif (colonnes = actifs).
    trend_filter:
        Masque booléen de tendance, même forme que ``momentum``.
    require_positive_momentum:
        Si ``True``, n'accepte que les actifs à momentum strictement positif.

    Returns
    -------
    pd.DataFrame
        Masque booléen d'éligibilité.
    """
    momentum = _as_dataframe(momentum)
    trend_filter = _as_dataframe(trend_filter)

    if not momentum.index.equals(trend_filter.index):
        raise ValueError("Les index du momentum et du filtre de tendance diffèrent.")
    if not momentum.columns.equals(trend_filter.columns):
        raise ValueError("Les colonnes du momentum et du filtre de tendance diffèrent.")

    eligible = momentum.notna() & trend_filter.astype(bool)
    if require_positive_momentum:
        eligible &= momentum > 0
    return eligible


def rank_by_momentum(
    momentum: pd.DataFrame,
    eligible: pd.DataFrame,
) -> pd.DataFrame:
    """Classe les actifs éligibles par momentum décroissant (1 = meilleur).

    Les actifs non éligibles reçoivent ``NaN`` (pas de rang). Les dates sans
    aucun actif éligible ont une ligne entièrement ``NaN``.

    Parameters
    ----------
    momentum:
        Momentum par actif.
    eligible:
        Masque booléen d'éligibilité, même forme que ``momentum``.

    Returns
    -------
    pd.DataFrame
        Rangs (1 = meilleur momentum), ``NaN`` pour les non-éligibles.
    """
    momentum = _as_dataframe(momentum)
    eligible = _as_dataframe(eligible)

    if not momentum.index.equals(eligible.index):
        raise ValueError("Les index du momentum et de l'éligibilité diffèrent.")
    if not momentum.columns.equals(eligible.columns):
        raise ValueError("Les colonnes du momentum et de l'éligibilité diffèrent.")

    eligible_momentum = momentum.where(eligible)
    # method="first" départage les ex aequo de façon déterministe (ordre des colonnes).
    return eligible_momentum.rank(axis=1, ascending=False, method="first")


def select_top_n_weights(
    momentum: pd.DataFrame,
    eligible: pd.DataFrame,
    top_n: int = 1,
    cash_col: str = CASH_COLUMN,
) -> pd.DataFrame:
    """Poids cibles : équipondération des ``top_n`` meilleurs, reste en cash.

    Convention : il y a ``top_n`` « emplacements », chacun pesant ``1 / top_n``.
    Un emplacement non pourvu (moins de ``top_n`` actifs éligibles) reste en
    cash. Ainsi :

    - ``top_n=1``, 1 éligible -> actif 100 % ;
    - ``top_n=2``, 2 éligibles -> 50 % / 50 % ;
    - ``top_n=2``, 1 éligible -> 50 % actif + 50 % cash ;
    - 0 éligible -> 100 % cash.

    Les poids sont dans ``[0, 1]`` et totalisent 1 à chaque date.

    Parameters
    ----------
    momentum:
        Momentum par actif.
    eligible:
        Masque booléen d'éligibilité.
    top_n:
        Nombre d'emplacements investis. Doit être strictement positif.
    cash_col:
        Nom de la colonne de cash.

    Returns
    -------
    pd.DataFrame
        Poids par actif + colonne cash, indexés comme le momentum.
    """
    if top_n <= 0:
        raise ValueError("top_n doit être strictement positif.")

    momentum = _as_dataframe(momentum)
    eligible = _as_dataframe(eligible)
    if cash_col in momentum.columns:
        raise ValueError(f"Le nom de colonne cash '{cash_col}' entre en conflit avec un actif.")

    ranks = rank_by_momentum(momentum, eligible)
    # Emplacement pourvu si l'actif est classé dans le top_n.
    selected = ranks.le(top_n) & ranks.notna()

    per_slot = 1.0 / top_n
    weights = selected.astype(float) * per_slot

    cash_weight = 1.0 - weights.sum(axis=1)
    # Sécurité numérique : pas de cash légèrement négatif dû aux flottants.
    cash_weight = cash_weight.clip(lower=0.0)
    weights[cash_col] = cash_weight
    return weights


def lag_weights_for_execution(
    target_weights: pd.DataFrame,
    periods: int = 1,
    cash_col: str = CASH_COLUMN,
) -> pd.DataFrame:
    """Décale les poids cibles pour l'exécution (signal M -> exécution M+1).

    Les poids décidés à la fin du mois M ne peuvent être appliqués qu'au mois
    M+1. Après décalage, les premières périodes (non investissables faute de
    signal antérieur) sont mises à 100 % cash.

    Parameters
    ----------
    target_weights:
        Poids cibles incluant la colonne cash.
    periods:
        Nombre de périodes de décalage (>= 1).
    cash_col:
        Nom de la colonne de cash.

    Returns
    -------
    pd.DataFrame
        Poids exécutés, mêmes colonnes que ``target_weights``.
    """
    if periods < 1:
        raise ValueError("periods doit être supérieur ou égal à 1.")
    if cash_col not in target_weights.columns:
        raise ValueError(f"La colonne cash '{cash_col}' est absente des poids cibles.")

    executed = target_weights.shift(periods)

    # Les premières lignes n'ont pas de signal antérieur -> 100 % cash.
    leading = executed[cash_col].isna()
    executed.loc[leading, :] = 0.0
    executed.loc[leading, cash_col] = 1.0
    return executed


def build_momentum_weights(
    prices: pd.DataFrame,
    lookback_months: int = 12,
    skip_months: int = 1,
    ma_window: int = 10,
    top_n: int = 1,
    use_trend_filter: bool = True,
    require_positive_momentum: bool = False,
    already_monthly: bool = False,
    cash_col: str = CASH_COLUMN,
) -> dict[str, pd.DataFrame]:
    """Orchestration : des prix aux poids exécutés (features -> signaux -> lag).

    Fonction de commodité pour le notebook et les backtests comparatifs. Ne fait
    qu'enchaîner les briques du module, sans logique nouvelle.

    Parameters
    ----------
    prices:
        Prix des actifs (colonnes = tickers). Quotidiens par défaut.
    lookback_months, skip_months:
        Paramètres du momentum.
    ma_window:
        Fenêtre de la moyenne mobile de tendance.
    top_n:
        Nombre d'actifs retenus.
    use_trend_filter:
        Si ``False``, la tendance est considérée toujours vraie (momentum pur).
    require_positive_momentum:
        Exiger un momentum strictement positif.
    already_monthly:
        Si ``True``, ``prices`` est déjà mensuel (pas de reconversion).
    cash_col:
        Nom de la colonne de cash.

    Returns
    -------
    dict[str, pd.DataFrame]
        Dictionnaire ``{"monthly_prices", "momentum", "moving_average",
        "trend_filter", "eligible", "target_weights", "executed_weights"}``.
    """
    monthly_prices = prices if already_monthly else to_monthly_prices(prices)
    monthly_prices = _as_dataframe(monthly_prices)

    momentum = compute_momentum(monthly_prices, lookback_months, skip_months)
    moving_average = compute_moving_average(monthly_prices, ma_window)

    if use_trend_filter:
        trend_filter = compute_trend_filter(monthly_prices, moving_average)
    else:
        # Momentum pur : tout le monde passe le filtre de tendance.
        trend_filter = pd.DataFrame(
            True, index=monthly_prices.index, columns=monthly_prices.columns
        )

    eligible = compute_eligibility(momentum, trend_filter, require_positive_momentum)
    target_weights = select_top_n_weights(momentum, eligible, top_n, cash_col)
    executed_weights = lag_weights_for_execution(target_weights, periods=1, cash_col=cash_col)

    return {
        "monthly_prices": monthly_prices,
        "momentum": momentum,
        "moving_average": moving_average,
        "trend_filter": trend_filter,
        "eligible": eligible,
        "target_weights": target_weights,
        "executed_weights": executed_weights,
    }

"""Features mensuelles pour la stratégie Momentum défensive PEA (Projet 2).

Ce module transforme des prix (quotidiens ou déjà mensuels) en features
utilisables par la couche de signaux :

- ``to_monthly_prices`` : passage à une fréquence mensuelle (dernier prix
  réellement disponible de chaque mois) ;
- ``compute_momentum`` : momentum ``prix(t-skip) / prix(t-lookback) - 1`` ;
- ``compute_moving_average`` : moyenne mobile simple ;
- ``compute_trend_filter`` : filtre de tendance ``prix > moyenne mobile``.

Aucune donnée future n'est utilisée et aucun forward-fill silencieux n'est
appliqué : les valeurs manquantes restent manquantes et conservent
l'alignement temporel.
"""

from __future__ import annotations

import pandas as pd

# Fréquence mensuelle « fin de mois » (Month-End) de pandas >= 2.2.
_MONTH_END = "ME"


def _require_datetime_index(data: pd.Series | pd.DataFrame) -> None:
    """Vérifie que ``data`` est non vide et indexé par des dates."""
    if data.empty:
        raise ValueError("Les données de prix ne doivent pas être vides.")
    if not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("L'index doit être un DatetimeIndex.")


def _sort_and_dedupe(data: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Trie par date et supprime les dates dupliquées en gardant la dernière.

    Garder la dernière occurrence est cohérent avec ``validate_prices`` du
    data loader : une correction fournisseur postérieure remplace la valeur
    initiale pour une même date.
    """
    data = data.sort_index()
    return data[~data.index.duplicated(keep="last")]


def to_monthly_prices(
    prices: pd.Series | pd.DataFrame,
) -> pd.Series | pd.DataFrame:
    """Convertit des prix en prix mensuels (dernier prix disponible du mois).

    On utilise le **dernier prix réellement disponible** de chaque mois, pas
    une moyenne mensuelle. ``resample("ME").last()`` ignore les ``NaN`` à
    l'intérieur du mois (dernière observation valide), mais ne comble jamais un
    mois entièrement vide : celui-ci reste ``NaN`` (pas de forward-fill).

    Parameters
    ----------
    prices:
        Série ou tableau de prix indexé par un ``DatetimeIndex``.

    Returns
    -------
    pd.Series | pd.DataFrame
        Prix ramenés en fin de mois. Les noms de colonnes / le nom de la
        Series sont préservés.

    Raises
    ------
    ValueError
        Si ``prices`` est vide ou si l'index n'est pas un ``DatetimeIndex``.
    """
    _require_datetime_index(prices)
    prices = _sort_and_dedupe(prices)

    # .last() prend la dernière valeur non nulle de chaque mois (dernier prix
    # réellement coté), sans propager d'un mois à l'autre.
    monthly = prices.resample(_MONTH_END).last()
    return monthly


def compute_momentum(
    monthly_prices: pd.Series | pd.DataFrame,
    lookback_months: int = 12,
    skip_months: int = 1,
) -> pd.Series | pd.DataFrame:
    """Momentum ``prix(t - skip) / prix(t - lookback) - 1``.

    Pour le momentum « 12-1 » (``lookback_months=12``, ``skip_months=1``) :
    ``prix(t-1) / prix(t-12) - 1``. On saute le dernier mois (``skip``) pour
    atténuer l'effet de retournement court terme.

    On n'utilise **pas** l'approximation ``pct_change(lookback) -
    pct_change(skip)``, qui ne correspond pas à cette définition. Les premières
    lignes ``NaN`` (historique insuffisant) sont conservées pour préserver
    l'alignement temporel.

    Parameters
    ----------
    monthly_prices:
        Prix mensuels indexés par des dates.
    lookback_months:
        Horizon long du momentum, en mois. Doit être strictement positif.
    skip_months:
        Nombre de mois récents ignorés. ``0 <= skip_months < lookback_months``.

    Returns
    -------
    pd.Series | pd.DataFrame
        Momentum, aligné sur l'index d'entrée.

    Raises
    ------
    ValueError
        Si les paramètres sont invalides, si l'entrée est vide / non temporelle,
        ou si des prix non strictement positifs sont présents.
    """
    _require_datetime_index(monthly_prices)

    if lookback_months <= 0:
        raise ValueError("lookback_months doit être strictement positif.")
    if skip_months < 0:
        raise ValueError("skip_months doit être positif ou nul.")
    if skip_months >= lookback_months:
        raise ValueError("skip_months doit être strictement inférieur à lookback_months.")

    if isinstance(monthly_prices, pd.DataFrame):
        non_numeric = [
            col
            for col in monthly_prices.columns
            if not pd.api.types.is_numeric_dtype(monthly_prices[col])
        ]
        if non_numeric:
            raise ValueError(f"Colonnes de prix non numériques : {non_numeric}")
    elif not pd.api.types.is_numeric_dtype(monthly_prices):
        raise ValueError("Les prix doivent être numériques.")

    # Un prix nul ou négatif rendrait le momentum ininterprétable.
    valid_values = monthly_prices.to_numpy()
    finite_mask = pd.notna(valid_values)
    if (valid_values[finite_mask] <= 0).any():
        raise ValueError("Les prix doivent être strictement positifs.")

    past_skip = monthly_prices.shift(skip_months)
    past_lookback = monthly_prices.shift(lookback_months)
    return past_skip / past_lookback - 1.0


def compute_moving_average(
    monthly_prices: pd.Series | pd.DataFrame,
    window: int = 10,
) -> pd.Series | pd.DataFrame:
    """Moyenne mobile simple sur ``window`` mois.

    ``min_periods=window`` : tant que la fenêtre n'est pas complète, la valeur
    reste ``NaN`` (aucune donnée future, aucune interpolation).

    Parameters
    ----------
    monthly_prices:
        Prix mensuels indexés par des dates.
    window:
        Taille de la fenêtre, en mois. Doit être strictement positif.

    Returns
    -------
    pd.Series | pd.DataFrame
        Moyenne mobile, alignée sur l'index d'entrée.

    Raises
    ------
    ValueError
        Si ``window <= 0`` ou si l'entrée est vide / non temporelle.
    """
    _require_datetime_index(monthly_prices)
    if window <= 0:
        raise ValueError("window doit être strictement positif.")

    return monthly_prices.rolling(window=window, min_periods=window).mean()


def compute_trend_filter(
    monthly_prices: pd.Series | pd.DataFrame,
    moving_average: pd.Series | pd.DataFrame,
) -> pd.Series | pd.DataFrame:
    """Filtre de tendance : ``True`` si ``prix > moyenne mobile``, sinon ``False``.

    Les périodes où la moyenne mobile n'est pas disponible (``NaN``) donnent
    ``False`` (comparaison avec ``NaN``) : l'actif est alors **non éligible**.
    On vérifie explicitement l'alignement des index (et des colonnes pour les
    DataFrames) afin d'éviter tout alignement implicite dangereux.

    Parameters
    ----------
    monthly_prices:
        Prix mensuels.
    moving_average:
        Moyenne mobile, de même forme et même index que ``monthly_prices``.

    Returns
    -------
    pd.Series | pd.DataFrame
        Masque booléen d'éligibilité de tendance.

    Raises
    ------
    ValueError
        Si les types, index ou colonnes ne correspondent pas.
    """
    if type(monthly_prices) is not type(moving_average):
        raise ValueError("prix et moyenne mobile doivent être du même type (Series ou DataFrame).")

    if not monthly_prices.index.equals(moving_average.index):
        raise ValueError("Les index des prix et de la moyenne mobile diffèrent.")

    if isinstance(monthly_prices, pd.DataFrame):
        if not monthly_prices.columns.equals(moving_average.columns):
            raise ValueError("Les colonnes des prix et de la moyenne mobile diffèrent.")

    # NaN dans la moyenne mobile -> comparaison False -> non éligible.
    return monthly_prices > moving_average


def rolling_annualized_volatility(
    returns: pd.Series | pd.DataFrame,
    window: int = 3,
    periods_per_year: int = 12,
) -> pd.Series | pd.DataFrame:
    """Volatilité réalisée glissante et annualisée (écart-type d'échantillon).

    Utilise uniquement les rendements passés et présents (fenêtre glissante se
    terminant à la date courante) : aucune donnée future. ``min_periods=window``
    laisse les premières périodes en ``NaN`` tant que la fenêtre n'est pas
    complète. Aucune valeur manquante n'est comblée.

    Annualisation : ``std(rendements) * sqrt(periods_per_year)``. Pour des
    données mensuelles, ``periods_per_year=12`` (choix principal du Projet 3) ;
    la fenêtre par défaut de 3 mois est réactive, des fenêtres de 6 ou 12 mois
    sont plus lisses.

    Parameters
    ----------
    returns:
        Rendements (Series ou DataFrame) indexés par des dates.
    window:
        Taille de la fenêtre glissante, en périodes. Doit être ``> 1`` (l'écart
        -type d'échantillon exige au moins deux points).
    periods_per_year:
        Nombre de périodes par an pour l'annualisation. Doit être ``> 0``.

    Returns
    -------
    pd.Series | pd.DataFrame
        Volatilité annualisée, alignée sur l'index d'entrée (index, colonnes et
        noms préservés).

    Raises
    ------
    ValueError
        Si l'entrée est vide / non temporelle / non numérique, ou si
        ``window <= 1`` ou ``periods_per_year <= 0``.
    """
    _require_datetime_index(returns)

    if window <= 1:
        raise ValueError("window doit être strictement supérieur à 1.")
    if periods_per_year <= 0:
        raise ValueError("periods_per_year doit être strictement positif.")

    if isinstance(returns, pd.DataFrame):
        non_numeric = [
            col for col in returns.columns if not pd.api.types.is_numeric_dtype(returns[col])
        ]
        if non_numeric:
            raise ValueError(f"Colonnes de rendements non numériques : {non_numeric}")
    elif not pd.api.types.is_numeric_dtype(returns):
        raise ValueError("Les rendements doivent être numériques.")

    rolling_std = returns.rolling(window=window, min_periods=window).std()
    return rolling_std * (periods_per_year ** 0.5)

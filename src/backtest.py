import numpy as np
import pandas as pd

from src.metrics import build_equity_curve, compute_returns  # noqa: F401 (ré-export public)

CASH_COLUMN = "CASH"

# Tolérance numérique sur la somme des poids (doit valoir exactement 1).
WEIGHT_TOLERANCE = 1e-10


def buy_and_hold(prices: pd.Series, initial_capital: float = 10_000) -> pd.DataFrame:
    """
    Simulate a buy-and-hold strategy from a price series.

    Parameters:
    prices (pd.Series): Asset prices.
    initial_capital (float): The initial investment amount.

    Returns:
    pd.DataFrame: Prices, returns, and equity curve.
    """
    clean_prices = prices.dropna()
    if clean_prices.empty:
        return pd.DataFrame(columns=["Prices", "Returns", "Equity Curve"])

    first_price = clean_prices.iloc[0]
    if first_price <= 0:
        raise ValueError("first valid price must be positive")

    shares = initial_capital / first_price
    returns = compute_returns(clean_prices)
    equity_curve = clean_prices * shares

    return pd.DataFrame(
        {
            "Prices": clean_prices,
            "Returns": returns.reindex(clean_prices.index),
            "Equity Curve": equity_curve,
        }
    )


def backtest_monthly_allocation(
    monthly_prices: pd.DataFrame,
    executed_weights: pd.DataFrame,
    initial_capital: float = 10_000.0,
    transaction_cost: float = 0.001,
    cash_return: float | pd.Series = 0.0,
    cash_col: str = CASH_COLUMN,
) -> pd.DataFrame:
    """Backteste une allocation mensuelle à poids déjà décalés (sans look-ahead).

    Le poids tenu pendant le mois ``t`` (``executed_weights`` en ``t``) a été
    décidé avec l'information disponible en ``t-1`` (poids déjà décalés en amont
    via ``lag_weights_for_execution``). Le rendement du mois ``t`` vaut
    ``prix(t) / prix(t-1) - 1`` : le poids de ``t`` n'utilise donc jamais le prix
    de ``t``.

    Convention de turnover et de frais
    ----------------------------------
    ``turnover(t) = 0.5 * somme_j |w_j(t) - poids_dérivés_j(t)|`` sur **toutes** les
    colonnes (actifs et cash). Cette convention représente la fraction du
    portefeuille effectivement remplacée :

    - ``100 % cash -> 100 % ETF`` donne un turnover de 100 % ;
    - ``100 % ETF A -> 100 % ETF B`` donne un turnover de 100 % (remplacement
      complet, pas un double comptage).

    Le coût vaut ``transaction_cost * somme |delta des actifs hors CASH|``.
    A -> B paie deux côtés ; cash -> A un seul. Le capital net de frais porte
    ensuite le rendement du mois. Modèle fractionnaire exploratoire ; le
    simulateur de compte calcule les frais exacts des parts entières.

    Parameters
    ----------
    monthly_prices:
        Prix mensuels des actifs (colonnes = tickers, sans colonne cash).
    executed_weights:
        Poids exécutés (déjà décalés), colonnes = actifs + ``cash_col``.
    initial_capital:
        Capital initial.
    transaction_cost:
        Coût proportionnel par côté traité (ex. ``0.001`` = 0,10 %).
    cash_return:
        Rendement mensuel du cash (0 par défaut). Scalaire, ou ``Series``
        indexée par date (ex. rendement mensuel d'un ETF monétaire) : les dates
        absentes ou ``NaN`` valent 0.
    cash_col:
        Nom de la colonne de cash.

    Returns
    -------
    pd.DataFrame
        Colonnes : ``Gross Return``, ``Turnover``, ``Transaction Cost``,
        ``Net Return``, ``Equity Curve``, ``Invested Exposure``,
        ``Cash Weight``, ``Selected Assets``.

    Raises
    ------
    ValueError
        Si les entrées sont incohérentes (colonne cash absente, poids négatifs,
        somme de poids > 1, indices non alignés, exposition sur un actif au
        rendement indisponible).
    """
    if cash_col not in executed_weights.columns:
        raise ValueError(f"La colonne cash '{cash_col}' est absente des poids exécutés.")
    if not monthly_prices.index.equals(executed_weights.index):
        raise ValueError("monthly_prices et executed_weights doivent partager le même index.")

    asset_cols = [c for c in executed_weights.columns if c != cash_col]
    missing = [c for c in asset_cols if c not in monthly_prices.columns]
    if missing:
        raise ValueError(f"Colonnes de prix manquantes pour : {missing}")

    # Les NaN doivent être rejetés AVANT toute somme (sum ignore les NaN et
    # masquerait une allocation invalide). On ne comble pas un NaN par 0/cash.
    missing_cells = executed_weights.isna()
    if missing_cells.to_numpy().any():
        locations = [
            f"(date={date!r}, column={column!r})"
            for date, column in missing_cells.stack()[missing_cells.stack()].index
        ]
        raise ValueError(
            "Portfolio weights must not contain NaN values. "
            f"NaN cell(s): {', '.join(locations)}."
        )

    if (executed_weights.to_numpy() < -1e-9).any():
        raise ValueError("Les poids ne doivent jamais être négatifs (pas de levier / vente à découvert).")

    # Chaque ligne de poids doit totaliser exactement 1 : toute part non investie
    # doit être affectée explicitement au cash (pas de complétion automatique).
    weight_sums = executed_weights.sum(axis=1)
    if not np.isclose(weight_sums, 1.0, rtol=0.0, atol=WEIGHT_TOLERANCE).all():
        raise ValueError(
            "Portfolio weights must sum to 1.0 for every date. "
            "Any uninvested allocation must be assigned explicitly to CASH."
        )

    # Rendements mensuels des actifs : prix(t) / prix(t-1) - 1.
    asset_returns = monthly_prices[asset_cols].pct_change(fill_method=None)

    asset_weights = executed_weights[asset_cols]

    # Sécurité anti-look-ahead : on refuse d'être exposé à un actif dont le
    # rendement du mois est indisponible (NaN), sauf poids nul.
    exposed_to_nan = (asset_weights.abs() > 0) & asset_returns.isna()
    if exposed_to_nan.to_numpy().any():
        raise ValueError("Exposition à un actif dont le rendement mensuel est indisponible (NaN).")

    # Un actif à poids nul ne contribue pas, même si son rendement est NaN.
    contrib = asset_weights.mul(asset_returns.fillna(0.0))
    if isinstance(cash_return, pd.Series):
        cash_return = cash_return.reindex(executed_weights.index).fillna(0.0)
    gross_return = contrib.sum(axis=1) + executed_weights[cash_col] * cash_return

    # Comparer aux positions ayant dérivé depuis le précédent rééquilibrage.
    prev_weights = executed_weights.shift(1)
    prev_weights.iloc[0] = 0.0
    if cash_col in prev_weights.columns:
        prev_weights.iloc[0, prev_weights.columns.get_loc(cash_col)] = 1.0
    previous_growth = asset_returns.fillna(0.0).shift(1).fillna(0.0) + 1.0
    prev_weights[asset_cols] = prev_weights[asset_cols] * previous_growth
    cash_growth = cash_return.shift(1).fillna(0.0) + 1.0 if isinstance(cash_return, pd.Series) else 1.0 + cash_return
    prev_weights[cash_col] *= cash_growth
    prev_weights.iloc[0] = 0.0
    prev_weights.iloc[0, prev_weights.columns.get_loc(cash_col)] = 1.0
    nav = prev_weights.sum(axis=1)
    if (nav <= 0).any():
        raise ValueError("Valeur du portefeuille nulle ou négative avant rééquilibrage.")
    prev_weights = prev_weights.div(nav, axis=0)
    delta = executed_weights - prev_weights
    turnover = 0.5 * delta.abs().sum(axis=1)
    # Commission par côté : A -> B exige une vente ET un achat. CASH n'est pas un ordre.
    traded_notional = delta[asset_cols].abs().sum(axis=1)
    cost = transaction_cost * traded_notional
    if not np.isfinite(transaction_cost) or transaction_cost < 0 or (cost >= 1).any():
        raise ValueError("Frais de transaction invalides.")
    net_return = (1.0 - cost) * (1.0 + gross_return) - 1.0

    equity_curve = (1.0 + net_return).cumprod() * initial_capital

    cash_weight = executed_weights[cash_col]
    # Exposition investie = somme des poids hors cash (les poids somment à 1).
    invested_exposure = asset_weights.sum(axis=1)

    # Actifs détenus par mois (liste en compréhension : bien plus rapide qu'un apply ligne à ligne).
    held_mask = asset_weights.to_numpy() > 0
    names = np.array(asset_cols, dtype=object)
    selected_assets = pd.Series(
        [", ".join(names[row]) if row.any() else cash_col for row in held_mask],
        index=executed_weights.index,
    )

    return pd.DataFrame(
        {
            "Gross Return": gross_return,
            "Turnover": turnover,
            "Traded Notional": traded_notional,
            "Transaction Cost": cost,
            "Net Return": net_return,
            "Equity Curve": equity_curve,
            "Invested Exposure": invested_exposure,
            "Cash Weight": cash_weight,
            "Selected Assets": selected_assets,
        }
    )

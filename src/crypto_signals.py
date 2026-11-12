"""Poche crypto risk-on / risk-off BTC/ETH — Projet 6 (recherche uniquement).

Module expérimental, **non branché** sur le rapport mensuel : il sert au
notebook ``10_crypto_risk_on_off.ipynb`` et au rapport ``reports/crypto_report.md``.
Aucun levier, aucun dérivé, aucun ordre.

Règles (guide, non optimisées)
------------------------------
- Signal risk-on : prix BTC > moyenne mobile 200 jours **et** momentum 90 jours > 0.
- Allocation risk-on : 70 % BTC / 30 % ETH ; risk-off : 100 % cash.
- Volatility targeting optionnel : exposition = min(1, cible / volatilité réalisée
  30 jours du panier), jamais de levier.
- Rebalancement périodique (mensuel par défaut). Le signal observé en fin de
  période ``t`` est exécuté sur la période ``t+1`` (décalage anti look-ahead).
- Les crypto-actifs cotent 7 j / 7 : volatilité annualisée avec ``√365``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.backtest import CASH_COLUMN, backtest_monthly_allocation
from src.signals import lag_weights_for_execution
from src.taxes import TaxConfig, crypto_net_value

BTC, ETH = "BTC-EUR", "ETH-EUR"
DEFAULT_ALLOCATION = {BTC: 0.7, ETH: 0.3}
CRYPTO_DAYS_PER_YEAR = 365
PERIODS_PER_YEAR = {"ME": 12, "W-FRI": 52}
STRATEGY_LABELS = {
    "bh_btc": "Buy & Hold BTC",
    "bh_basket": "Buy & Hold 70/30 BTC/ETH",
    "roro_btc": "Risk-on/off BTC",
    "roro_basket": "Risk-on/off 70/30",
    "roro_basket_vt": "Risk-on/off 70/30 + VT",
}


def trend_signal(prices: pd.Series, ma_window: int = 200, momentum_window: int = 90) -> pd.Series:
    """Risk-on quotidien : prix > MA(``ma_window``) et rendement ``momentum_window`` jours > 0.

    Utilise uniquement les prix jusqu'au jour ``t`` inclus. Les jours sans
    historique suffisant sont risk-off (``False``).
    """
    prices = prices.dropna().astype(float)
    if prices.empty or (prices <= 0).any():
        raise ValueError("Les prix doivent être non vides et strictement positifs.")
    moving_average = prices.rolling(ma_window, min_periods=ma_window).mean()
    momentum = prices / prices.shift(momentum_window) - 1.0
    return ((prices > moving_average) & (momentum > 0)).fillna(False).astype(bool)


def _basket_volatility(daily_prices: pd.DataFrame, allocation: dict[str, float], window: int) -> pd.Series:
    """Volatilité annualisée d'un panier rebalancé quotidiennement (approximation)."""
    returns = daily_prices[list(allocation)].pct_change(fill_method=None)
    basket = sum(returns[ticker] * weight for ticker, weight in allocation.items()) / sum(allocation.values())
    return basket.rolling(window, min_periods=window).std() * np.sqrt(CRYPTO_DAYS_PER_YEAR)


def build_crypto_weights(
    daily_prices: pd.DataFrame,
    allocation: dict[str, float] | None = None,
    *,
    use_signal: bool = True,
    signal_ticker: str = BTC,
    target_volatility: float | None = None,
    vol_window: int = 30,
    freq: str = "ME",
) -> dict[str, pd.DataFrame]:
    """Poids cibles et exécutés d'une stratégie crypto à rebalancement périodique.

    Returns
    -------
    dict
        ``period_prices`` (prix de fin de période des actifs de l'allocation),
        ``target_weights`` (décidés en fin de période) et ``executed_weights``
        (appliqués sur la période suivante), colonnes = actifs + ``CASH``.
    """
    allocation = dict(allocation or DEFAULT_ALLOCATION)
    if any(w < 0 for w in allocation.values()) or not np.isclose(sum(allocation.values()), 1.0):
        raise ValueError("L'allocation doit être positive et sommer à 1.")
    missing = [t for t in [*allocation, signal_ticker] if t not in daily_prices.columns]
    if missing:
        raise ValueError(f"Prix manquants pour : {missing}")
    if target_volatility is not None and target_volatility <= 0:
        raise ValueError("La volatilité cible doit être strictement positive.")

    daily = daily_prices.sort_index()
    period_prices = daily[list(allocation)].resample(freq).last()
    # Période en cours incomplète (fin de période postérieure à la dernière
    # observation) : exclue, comme le mois partiel du rapport mensuel.
    last_observation = daily.dropna(how="all").index.max().normalize()
    period_prices = period_prices.loc[period_prices.index <= last_observation]
    # Un actif n'est investissable qu'à partir de son premier prix de fin de période.
    available = period_prices.notna()

    exposure = pd.Series(1.0, index=period_prices.index)
    if use_signal:
        signal = trend_signal(daily[signal_ticker]).resample(freq).last()
        exposure = exposure.where(signal.reindex(period_prices.index).fillna(False).astype(bool), 0.0)
    if target_volatility is not None:
        vol = _basket_volatility(daily, allocation, vol_window).resample(freq).last().reindex(period_prices.index)
        exposure = exposure * (target_volatility / vol).clip(upper=1.0).fillna(0.0)

    target = pd.DataFrame(0.0, index=period_prices.index, columns=[*allocation, CASH_COLUMN])
    for ticker, weight in allocation.items():
        target[ticker] = (weight * exposure).where(available[ticker], 0.0)
    # Un actif pas encore coté : sa part reste en cash (pas de redistribution).
    target[CASH_COLUMN] = 1.0 - target[list(allocation)].sum(axis=1)
    executed = lag_weights_for_execution(target, periods=1)
    # Pas d'exposition sur la première période de cotation (rendement non défini).
    first_return_missing = period_prices.pct_change(fill_method=None).isna()
    for ticker in allocation:
        blocked = first_return_missing[ticker] & (executed[ticker] > 0)
        executed.loc[blocked, CASH_COLUMN] += executed.loc[blocked, ticker]
        executed.loc[blocked, ticker] = 0.0
    return {"period_prices": period_prices, "target_weights": target, "executed_weights": executed}


def _metrics(returns: pd.Series, periods_per_year: int) -> dict:
    returns = returns.dropna()
    growth = (1.0 + returns).cumprod()
    years = len(returns) / periods_per_year
    volatility = float(returns.std() * np.sqrt(periods_per_year))
    return {
        "cagr": float(growth.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else None,
        "volatility": volatility,
        "sharpe": float(returns.mean() / returns.std() * np.sqrt(periods_per_year)) if returns.std() > 0 else None,
        "max_drawdown": float((growth / growth.cummax() - 1.0).min()),
        "n_periods": int(len(returns)),
    }


def run_crypto_study(
    daily_prices: pd.DataFrame,
    *,
    transaction_cost: float = 0.0025,
    target_volatility: float = 0.40,
    freq: str = "ME",
    start: str | pd.Timestamp | None = None,
) -> dict:
    """Compare les cinq stratégies du guide sur les mêmes périodes, frais inclus.

    La fenêtre commence quand BTC **et** ETH sont investissables et que le
    signal MA200 est calculable (ou à ``start`` si plus tardif).
    """
    if freq not in PERIODS_PER_YEAR:
        raise ValueError(f"Fréquence non supportée : {freq} ({', '.join(PERIODS_PER_YEAR)}).")
    configs: dict[str, dict[str, Any]] = {
        "bh_btc": dict(allocation={BTC: 1.0}, use_signal=False),
        "bh_basket": dict(allocation=DEFAULT_ALLOCATION, use_signal=False),
        "roro_btc": dict(allocation={BTC: 1.0}, use_signal=True),
        "roro_basket": dict(allocation=DEFAULT_ALLOCATION, use_signal=True),
        "roro_basket_vt": dict(allocation=DEFAULT_ALLOCATION, use_signal=True, target_volatility=target_volatility),
    }
    backtests, period_index = {}, None
    for name, kwargs in configs.items():
        bundle = build_crypto_weights(daily_prices, freq=freq, **kwargs)
        period_index = bundle["period_prices"].index
        backtests[name] = backtest_monthly_allocation(
            bundle["period_prices"], bundle["executed_weights"], transaction_cost=transaction_cost
        )
    # Première période où ETH est détenable (prix de fin de période précédente
    # connu) et où le signal MA200 de BTC a pu être observé en fin de période.
    eth_first_price = daily_prices[ETH].resample(freq).last().reindex(period_index).first_valid_index()
    if period_index is None:
        raise ValueError("Aucune stratégie crypto construite.")
    btc = daily_prices[BTC].dropna()
    signal_ready = btc.index[min(199, len(btc) - 1)]
    first_decision = max(eth_first_price, period_index[period_index >= signal_ready][0])
    later = period_index[period_index > first_decision]
    if later.empty:
        raise ValueError("Historique insuffisant pour la comparaison crypto.")
    window_start = later[0]
    if start is not None:
        window_start = max(window_start, pd.Timestamp(start))
    periods_per_year = PERIODS_PER_YEAR[freq]
    returns = {name: bt["Net Return"].loc[window_start:] for name, bt in backtests.items()}
    first_index = returns["bh_btc"].index
    return {
        "start": first_index.min().date().isoformat(),
        "end": first_index.max().date().isoformat(),
        "freq": freq,
        "transaction_cost": transaction_cost,
        "target_volatility": target_volatility,
        "returns": returns,
        "exposure": {name: bt["Invested Exposure"].loc[window_start:] for name, bt in backtests.items()},
        "metrics": {
            name: {**_metrics(r, periods_per_year),
                   "avg_exposure": float(backtests[name]["Invested Exposure"].loc[window_start:].mean())}
            for name, r in returns.items()
        },
    }


def simulate_sleeve(core_returns: pd.Series, crypto_returns: pd.Series, crypto_share: float) -> pd.Series:
    """Rendements d'un portefeuille « cœur + poche crypto » rebalancé chaque période.

    ``crypto_share`` dans ``[0, 1]`` (ex. 0,05). Seules les dates communes sont
    conservées. Les frais du rebalancement entre les deux poches sont ignorés
    (approximation documentée).
    """
    if not 0.0 <= crypto_share <= 1.0:
        raise ValueError("crypto_share doit être compris entre 0 et 1.")
    aligned = pd.concat([core_returns, crypto_returns], axis=1, join="inner").dropna()
    aligned.columns = ["core", "crypto"]
    return (1.0 - crypto_share) * aligned["core"] + crypto_share * aligned["crypto"]


def sleeve_comparison(core_returns: pd.Series, crypto_returns: dict[str, pd.Series],
                      shares: tuple[float, ...] = (0.05, 0.10), periods_per_year: int = 12) -> pd.DataFrame:
    """Tableau : cœur seul vs cœur + poche crypto pour chaque stratégie et part."""
    rows = []
    common = core_returns.dropna().index
    for series in crypto_returns.values():
        common = common.intersection(series.dropna().index)
    rows.append({"portefeuille": "100 % cœur", **_metrics(core_returns.loc[common], periods_per_year)})
    for name, series in crypto_returns.items():
        for share in shares:
            mixed = simulate_sleeve(core_returns.loc[common], series.loc[common], share)
            label = f"{1 - share:.0%} cœur + {share:.0%} {STRATEGY_LABELS.get(name, name)}"
            rows.append({"portefeuille": label, **_metrics(mixed, periods_per_year)})
    return pd.DataFrame(rows).set_index("portefeuille")


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def generate_crypto_report(study: dict, sleeves: pd.DataFrame, output_path: str | Path,
                           core_label: str = "CW8.PA", taxes: TaxConfig | None = None) -> Path:
    """Rapport Markdown de la recherche crypto (rendement cumulé net de flat tax inclus)."""
    taxes = taxes or TaxConfig()
    lines = [
        "# Poche crypto risk-on / risk-off BTC/ETH — Projet 6 (recherche)", "",
        f"Date de génération : {date.today().isoformat()}", "",
        "Recherche uniquement : **non branchée** sur le rapport mensuel, aucun levier, aucun ordre.", "",
        "## Hypothèses", "",
        f"- Données : BTC-EUR et ETH-EUR (Yahoo Finance, en euros), période {study['start']} → {study['end']}.",
        "- Risk-on si BTC > MA 200 jours et momentum 90 jours > 0 ; sinon 100 % cash (non rémunéré).",
        f"- Rebalancement {'mensuel' if study['freq'] == 'ME' else 'hebdomadaire'}, signal exécuté la période suivante.",
        f"- Frais : {study['transaction_cost']:.2%} par unité de turnover (plateforme crypto).",
        f"- Volatility targeting : cible {study['target_volatility']:.0%} annualisée, volatilité 30 jours, sans levier.",
        f"- Fiscalité : flat tax {taxes.flat_tax_pct:.0f} % sur la plus-value, payée une fois à la sortie "
        "(rendement cumulé net).", "",
        "## Stratégies crypto", "",
        "| Stratégie | CAGR | Volatilité | Sharpe | Max drawdown | Exposition moy. | Cumulé brut | Cumulé net d'impôt |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, m in study["metrics"].items():
        sharpe = "n/a" if m["sharpe"] is None else f"{m['sharpe']:.2f}"
        gross = float((1.0 + study["returns"][name].dropna()).prod())
        net = crypto_net_value(gross, 1.0, taxes)
        lines.append(f"| {STRATEGY_LABELS.get(name, name)} | {_pct(m['cagr'])} | {_pct(m['volatility'])} | "
                     f"{sharpe} | {_pct(m['max_drawdown'])} | {m['avg_exposure']:.0%} | {_pct(gross - 1.0)} | "
                     f"{_pct(net - 1.0)} |")
    lines += ["", f"## Effet patrimonial (cœur = Buy & Hold {core_label}, rebalancement mensuel)", "",
              "| Portefeuille | CAGR | Volatilité | Sharpe | Max drawdown |", "| --- | ---: | ---: | ---: | ---: |"]
    for label, m in sleeves.iterrows():
        sharpe = "n/a" if m["sharpe"] is None or pd.isna(m["sharpe"]) else f"{m['sharpe']:.2f}"
        lines.append(f"| {label} | {_pct(m['cagr'])} | {_pct(m['volatility'])} | {sharpe} | {_pct(m['max_drawdown'])} |")
    lines += [
        "", "## Lecture", "",
        "- Le filtre risk-on/off vise d'abord à **réduire le drawdown** de la poche (les krachs crypto dépassent −70 %) ;",
        "  son intérêt se juge au drawdown et au Sharpe, pas au rendement final.",
        "- Une poche de 5 à 10 % modifie peu le portefeuille global en temps normal mais pèse fortement lors des chocs.",
        "- Taille maximale suggérée par le guide : 1 à 3 % du patrimoine au début, 5 % au plus, après paper trading.", "",
        "## Limites", "",
        "- Historique court (ETH-EUR depuis fin 2017) et dominé par quelques cycles haussiers extrêmes.",
        "- Frais, spreads, fiscalité (flat tax sur les plus-values crypto) et risque de plateforme non modélisés finement.",
        "- Rebalancement entre cœur et poche crypto sans frais ; poche crypto hors PEA.",
        "- Les performances passées ne préjugent pas des performances futures. Aucun ordre n'est exécuté.", "",
    ]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path

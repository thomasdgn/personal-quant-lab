import numpy as np
import pandas as pd
import pytest

from src.features import rolling_annualized_volatility
from src.portfolio import (
    apply_volatility_target,
    build_vol_targeted_weights,
    compute_target_exposure,
)
from src.signals import build_momentum_weights, CASH_COLUMN
from src.backtest import backtest_monthly_allocation


def _months(n):
    return pd.date_range("2020-01-31", periods=n, freq="ME")


# --------------------------------------------------------------------------- #
# rolling_annualized_volatility
# --------------------------------------------------------------------------- #
def test_vol_constant_series_is_zero_after_window():
    r = pd.Series([0.01] * 6, index=_months(6))
    vol = rolling_annualized_volatility(r, window=3, periods_per_year=12)
    assert vol.iloc[:2].isna().all()          # min_periods=window
    assert vol.iloc[2:].abs().max() == pytest.approx(0.0)


def test_vol_known_values_matches_manual():
    r = pd.Series([0.0, 0.1, 0.0, 0.1], index=_months(4))
    vol = rolling_annualized_volatility(r, window=2, periods_per_year=12)
    # std d'échantillon (ddof=1) de [0.0, 0.1] = 0.070710..., * sqrt(12)
    expected = np.std([0.0, 0.1], ddof=1) * np.sqrt(12)
    assert vol.iloc[1] == pytest.approx(expected)


def test_vol_annualisation_scales_with_sqrt_periods():
    r = pd.Series([0.0, 0.1, -0.1, 0.05, -0.05], index=_months(5))
    v12 = rolling_annualized_volatility(r, window=3, periods_per_year=12)
    v1 = rolling_annualized_volatility(r, window=3, periods_per_year=1)
    ratio = (v12 / v1).dropna()
    assert np.allclose(ratio, np.sqrt(12))


def test_vol_leading_nan():
    r = pd.Series([0.01, 0.02, 0.03, 0.04], index=_months(4))
    vol = rolling_annualized_volatility(r, window=3)
    assert vol.iloc[:2].isna().all()
    assert not np.isnan(vol.iloc[2])


@pytest.mark.parametrize("window,ppy", [(1, 12), (0, 12), (3, 0), (3, -1)])
def test_vol_invalid_params(window, ppy):
    r = pd.Series([0.01, 0.02, 0.03], index=_months(3))
    with pytest.raises(ValueError):
        rolling_annualized_volatility(r, window=window, periods_per_year=ppy)


def test_vol_rejects_non_datetime_index():
    with pytest.raises(ValueError):
        rolling_annualized_volatility(pd.Series([0.1, 0.2, 0.3]), window=2)


def test_vol_rejects_empty():
    with pytest.raises(ValueError):
        rolling_annualized_volatility(pd.Series([], dtype=float, index=pd.DatetimeIndex([])), window=2)


def test_vol_dataframe():
    df = pd.DataFrame({"A": [0.0, 0.1, 0.0], "B": [0.0, 0.2, 0.0]}, index=_months(3))
    vol = rolling_annualized_volatility(df, window=2, periods_per_year=12)
    assert list(vol.columns) == ["A", "B"]
    assert vol["B"].iloc[1] > vol["A"].iloc[1]


# --------------------------------------------------------------------------- #
# compute_target_exposure
# --------------------------------------------------------------------------- #
def test_exposure_equals_one_when_vol_equals_target():
    vol = pd.Series([0.10], index=_months(1))
    exp = compute_target_exposure(vol, target_volatility=0.10)
    assert exp.iloc[0] == pytest.approx(1.0)


def test_exposure_half_when_vol_double_target():
    vol = pd.Series([0.20], index=_months(1))
    exp = compute_target_exposure(vol, target_volatility=0.10)
    assert exp.iloc[0] == pytest.approx(0.5)


def test_exposure_capped_at_max_when_vol_low():
    vol = pd.Series([0.05], index=_months(1))
    exp = compute_target_exposure(vol, target_volatility=0.10, max_exposure=1.0)
    assert exp.iloc[0] == pytest.approx(1.0)  # 2.0 plafonné à 1.0


def test_exposure_zero_vol_is_capped_not_leveraged():
    vol = pd.Series([0.0], index=_months(1))
    exp = compute_target_exposure(vol, target_volatility=0.10, max_exposure=1.0)
    assert exp.iloc[0] == pytest.approx(1.0)  # jamais > max, pas de levier


def test_exposure_nan_vol_is_zero():
    vol = pd.Series([np.nan], index=_months(1))
    exp = compute_target_exposure(vol, target_volatility=0.10)
    assert exp.iloc[0] == pytest.approx(0.0)


def test_exposure_invalid_target():
    vol = pd.Series([0.1], index=_months(1))
    with pytest.raises(ValueError):
        compute_target_exposure(vol, target_volatility=0.0)


def test_exposure_max_above_one_rejected():
    vol = pd.Series([0.1], index=_months(1))
    with pytest.raises(ValueError):
        compute_target_exposure(vol, target_volatility=0.1, max_exposure=1.5)


def test_exposure_min_above_max_rejected():
    vol = pd.Series([0.1], index=_months(1))
    with pytest.raises(ValueError):
        compute_target_exposure(vol, target_volatility=0.1, min_exposure=0.8, max_exposure=0.5)


def test_exposure_never_negative_or_above_one():
    vol = pd.Series([0.05, 0.10, 0.20, 0.40, np.nan, 0.0], index=_months(6))
    exp = compute_target_exposure(vol, target_volatility=0.10)
    assert (exp >= 0).all() and (exp <= 1).all()


# --------------------------------------------------------------------------- #
# apply_volatility_target
# --------------------------------------------------------------------------- #
def test_apply_single_asset_scaled_to_cash():
    index = _months(1)
    base = pd.DataFrame({"A": [1.0], CASH_COLUMN: [0.0]}, index=index)
    exp = pd.Series([0.5], index=index)
    out = apply_volatility_target(base, exp)
    assert out.iloc[0]["A"] == pytest.approx(0.5)
    assert out.iloc[0][CASH_COLUMN] == pytest.approx(0.5)


def test_apply_top2_scaled():
    index = _months(1)
    base = pd.DataFrame({"A": [0.5], "B": [0.5], CASH_COLUMN: [0.0]}, index=index)
    exp = pd.Series([0.6], index=index)
    out = apply_volatility_target(base, exp)
    assert out.iloc[0]["A"] == pytest.approx(0.3)
    assert out.iloc[0]["B"] == pytest.approx(0.3)
    assert out.iloc[0][CASH_COLUMN] == pytest.approx(0.4)


def test_apply_full_cash_stays_full_cash():
    index = _months(1)
    base = pd.DataFrame({"A": [0.0], CASH_COLUMN: [1.0]}, index=index)
    exp = pd.Series([0.6], index=index)
    out = apply_volatility_target(base, exp)
    assert out.iloc[0][CASH_COLUMN] == pytest.approx(1.0)


def test_apply_weights_sum_to_one_and_non_negative():
    index = _months(3)
    base = pd.DataFrame(
        {"A": [1.0, 0.5, 0.0], "B": [0.0, 0.5, 0.0], CASH_COLUMN: [0.0, 0.0, 1.0]},
        index=index,
    )
    exp = pd.Series([0.3, 0.6, 0.9], index=index)
    out = apply_volatility_target(base, exp)
    assert np.allclose(out.sum(axis=1), 1.0)
    assert (out.to_numpy() >= -1e-12).all()


def test_apply_nan_exposure_is_full_cash():
    index = _months(1)
    base = pd.DataFrame({"A": [1.0], CASH_COLUMN: [0.0]}, index=index)
    exp = pd.Series([np.nan], index=index)
    out = apply_volatility_target(base, exp)
    assert out.iloc[0][CASH_COLUMN] == pytest.approx(1.0)


def test_apply_rejects_misaligned_index():
    base = pd.DataFrame({"A": [1.0], CASH_COLUMN: [0.0]}, index=_months(1))
    exp = pd.Series([0.5], index=pd.date_range("2019-01-31", periods=1, freq="ME"))
    with pytest.raises(ValueError):
        apply_volatility_target(base, exp)


def test_apply_rejects_missing_cash_column():
    index = _months(1)
    base = pd.DataFrame({"A": [1.0]}, index=index)
    exp = pd.Series([0.5], index=index)
    with pytest.raises(ValueError):
        apply_volatility_target(base, exp)


def test_apply_never_exceeds_target_exposure():
    index = _months(1)
    base = pd.DataFrame({"A": [1.0], CASH_COLUMN: [0.0]}, index=index)
    exp = pd.Series([0.4], index=index)
    out = apply_volatility_target(base, exp)
    invested = out.iloc[0]["A"]
    assert invested <= 0.4 + 1e-9


# --------------------------------------------------------------------------- #
# anti-look-ahead
# --------------------------------------------------------------------------- #
def test_volatility_spike_does_not_reduce_same_month_exposure():
    """Un pic de volatilité au mois M ne doit réduire l'exposition qu'au mois
    M+1, jamais rétroactivement au mois M lui-même."""
    index = _months(8)
    # Rendements calmes puis pic en position 5.
    base_returns = pd.Series([0.01, 0.01, 0.01, 0.01, 0.01, 0.20, 0.01, 0.01], index=index)

    vol = rolling_annualized_volatility(base_returns, window=3, periods_per_year=12)
    exposure = compute_target_exposure(vol, target_volatility=0.10)
    executed = exposure.shift(1)  # décalage anti-look-ahead

    m = 5  # mois du pic
    # L'exposition exécutée au mois du pic vient d'AVANT le pic (calme) ...
    assert executed.iloc[m] == pytest.approx(exposure.iloc[m - 1])
    # ... et l'exposition réduite par le pic ne s'applique qu'au mois suivant.
    assert executed.iloc[m + 1] == pytest.approx(exposure.iloc[m])
    # La version "trichée" (même mois) diffère de la version correcte.
    assert executed.iloc[m + 1] != pytest.approx(executed.iloc[m])


def test_build_vol_targeted_weights_no_lookahead_first_period_cash():
    index = _months(24)
    rng = np.random.default_rng(0)
    prices = pd.DataFrame(
        {
            "A": 100 * np.cumprod(1 + rng.normal(0.01, 0.03, 24)),
            "B": 100 * np.cumprod(1 + rng.normal(0.008, 0.04, 24)),
        },
        index=index,
    )
    base = build_momentum_weights(prices, lookback_months=6, skip_months=1, ma_window=3,
                                  top_n=1, already_monthly=True)
    out = build_vol_targeted_weights(prices, base["executed_weights"],
                                     target_volatility=0.10, vol_window=3)
    fw = out["final_weights"]
    assert np.allclose(fw.sum(axis=1), 1.0)
    assert (fw.to_numpy() >= -1e-9).all() and (fw.to_numpy() <= 1 + 1e-9).all()
    # Première période : exposition décalée indisponible -> 100 % cash.
    assert fw.iloc[0][CASH_COLUMN] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# backtest avec poids vol-targeted
# --------------------------------------------------------------------------- #
def _simple_setup(n=30, seed=1):
    index = _months(n)
    rng = np.random.default_rng(seed)
    prices = pd.DataFrame(
        {"A": 100 * np.cumprod(1 + rng.normal(0.01, 0.03, n)),
         "B": 100 * np.cumprod(1 + rng.normal(0.009, 0.05, n))},
        index=index,
    )
    base = build_momentum_weights(prices, 6, 1, 3, 1, already_monthly=True)
    vt = build_vol_targeted_weights(prices, base["executed_weights"], 0.10, 3)
    return prices, vt["final_weights"]


def test_backtest_vol_targeted_outputs_are_clean():
    prices, fw = _simple_setup()
    bt = backtest_monthly_allocation(prices, fw, transaction_cost=0.001)
    assert (bt["Equity Curve"] > 0).all()
    assert not bt["Equity Curve"].isna().any()
    assert not bt["Net Return"].isna().any()


def test_backtest_vol_targeted_fees_reduce_capital():
    prices, fw = _simple_setup()
    f0 = backtest_monthly_allocation(prices, fw, transaction_cost=0.0)["Equity Curve"].iloc[-1]
    f1 = backtest_monthly_allocation(prices, fw, transaction_cost=0.003)["Equity Curve"].iloc[-1]
    assert f0 >= f1


def test_backtest_vol_targeted_is_reproducible():
    prices, fw = _simple_setup(seed=2)
    a = backtest_monthly_allocation(prices, fw, transaction_cost=0.001)["Equity Curve"]
    b = backtest_monthly_allocation(prices, fw, transaction_cost=0.001)["Equity Curve"]
    assert np.allclose(a.to_numpy(), b.to_numpy())


def test_vol_targeting_reduces_portfolio_volatility_on_high_vol_asset():
    """Sur un actif très volatil constamment détenu, plafonner l'exposition via
    le vol targeting réduit la volatilité réalisée du portefeuille."""
    index = _months(40)
    rng = np.random.default_rng(7)
    # Actif à forte volatilité (bien au-dessus de la cible 10 %).
    ret = rng.normal(0.01, 0.12, 40)
    price = pd.Series(100 * np.cumprod(1 + ret), index=index).to_frame("A")

    # Base : 100 % A dès que possible (momentum trivial, MA courte).
    base = build_momentum_weights(price, lookback_months=2, skip_months=0, ma_window=2,
                                  top_n=1, use_trend_filter=False, already_monthly=True)
    base_w = base["executed_weights"]
    base_bt = backtest_monthly_allocation(price, base_w, transaction_cost=0.0)

    vt = build_vol_targeted_weights(price, base_w, target_volatility=0.10, vol_window=6)
    vt_bt = backtest_monthly_allocation(price, vt["final_weights"], transaction_cost=0.0)

    base_vol = base_bt["Net Return"].std()
    vt_vol = vt_bt["Net Return"].std()
    assert vt_vol < base_vol

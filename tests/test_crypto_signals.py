"""Projet 6 — signaux crypto risk-on / risk-off (recherche, sans ordre)."""

import numpy as np
import pandas as pd
import pytest

from src.crypto_signals import (
    BTC,
    ETH,
    build_crypto_weights,
    generate_crypto_report,
    run_crypto_study,
    simulate_sleeve,
    sleeve_comparison,
    trend_signal,
)


@pytest.fixture(scope="module")
def daily():
    index = pd.date_range("2016-01-01", "2024-12-31", freq="D")
    rng = np.random.default_rng(11)
    btc = 1000 * np.cumprod(1 + rng.normal(0.002, 0.04, len(index)))
    eth = pd.Series(100 * np.cumprod(1 + rng.normal(0.002, 0.05, len(index))), index=index)
    eth[eth.index < "2017-11-11"] = np.nan
    return pd.DataFrame({BTC: btc, ETH: eth}, index=index)


def test_trend_signal_rule_on_simple_series():
    index = pd.date_range("2020-01-01", periods=400, freq="D")
    rising = pd.Series(np.linspace(100, 500, 400), index=index)
    signal = trend_signal(rising)
    assert not signal.iloc[:199].any()  # MA200 indisponible avant 200 observations -> risk-off
    assert signal.iloc[250:].all()
    falling = pd.Series(np.linspace(500, 100, 400), index=index)
    assert not trend_signal(falling).any()


def test_trend_signal_does_not_use_future_prices():
    index = pd.date_range("2020-01-01", periods=400, freq="D")
    prices = pd.Series(np.linspace(100, 500, 400), index=index)
    changed = prices.copy()
    changed.iloc[300:] = 1.0
    pd.testing.assert_series_equal(trend_signal(prices).iloc[:300], trend_signal(changed).iloc[:300])


def test_weights_are_lagged_valid_and_without_leverage(daily):
    bundle = build_crypto_weights(daily, target_volatility=0.4)
    target, executed = bundle["target_weights"], bundle["executed_weights"]
    assert np.allclose(executed.sum(axis=1), 1.0)
    assert (executed.to_numpy() >= -1e-12).all() and (executed.drop(columns="CASH").sum(axis=1) <= 1 + 1e-12).all()
    pd.testing.assert_frame_equal(executed.iloc[2:], target.shift(1).iloc[2:], check_freq=False)
    assert (executed.loc[:"2017-11-30", ETH] == 0).all()  # ETH non coté -> pas d'exposition


def test_risk_off_goes_to_cash(daily):
    crash = daily.copy()
    crash.loc["2023-01-01":, BTC] = np.linspace(crash.loc["2022-12-31", BTC], 1.0, len(crash.loc["2023-01-01":]))
    executed = build_crypto_weights(crash)["executed_weights"]
    assert (executed.loc["2023-12-31":, "CASH"] == 1.0).all()


def test_incomplete_last_period_is_dropped(daily):
    partial = daily.loc[:"2024-12-15"]
    assert build_crypto_weights(partial)["period_prices"].index.max() == pd.Timestamp("2024-11-30")


def test_study_compares_all_strategies_on_same_periods(daily):
    study = run_crypto_study(daily)
    assert set(study["metrics"]) == {"bh_btc", "bh_basket", "roro_btc", "roro_basket", "roro_basket_vt"}
    lengths = {len(r) for r in study["returns"].values()}
    assert len(lengths) == 1
    assert pd.Timestamp(study["start"]) > pd.Timestamp("2017-11-30")
    assert study["metrics"]["roro_basket_vt"]["avg_exposure"] <= study["metrics"]["roro_basket"]["avg_exposure"]
    weekly = run_crypto_study(daily, freq="W-FRI")
    assert weekly["metrics"]["bh_btc"]["n_periods"] > study["metrics"]["bh_btc"]["n_periods"]
    with pytest.raises(ValueError):
        run_crypto_study(daily, freq="D")


def test_sleeve_math_and_report(daily, tmp_path):
    index = pd.date_range("2020-01-31", periods=3, freq="ME")
    core = pd.Series([0.01, 0.02, -0.01], index=index)
    crypto = pd.Series([0.10, -0.20, 0.05], index=index)
    assert simulate_sleeve(core, crypto, 0.1).tolist() == pytest.approx([0.019, -0.002, -0.004])
    with pytest.raises(ValueError):
        simulate_sleeve(core, crypto, 1.5)
    study = run_crypto_study(daily)
    sleeves = sleeve_comparison(study["returns"]["bh_btc"] * 0.1, {"roro_basket": study["returns"]["roro_basket"]})
    assert "100 % cœur" in sleeves.index and len(sleeves) == 3
    text = generate_crypto_report(study, sleeves, tmp_path / "crypto.md").read_text(encoding="utf-8")
    assert "Risk-on/off 70/30" in text and "non branchée" in text

"""Registre de stratégies : équivalence exacte avec les implémentations historiques."""

import numpy as np
import pandas as pd
import pytest

from src.monthly_pipeline import MonthlyPipelineConfig
from src.portfolio import build_vol_targeted_weights
from src.signals import build_momentum_weights
from src.strategies import (
    REGISTRY,
    StrategyContext,
    available_strategies,
    build_strategy,
    build_target,
    label,
)


def _monthly(n=110, seed=11):
    index = pd.date_range("2016-01-31", periods=n, freq="ME")
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({
        "CW8.PA": 100 * np.cumprod(1 + rng.normal(0.008, 0.04, n)),
        "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.007, 0.05, n)),
        "PAEEM.PA": 100 * np.cumprod(1 + rng.normal(0.004, 0.06, n)),
        "OBLI.PA": 100 * np.cumprod(1 + rng.normal(0.002, 0.01, n)),
    }, index=index)
    frame.loc[frame.index < "2018-12-31", "OBLI.PA"] = np.nan
    return frame


CONFIG = MonthlyPipelineConfig()
CTX = StrategyContext(config=CONFIG, equities=("CW8.PA", "ESE.PA", "PAEEM.PA"), bond="OBLI.PA",
                      fixed_allocation=(("CW8.PA", 0.85), ("PAEEM.PA", 0.15)))


def test_momentum_matches_legacy_executed_weights():
    monthly = _monthly()
    legacy = build_momentum_weights(monthly, lookback_months=12, skip_months=1, ma_window=10, top_n=1,
                                    already_monthly=True)["executed_weights"]
    pd.testing.assert_frame_equal(build_strategy("momentum", monthly, CTX)["executed_weights"], legacy)


def test_momentum_vt_matches_legacy_final_weights():
    monthly = _monthly()
    base = build_momentum_weights(monthly, already_monthly=True)["executed_weights"]
    legacy = build_vol_targeted_weights(monthly, base, target_volatility=0.10, vol_window=3)["final_weights"]
    new = build_strategy("momentum_vt", monthly, CTX)["executed_weights"]
    pd.testing.assert_frame_equal(new, legacy, check_exact=False, atol=1e-12)


@pytest.mark.parametrize("name", list(REGISTRY))
def test_every_strategy_produces_valid_lagged_weights(name):
    monthly = _monthly()
    bundle = build_strategy(name, monthly, CTX)
    target, executed = bundle["target_weights"], bundle["executed_weights"]
    assert np.allclose(target.sum(axis=1), 1.0) and np.allclose(executed.sum(axis=1), 1.0)
    assert (executed.to_numpy() >= -1e-12).all() and (executed.to_numpy() <= 1 + 1e-12).all()
    pd.testing.assert_frame_equal(executed.iloc[1:], target.shift(1).iloc[1:], check_freq=False)
    assert (executed.iloc[0].drop("CASH") == 0).all()


def test_core_satellite_mixes_benchmark_and_satellite():
    monthly = _monthly()
    ctx = StrategyContext(config=CONFIG, equities=CTX.equities, bond="OBLI.PA", core_weight=0.7, satellite="momentum")
    mixed = build_target("core_satellite", monthly, ctx)
    satellite = build_target("momentum", monthly, ctx)
    month = monthly.index[-1]
    assert mixed.loc[month, "CW8.PA"] == pytest.approx(0.7 + 0.3 * satellite.loc[month, "CW8.PA"])
    assert "0.7" not in label("core_satellite", ctx) and "70%" in label("core_satellite", ctx)
    with pytest.raises(ValueError):
        build_target("core_satellite", monthly, StrategyContext(config=CONFIG, satellite="core_satellite"))


def test_availability_without_bond_and_unknown_strategy():
    monthly = _monthly().drop(columns="OBLI.PA")
    names = available_strategies(monthly, StrategyContext(config=CONFIG, bond="OBLI.PA"))
    assert "static_60_40" not in names and "dual_momentum" not in names and "benchmark" in names
    assert "allocation_fixe" not in names  # aucune allocation dans ce contexte
    assert "allocation_fixe" in available_strategies(monthly, CTX)
    target = build_target("allocation_fixe", monthly, CTX)
    valid = monthly[["CW8.PA", "PAEEM.PA"]].notna().all(axis=1)
    assert target.loc[valid, "CW8.PA"].eq(0.85).all() and target.loc[valid, "PAEEM.PA"].eq(0.15).all()
    with pytest.raises(ValueError, match="aucune allocation"):
        build_target("allocation_fixe", monthly, StrategyContext(config=CONFIG, bond="OBLI.PA"))
    with pytest.raises(ValueError, match="inconnue"):
        build_target("magic", monthly, CTX)

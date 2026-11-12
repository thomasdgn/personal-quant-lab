"""Moteur de backtest unique et format commun des résultats JSON."""

import json

import numpy as np
import pandas as pd
import pytest

from src.backtest import backtest_monthly_allocation
from src.engine import active_returns, first_invested, net_returns, run_backtest, run_strategies
from src.monthly_pipeline import MonthlyPipelineConfig
from src.results import meta_block, read_results_json, to_jsonable, write_results_json
from src.strategies import StrategyContext, build_strategy


def _monthly(n=120):
    index = pd.date_range("2010-01-31", periods=n, freq="ME")
    rng = np.random.default_rng(11)
    return pd.DataFrame({"CW8.PA": 100 * np.cumprod(1 + rng.normal(0.007, 0.04, n)),
                         "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.008, 0.05, n)),
                         "OBLI.PA": 100 * np.cumprod(1 + rng.normal(0.002, 0.01, n))}, index=index)


def _ctx():
    return StrategyContext(config=MonthlyPipelineConfig(), equities=("CW8.PA", "ESE.PA"), bond="OBLI.PA")


def test_engine_matches_raw_backtest_and_excludes_warmup():
    monthly, ctx = _monthly(), _ctx()
    runs = run_strategies(monthly, ctx, cost=0.001)
    assert list(runs)[0] == "benchmark" and "static_60_40" in runs
    run = runs["momentum_vt"]
    executed = build_strategy("momentum_vt", monthly, ctx)["executed_weights"]
    assets = [c for c in executed.columns if c != "CASH"]
    raw = backtest_monthly_allocation(monthly[assets], executed, transaction_cost=0.001)
    pd.testing.assert_frame_equal(run.backtest, raw)
    pd.testing.assert_frame_equal(run_backtest(monthly, executed, 0.001), raw)
    start = first_invested(raw)
    assert run.first_invested == start
    assert run.returns.loc[:start].iloc[:-1].isna().all() and run.returns.loc[start:].notna().all()
    pd.testing.assert_series_equal(net_returns(monthly, executed, 0.001), active_returns(raw))
    assert set(run_strategies(monthly, ctx, cost=0.001, names=["benchmark"])) == {"benchmark"}


def test_results_json_meta_block_and_strict_values(tmp_path):
    payload = {"a": np.float64(np.nan), "b": np.int64(3), "c": np.bool_(True), "d": pd.Timestamp("2026-01-31"),
               "e": [np.inf, 1.5], "f": pd.Series({"x": 1.0})}
    path = write_results_json(payload, tmp_path / "r.json", kind="stress", start="2008-01-31", end="2026-08-31",
                              synthetic_share=0.5, notes=["n"])
    assert b"\r" not in path.read_bytes()  # fins de ligne LF sur tous les postes (.gitattributes)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["a"] is None and data["b"] == 3 and data["c"] is True and data["d"].startswith("2026-01-31")
    assert data["e"] == [None, 1.5] and data["f"] == {"x": 1.0}
    meta = data["meta"]
    assert meta["kind"] == "stress" and meta["schema_version"] == "1.0" and meta["synthetic_share"] == 0.5
    assert meta["data_window"] == {"start": "2008-01-31", "end": "2026-08-31"} and meta["notes"] == ["n"]
    assert read_results_json(path, "stress")["b"] == 3
    with pytest.raises(ValueError, match="attendu"):
        read_results_json(path, "plans")
    assert read_results_json(tmp_path / "absent.json") is None
    with pytest.raises(ValueError, match="inconnu"):
        meta_block("autre")
    assert to_jsonable((1, {2: np.float32(0.5)})) == [1, {"2": 0.5}]

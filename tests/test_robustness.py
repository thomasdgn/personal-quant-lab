"""Robustesse des stratégies : statistiques, grilles, verdicts, rapport et CLI (hors-ligne)."""

import json

import numpy as np
import pandas as pd
import pytest

import main
from src.monthly_pipeline import MonthlyPipelineConfig
from src.robustness import (
    PARAM_GRIDS,
    annual_sharpe,
    deflated_sharpe,
    expected_max_sharpe,
    generate_robustness_report,
    grid_for,
    params_key,
    probabilistic_sharpe,
    rolling_comparison,
    _edge,
    _protection,
    _verdict,
    run_robustness,
    save_robustness_json,
    subperiods,
    worst_window_cagr,
)
from src.strategies import StrategyContext


def _series(values, start="2008-01-31"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="ME"))


def _universe(n=204, seed=7):
    index = pd.date_range("2008-01-31", periods=n, freq="ME")
    rng = np.random.default_rng(seed)
    cols = {"CW8.PA": (0.007, 0.045), "ESE.PA": (0.008, 0.05), "PAEEM.PA": (0.005, 0.06), "OBLI.PA": (0.002, 0.012)}
    return pd.DataFrame({c: 100 * np.cumprod(1 + rng.normal(mu, sd, n)) for c, (mu, sd) in cols.items()}, index=index)


def test_probabilistic_and_deflated_sharpe():
    rng = np.random.default_rng(0)
    strong = _series(rng.normal(0.02, 0.03, 240))
    noise = _series(rng.normal(0.0, 0.03, 240))
    assert probabilistic_sharpe(strong) > 0.99
    assert 0.05 < probabilistic_sharpe(noise) < 0.95
    assert probabilistic_sharpe(_series([0.01, 0.02, 0.0])) is None
    assert expected_max_sharpe(1, 0.1) == 0.0
    assert 0 < expected_max_sharpe(10, 0.1) < expected_max_sharpe(100, 0.1)
    assert deflated_sharpe(strong, 100, 0.1) <= probabilistic_sharpe(strong)


def test_worst_window_and_rolling_comparison():
    returns = _series([0.02] * 30 + [-0.03] * 12 + [0.01] * 30)
    brute = min((1 + returns.iloc[i:i + 24]).prod() ** (12 / 24) - 1 for i in range(len(returns) - 23))
    assert worst_window_cagr(returns, 24) == pytest.approx(brute)
    assert worst_window_cagr(returns.iloc[:10], 24) is None
    bench = _series(np.random.default_rng(2).normal(0.005, 0.04, 120))
    better = rolling_comparison(bench + 0.002, bench, window=60)
    assert better["pct_better_return"] == 1.0 and better["n_windows"] == 61
    assert better["median_excess_cagr"] > 0
    assert rolling_comparison(bench.iloc[:30], bench, window=60) is None


def test_verdict_rules():
    assert _verdict([{"ok": True}, {"ok": True}, {"ok": None}]) == (1.0, "robuste")
    assert _verdict([{"ok": True}, {"ok": True}, {"ok": False}])[1] == "acceptable"
    assert _verdict([{"ok": False}, {"ok": True}])[1] == "fragile"
    assert _verdict([{"ok": None}])[1] == "non évaluable"
    rolling = {"pct_better_sharpe": 0.8, "median_excess_cagr": 0.01, "pct_shallower_drawdown": 0.9}
    assert _edge({"rolling": rolling, "excess_psr": 0.97, "excess_dsr": 0.95})["verdict"] == "démontrée"
    assert _edge({"rolling": rolling, "excess_psr": 0.97, "excess_dsr": 0.5})["verdict"] == "possible"
    assert _edge({"rolling": {**rolling, "pct_better_sharpe": 0.1}, "excess_psr": 0.3,
                  "excess_dsr": 0.0})["verdict"] == "non démontrée"
    assert _edge({"rolling": None, "excess_psr": None})["verdict"] == "n/a"
    item = {"rolling": rolling, "stats": {"max_drawdown": -0.2}}
    assert _protection(item, -0.4)["verdict"] == "forte"
    assert _protection({**item, "stats": {"max_drawdown": -0.39}}, -0.4)["verdict"] == "moyenne"
    assert _protection({"rolling": {**rolling, "pct_shallower_drawdown": 0.2}, "stats": {"max_drawdown": -0.4}},
                       -0.4)["verdict"] == "faible"


def test_subperiods_and_grid_defaults():
    returns = _series([0.01] * 200)
    periods = subperiods(returns, pd.Series(0.5, index=returns.index))
    assert [p["période"] for p in periods][:2] == ["2008-2012", "2013-2017"]
    assert all(p["part_synthetique"] == 0.5 for p in periods)
    config = MonthlyPipelineConfig()
    assert grid_for("momentum_vt", config)["vol_window"] == PARAM_GRIDS["momentum_vt"]["vol_window"]
    assert params_key({"target_vol": 0.1, "vol_window": 3}) == "target_vol=0.1 vol_window=3"
    from dataclasses import replace

    odd = replace(config, volatility_targeting=replace(config.volatility_targeting, volatility_window=5))
    assert 5 in grid_for("momentum_vt", odd)["vol_window"]


@pytest.mark.slow
def test_run_robustness_verdicts_report_and_json(tmp_path):
    monthly = _universe()
    ctx = StrategyContext(config=MonthlyPipelineConfig(), equities=("CW8.PA", "ESE.PA", "PAEEM.PA"), bond="OBLI.PA",
                          core_weight=0.8, satellite="momentum_vt")
    synthetic = pd.Series(np.linspace(1, 0, len(monthly)), index=monthly.index)
    study = run_robustness(monthly, ctx, transaction_cost=0.001, synthetic=synthetic, followed="momentum_vt")
    items = study["strategies"]
    assert set(items) >= {"benchmark", "momentum_vt", "top3_trend", "static_60_40", "core_satellite"}
    assert study["n_trials"] > len(items)
    for name, item in items.items():
        assert item["verdict"] in ("robuste", "acceptable", "fragile")
        assert 0 <= item["score"] <= 1
        if name == "benchmark":
            assert item["edge"] is None and item["protection"] is None
        else:
            assert item["edge"]["verdict"] in ("démontrée", "possible", "non démontrée")
            assert item["protection"]["verdict"] in ("forte", "moyenne", "faible")
    grid = items["top3_trend"]["grid"]
    assert grid["n_configs"] == 27 and grid["default"] == "lookback=12 ma=10 top_n=3"
    assert grid["default_rank"] is not None and grid["walk_forward"]["sharpe"] is not None
    assert study["meta_selection"]["choices"]
    assert annual_sharpe(study["series"]["benchmark"]) == pytest.approx(items["benchmark"]["stats"]["sharpe"])
    report = generate_robustness_report(study, tmp_path / "robustness.md").read_text(encoding="utf-8")
    assert "Fiabilité" in report and "Surperformance" in report and "Part synthétique" in report
    payload = json.loads(save_robustness_json(study, tmp_path / "robustness.json").read_text(encoding="utf-8"))
    assert payload["followed"] == "momentum_vt" and len(payload["series"]["dates"]) == study["n_months"]
    assert isinstance(payload["strategies"]["momentum"]["criteria"][0]["ok"], bool)


@pytest.mark.slow
def test_robustness_cli(tmp_path, capsys):
    monthly = _universe(n=150)
    data = tmp_path / "long_history.csv"
    monthly.rename_axis("Date").to_csv(data)
    sources = pd.DataFrame({c: c for c in monthly.columns}, index=monthly.index)
    sources.iloc[:60, 0] = "PROXY"
    sources.rename_axis("Date").to_csv(tmp_path / "long_history_sources.csv")
    long_cfg = tmp_path / "long.yaml"
    long_cfg.write_text("fx_ticker: EURUSD=X\nstart: '2008-01-01'\nchains:\n"
                        + "".join(f"  {c}:\n    - {{ticker: P{i}, currency: EUR}}\n" for i, c in enumerate(monthly)),
                        encoding="utf-8")
    assets = tmp_path / "assets.yaml"
    assets.write_text("universe:\n" + "".join(
        f"  - {{ticker: {c}, name: {c}, category: x, universe_active: true, notes: ''"
        + (", role: defensive" if c == "OBLI.PA" else "") + "}\n" for c in monthly), encoding="utf-8")
    out = tmp_path / "research" / "robustness_report.md"
    assert main.main(["robustness", "--assets", str(assets), "--long-config", str(long_cfg), "--long-data", str(data),
                      "--output", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "SYNTHÉTIQUE" in printed and "fiabilité" in printed
    assert out.exists() and out.with_suffix(".json").exists()

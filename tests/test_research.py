"""Recherche de robustesse : stratégies alternatives, walk-forward, bootstrap."""

import numpy as np
import pandas as pd
import pytest

from src.monthly_pipeline import MonthlyPipelineConfig
from src.research import (
    block_bootstrap_sharpe_diff,
    conclusion_lines,
    dual_momentum_weights,
    generate_research_report,
    grid_configs,
    grid_stability,
    inverse_vol_weights,
    run_research,
    save_heatmap,
    save_research_json,
    static_weights,
    walk_forward_selection,
)


def _monthly(n=110, seed=7):
    index = pd.date_range("2016-01-31", periods=n, freq="ME")
    rng = np.random.default_rng(seed)
    data = {
        "CW8.PA": 100 * np.cumprod(1 + rng.normal(0.008, 0.04, n)),
        "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.007, 0.05, n)),
        "PAEEM.PA": 100 * np.cumprod(1 + rng.normal(0.004, 0.06, n)),
        "OBLI.PA": 100 * np.cumprod(1 + rng.normal(0.002, 0.01, n)),
    }
    frame = pd.DataFrame(data, index=index)
    frame.loc[frame.index < "2018-12-31", "OBLI.PA"] = np.nan
    return frame


def test_grid_has_72_configurations():
    configs = grid_configs()
    assert len(configs) == 72 and len({c.key for c in configs}) == 72


def test_static_weights_are_lagged_and_wait_for_all_assets():
    monthly = _monthly()
    weights = static_weights(monthly, {"CW8.PA": 0.6, "OBLI.PA": 0.4})
    assert np.allclose(weights.sum(axis=1), 1.0)
    assert (weights.loc[:"2018-12-31", "OBLI.PA"] == 0).all()
    assert weights.loc["2019-01-31", "OBLI.PA"] == pytest.approx(0.4)  # décidé fin décembre, appliqué en janvier


def test_inverse_vol_weights_proportional_to_inverse_volatility():
    monthly = _monthly()
    weights = inverse_vol_weights(monthly, ["CW8.PA", "ESE.PA"])
    vol = monthly[["CW8.PA", "ESE.PA"]].pct_change().rolling(12).std()
    month = monthly.index[40]
    previous = monthly.index[39]
    expected = (1 / vol.loc[previous]) / (1 / vol.loc[previous]).sum()
    assert weights.loc[month, ["CW8.PA", "ESE.PA"]].to_numpy() == pytest.approx(expected.to_numpy())
    assert weights.loc[month, "CASH"] == pytest.approx(0.0)


def test_dual_momentum_prefers_bond_then_cash_when_equities_fall():
    index = pd.date_range("2020-01-31", periods=30, freq="ME")
    falling = pd.Series(np.linspace(100, 50, 30), index=index)
    rising_bond = pd.Series(np.linspace(100, 110, 30), index=index)
    weights = dual_momentum_weights(pd.DataFrame({"EQ": falling, "BOND": rising_bond}), ["EQ"], "BOND")
    assert weights.iloc[-1]["BOND"] == 1.0
    falling_bond = pd.Series(np.linspace(110, 100, 30), index=index)
    weights = dual_momentum_weights(pd.DataFrame({"EQ": falling, "BOND": falling_bond}), ["EQ"], "BOND")
    assert weights.iloc[-1]["CASH"] == 1.0


def test_bootstrap_identical_sharpe_gives_zero_difference():
    rng = np.random.default_rng(0)
    reference = pd.Series(rng.normal(0.01, 0.04, 90), index=pd.date_range("2018-01-31", periods=90, freq="ME"))
    result = block_bootstrap_sharpe_diff(reference * 2, reference, samples=300)
    assert result["diff"] == pytest.approx(0.0, abs=1e-12)
    assert result["low"] == pytest.approx(0.0, abs=1e-9) and result["high"] == pytest.approx(0.0, abs=1e-9)
    better = block_bootstrap_sharpe_diff(reference + 0.02, reference, samples=300)
    assert better["low"] > 0 and better["prob_positive"] == 1.0
    with pytest.raises(ValueError):
        block_bootstrap_sharpe_diff(reference.iloc[:5], reference.iloc[:5])


def test_walk_forward_only_uses_past_performance():
    index = pd.date_range("2015-01-31", periods=72, freq="ME")
    good_then_bad = pd.Series(np.where(index < "2019-01-31", 0.02, -0.02), index=index) + 0.001 * np.sin(np.arange(72))
    bad_then_good = pd.Series(np.where(index < "2019-01-31", -0.01, 0.03), index=index) + 0.001 * np.cos(np.arange(72))
    result = walk_forward_selection({"A": good_then_bad, "B": bad_then_good}, pd.Timestamp("2019-01-31"),
                                    index[-1], min_train=36)
    assert result["choices"][0]["config"] == "A"  # choisi sur le passé, même s'il échoue ensuite
    assert result["returns"].index.min() == pd.Timestamp("2019-01-31")
    with pytest.raises(ValueError):
        walk_forward_selection({"A": good_then_bad}, index[10], index[-1], min_train=36)


def test_grid_stability_rank_correlation():
    index = pd.date_range("2020-01-31", periods=40, freq="ME")
    rng = np.random.default_rng(1)
    returns = {f"c{i}": pd.Series(rng.normal(0.002 * i, 0.02, 40), index=index) for i in range(6)}
    stability = grid_stability(returns, index[0], index[-1])
    assert -1 <= stability["rank_correlation"] <= 1
    assert list(stability["table"].columns) == ["sharpe_total", "sharpe_1re_moitie", "sharpe_2e_moitie"]


@pytest.mark.slow
def test_run_research_and_report(tmp_path):
    study = run_research(_monthly(), MonthlyPipelineConfig(), roles={"OBLI.PA": "defensive"}, realistic_cost=0.002)
    assert pd.Timestamp(study["start"]) >= pd.Timestamp("2018-12-31")
    lengths = {len(item["returns"]) for item in study["results"].values()}
    assert lengths == {study["n_months"]}
    assert study["results"]["benchmark"]["vs_benchmark"] is None
    assert "cagr_realistic_cost" in study["results"]["momentum"]["stats"]
    assert study["n_strategies_tested"] == 72 + 8
    heatmap = save_heatmap(study, tmp_path / "figures" / "grid.png")
    text = generate_research_report(study, tmp_path / "r.md", heatmap=heatmap).read_text(encoding="utf-8")
    assert "Tableau de preuves" in text and "figures/grid.png" in text
    assert any("décision humaine" in line for line in conclusion_lines(study))
    import json

    payload = json.loads(save_research_json(study, tmp_path / "r.json").read_text(encoding="utf-8"))
    assert {row["key"] for row in payload["strategies"]} == set(study["results"])
    assert payload["conclusion"] == conclusion_lines(study) and payload["walk_forward"]

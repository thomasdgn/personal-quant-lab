import numpy as np
import pandas as pd
import pytest

from src.dca import generate_dca_report, money_weighted_return, run_dca_comparison, simulate_dca


def _returns(values, start="2020-01-31"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="ME"), dtype=float)


def test_simulate_dca_hand_computed():
    sim = simulate_dca(_returns([0.10, -0.10]), 100.0)
    # Mois 1 : (0 + 100) * 1.1 = 110 ; mois 2 : (110 + 100) * 0.9 = 189.
    assert sim["Value"].tolist() == pytest.approx([110.0, 189.0])
    assert sim["Cumulative Contributions"].tolist() == [100.0, 200.0]
    assert sim["Gain"].iloc[-1] == pytest.approx(-11.0)


def test_simulate_dca_skips_leading_nan_and_rejects_inner_nan():
    sim = simulate_dca(_returns([np.nan, 0.0, 0.0]), 50.0)
    assert len(sim) == 2 and sim["Value"].iloc[-1] == pytest.approx(100.0)
    with pytest.raises(ValueError):
        simulate_dca(_returns([0.0, np.nan, 0.0]), 50.0)


def test_contribution_cost_applies_only_to_invested_part():
    returns = _returns([0.0, 0.0])
    exposure = pd.Series([1.0, 0.5], index=returns.index)
    sim = simulate_dca(returns, 100.0, invested_exposure=exposure, transaction_cost=0.01)
    assert sim["Value"].iloc[-1] == pytest.approx(99.0 + 99.5)


def test_money_weighted_return_matches_constant_monthly_rate():
    monthly_rate = 0.01
    sim = simulate_dca(_returns([monthly_rate] * 36), 100.0)
    assert money_weighted_return(sim) == pytest.approx((1 + monthly_rate) ** 12 - 1, rel=1e-6)


def test_negative_inputs_rejected():
    with pytest.raises(ValueError):
        simulate_dca(_returns([0.0]), -1.0)


def test_comparison_uses_common_window_and_writes_report(tmp_path):
    long = _returns([0.01] * 24)
    short = _returns([0.02] * 12, start="2021-01-31")
    result = run_dca_comparison({"buy_and_hold": long, "momentum": short}, 100.0)
    assert result["start"] == "2021-01-31" and result["n_months"] == 12
    assert result["strategies"]["momentum"]["final_value_eur"] > result["strategies"]["buy_and_hold"]["final_value_eur"]
    path = generate_dca_report(result, tmp_path / "dca.md", benchmark="CW8.PA")
    text = path.read_text(encoding="utf-8")
    assert "Buy & Hold CW8.PA" in text and "TRI annualisé" in text


def test_comparison_start_parameter():
    series = _returns([0.01] * 24)
    result = run_dca_comparison({"a": series}, 10.0, start="2021-06-30")
    assert result["start"] == "2021-06-30"

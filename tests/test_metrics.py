import pandas as pd
import pytest

from src.backtest import build_equity_curve, buy_and_hold
from src.metrics import (
    annualized_return,
    compute_drawdown,
    compute_returns,
    max_drawdown,
    sharpe_ratio,
    yearly_returns,
)


def test_compute_returns():
    prices = pd.Series([100, 110, 121])
    returns = compute_returns(prices)

    assert returns.iloc[0] == pytest.approx(0.10)
    assert returns.iloc[1] == pytest.approx(0.10)


def test_build_equity_curve():
    returns = pd.Series([0.10, -0.05])
    equity = build_equity_curve(returns, initial_capital=1000)

    assert equity.iloc[0] == pytest.approx(1100)
    assert equity.iloc[1] == pytest.approx(1045)


def test_compute_returns_does_not_forward_fill_missing_prices():
    prices = pd.Series([100.0, None, 121.0])

    returns = compute_returns(prices)

    assert returns.empty


def test_annualized_return_uses_cagr():
    returns = pd.Series([0.10, 0.10])

    result = annualized_return(returns, periods_per_year=2)

    assert result == pytest.approx(0.21)


def test_sharpe_ratio_uses_mean_excess_return():
    returns = pd.Series([0.10, -0.05, 0.02])
    expected = returns.mean() / returns.std() * (3 ** 0.5)

    result = sharpe_ratio(returns, periods_per_year=3)

    assert result == pytest.approx(expected)


def test_constant_returns_have_undefined_sharpe_ratio():
    returns = pd.Series([0.01, 0.01, 0.01])

    result = sharpe_ratio(returns)

    assert pd.isna(result)


def test_compute_drawdown_is_negative_from_running_peak():
    equity = pd.Series([100.0, 120.0, 90.0, 130.0])

    drawdown = compute_drawdown(equity)

    assert drawdown.iloc[0] == pytest.approx(0.0)
    assert drawdown.iloc[2] == pytest.approx(-0.25)
    assert max_drawdown(equity) == pytest.approx(-0.25)


def test_yearly_returns_compounds_calendar_years():
    returns = pd.Series(
        [0.10, 0.10, -0.05],
        index=pd.to_datetime(["2024-01-02", "2024-12-31", "2025-01-02"]),
    )

    result = yearly_returns(returns)

    assert result.loc["2024-12-31"] == pytest.approx(0.21)
    assert result.loc["2025-12-31"] == pytest.approx(-0.05)


def test_buy_and_hold_uses_prices_and_starts_at_initial_capital():
    prices = pd.Series([100.0, 110.0, 121.0])

    result = buy_and_hold(prices, initial_capital=1000)

    assert result["Equity Curve"].iloc[0] == pytest.approx(1000)
    assert result["Equity Curve"].iloc[-1] == pytest.approx(1210)
    assert pd.isna(result["Returns"].iloc[0])

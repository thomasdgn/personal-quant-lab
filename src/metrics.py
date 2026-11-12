import numpy as np
import pandas as pd


def _clean_returns(returns: pd.Series) -> pd.Series:
    return returns.dropna()


def compute_returns(prices: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """
    Compute simple period returns from prices.

    Parameters:
    prices (pd.Series | pd.DataFrame): Price series or table.

    Returns:
    pd.Series | pd.DataFrame: Simple returns.
    """
    returns = prices.pct_change(fill_method=None)
    if isinstance(returns, pd.DataFrame):
        return returns.dropna(how="all")
    return returns.dropna()


def build_equity_curve(
    returns: pd.Series | pd.DataFrame,
    initial_capital: float = 1.0,
) -> pd.Series | pd.DataFrame:
    """
    Build an equity curve from simple returns.

    Parameters:
    returns (pd.Series | pd.DataFrame): Simple period returns.
    initial_capital (float): The initial investment amount.

    Returns:
    pd.Series | pd.DataFrame: Equity curve indexed like returns.
    """
    if isinstance(returns, pd.DataFrame):
        clean_returns = returns.dropna(how="all")
    else:
        clean_returns = returns.dropna()

    return (1 + clean_returns).cumprod() * initial_capital


def annualized_return(returns: pd.Series, periods_per_year: int = 252) -> float:
    """
    Calculate CAGR from a return series.
    """
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")

    clean_returns = _clean_returns(returns)
    if clean_returns.empty:
        return np.nan

    total_growth = (1 + clean_returns).prod()
    if total_growth < 0:
        return np.nan
    if total_growth == 0:
        return -1.0

    years = len(clean_returns) / periods_per_year
    return total_growth ** (1 / years) - 1


def annualized_volatility(
    returns: pd.Series,
    periods_per_year: int = 252,
) -> float:
    """
    Calculate annualized volatility from period returns.
    """
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")

    clean_returns = _clean_returns(returns)
    if clean_returns.empty:
        return np.nan

    return clean_returns.std() * np.sqrt(periods_per_year)


def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """
    Calculate annualized Sharpe ratio from period returns.
    """
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")

    clean_returns = _clean_returns(returns)
    if clean_returns.empty:
        return np.nan

    periodic_risk_free_rate = risk_free_rate / periods_per_year
    excess_returns = clean_returns - periodic_risk_free_rate
    excess_volatility = excess_returns.std()

    if excess_volatility == 0 or np.isnan(excess_volatility):
        return np.nan

    return excess_returns.mean() / excess_volatility * np.sqrt(periods_per_year)


def compute_drawdown(equity_curve: pd.Series) -> pd.Series:
    """
    Calculate drawdown at each date as a negative percentage from the peak.
    """
    clean_equity = equity_curve.dropna()
    if clean_equity.empty:
        return clean_equity

    running_max = clean_equity.cummax()
    return clean_equity / running_max.replace(0, np.nan) - 1


def max_drawdown(equity_curve: pd.Series) -> float:
    drawdown = compute_drawdown(equity_curve)
    if drawdown.empty:
        return np.nan
    return drawdown.min()


def yearly_returns(returns: pd.Series) -> pd.Series:
    """
    Calculate calendar-year returns from period returns.
    """
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise TypeError("returns must have a DatetimeIndex")

    clean_returns = _clean_returns(returns)
    return clean_returns.resample("YE").apply(lambda x: (1 + x).prod() - 1)


def performance_summary(
    returns: pd.Series,
    equity_curve: pd.Series,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
) -> pd.Series:
    """
    Combine the main performance metrics into one series.
    """
    clean_returns = _clean_returns(returns)
    clean_equity = equity_curve.dropna()
    annual = yearly_returns(clean_returns)

    summary = {
        "CAGR": annualized_return(clean_returns, periods_per_year),
        "Volatility": annualized_volatility(clean_returns, periods_per_year),
        "Sharpe": sharpe_ratio(clean_returns, risk_free_rate, periods_per_year),
        "Max Drawdown": max_drawdown(clean_equity),
        "Best Year": annual.max(),
        "Worst Year": annual.min(),
        "Final Capital": clean_equity.iloc[-1] if not clean_equity.empty else np.nan,
    }

    return pd.Series(summary)

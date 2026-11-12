import numpy as np
import pandas as pd
import pytest

from src.features import (
    compute_momentum,
    compute_moving_average,
    compute_trend_filter,
    to_monthly_prices,
)


# --------------------------------------------------------------------------- #
# to_monthly_prices
# --------------------------------------------------------------------------- #
def test_to_monthly_prices_keeps_last_available_price_of_month():
    index = pd.to_datetime(
        ["2024-01-30", "2024-01-31", "2024-02-27", "2024-02-29"]
    )
    prices = pd.Series([100.0, 101.0, 110.0, 111.0], index=index, name="CW8.PA")

    monthly = to_monthly_prices(prices)

    assert list(monthly.index) == list(pd.to_datetime(["2024-01-31", "2024-02-29"]))
    assert monthly.loc["2024-01-31"] == 101.0  # dernier prix de janvier
    assert monthly.loc["2024-02-29"] == 111.0  # dernier prix de février
    assert monthly.name == "CW8.PA"


def test_to_monthly_prices_sorts_unsorted_dates():
    index = pd.to_datetime(["2024-02-29", "2024-01-31"])
    prices = pd.Series([111.0, 101.0], index=index)

    monthly = to_monthly_prices(prices)

    assert monthly.index.is_monotonic_increasing
    assert monthly.iloc[0] == 101.0


def test_to_monthly_prices_preserves_dataframe_columns():
    index = pd.to_datetime(["2024-01-31", "2024-02-29"])
    prices = pd.DataFrame({"CW8.PA": [101.0, 111.0], "ESE.PA": [50.0, 55.0]}, index=index)

    monthly = to_monthly_prices(prices)

    assert list(monthly.columns) == ["CW8.PA", "ESE.PA"]


def test_to_monthly_prices_rejects_non_datetime_index():
    prices = pd.Series([1.0, 2.0], index=[0, 1])
    with pytest.raises(ValueError):
        to_monthly_prices(prices)


def test_to_monthly_prices_rejects_empty():
    prices = pd.Series([], dtype=float, index=pd.DatetimeIndex([]))
    with pytest.raises(ValueError):
        to_monthly_prices(prices)


# --------------------------------------------------------------------------- #
# compute_momentum
# --------------------------------------------------------------------------- #
def _monthly_series(values):
    index = pd.date_range("2023-01-31", periods=len(values), freq="ME")
    return pd.Series(values, index=index, dtype=float)


def test_compute_momentum_12_1_matches_manual_value():
    # 13 mois, prix croissant de 10 à 22 par pas de 1.
    prices = _monthly_series(list(range(10, 23)))

    momentum = compute_momentum(prices, lookback_months=12, skip_months=1)

    # A t=12 : prix(t-1)=21, prix(t-12)=10 -> 21/10 - 1 = 1.1
    assert momentum.iloc[12] == pytest.approx(1.1)
    # Les 12 premières valeurs sont NaN (historique insuffisant) et conservées.
    assert momentum.iloc[:12].isna().all()
    assert len(momentum) == len(prices)


def test_compute_momentum_skip_zero_differs_from_skip_one():
    prices = _monthly_series(list(range(10, 23)))

    skip1 = compute_momentum(prices, lookback_months=12, skip_months=1).iloc[12]
    skip0 = compute_momentum(prices, lookback_months=12, skip_months=0).iloc[12]

    assert skip1 == pytest.approx(1.1)   # 21/10 - 1
    assert skip0 == pytest.approx(1.2)   # 22/10 - 1


def test_compute_momentum_is_not_the_pct_change_approximation():
    # Prix non linéaires : la vraie formule diffère de pct_change(12)-pct_change(1).
    prices = _monthly_series([100, 90, 120, 80, 130, 95, 140, 70, 150, 60, 160, 50, 200])

    momentum = compute_momentum(prices, 12, 1).iloc[12]
    approx = (prices.pct_change(12) - prices.pct_change(1)).iloc[12]

    manual = prices.iloc[11] / prices.iloc[0] - 1.0  # 160/100 - 1 = 0.6
    assert momentum == pytest.approx(manual)
    assert momentum != pytest.approx(approx)


def test_compute_momentum_dataframe():
    index = pd.date_range("2023-01-31", periods=13, freq="ME")
    prices = pd.DataFrame(
        {"A": range(10, 23), "B": range(20, 46, 2)}, index=index, dtype=float
    )
    momentum = compute_momentum(prices, 12, 1)
    assert momentum.iloc[12]["A"] == pytest.approx(21 / 10 - 1)
    assert momentum.iloc[12]["B"] == pytest.approx(42 / 20 - 1)


@pytest.mark.parametrize(
    "lookback,skip",
    [(0, 0), (12, -1), (12, 12), (12, 13)],
)
def test_compute_momentum_invalid_params(lookback, skip):
    prices = _monthly_series(list(range(10, 23)))
    with pytest.raises(ValueError):
        compute_momentum(prices, lookback_months=lookback, skip_months=skip)


def test_compute_momentum_rejects_non_positive_prices():
    prices = _monthly_series([10, 0, 12] + list(range(13, 23)))
    with pytest.raises(ValueError):
        compute_momentum(prices, 12, 1)


# --------------------------------------------------------------------------- #
# compute_moving_average
# --------------------------------------------------------------------------- #
def test_compute_moving_average_simple_and_leading_nan():
    prices = _monthly_series([1, 2, 3, 4, 5])

    ma = compute_moving_average(prices, window=3)

    assert ma.iloc[:2].isna().all()            # min_periods=window
    assert ma.iloc[2] == pytest.approx(2.0)     # (1+2+3)/3
    assert ma.iloc[4] == pytest.approx(4.0)     # (3+4+5)/3


def test_compute_moving_average_invalid_window():
    prices = _monthly_series([1, 2, 3])
    with pytest.raises(ValueError):
        compute_moving_average(prices, window=0)


# --------------------------------------------------------------------------- #
# compute_trend_filter
# --------------------------------------------------------------------------- #
def test_compute_trend_filter_true_false_and_nan_is_false():
    index = pd.date_range("2023-01-31", periods=3, freq="ME")
    prices = pd.Series([1.0, 2.0, 3.0], index=index)
    ma = pd.Series([np.nan, 1.5, 2.5], index=index)

    trend = compute_trend_filter(prices, ma)

    assert list(trend) == [False, True, True]


def test_compute_trend_filter_rejects_misaligned_index():
    prices = pd.Series([1.0, 2.0], index=pd.date_range("2023-01-31", periods=2, freq="ME"))
    ma = pd.Series([1.0, 2.0], index=pd.date_range("2022-01-31", periods=2, freq="ME"))
    with pytest.raises(ValueError):
        compute_trend_filter(prices, ma)


def test_compute_trend_filter_rejects_type_mismatch():
    index = pd.date_range("2023-01-31", periods=2, freq="ME")
    prices = pd.Series([1.0, 2.0], index=index)
    ma = pd.DataFrame({"A": [1.0, 2.0]}, index=index)
    with pytest.raises(ValueError):
        compute_trend_filter(prices, ma)


def test_compute_trend_filter_rejects_misaligned_columns():
    index = pd.date_range("2023-01-31", periods=2, freq="ME")
    prices = pd.DataFrame({"A": [1.0, 2.0], "B": [1.0, 2.0]}, index=index)
    ma = pd.DataFrame({"A": [1.0, 2.0], "C": [1.0, 2.0]}, index=index)
    with pytest.raises(ValueError):
        compute_trend_filter(prices, ma)

import numpy as np
import pandas as pd
import pytest

from src.signals import (
    CASH_COLUMN,
    compute_eligibility,
    lag_weights_for_execution,
    rank_by_momentum,
    select_top_n_weights,
)


@pytest.fixture
def momentum() -> pd.DataFrame:
    index = pd.date_range("2023-01-31", periods=3, freq="ME")
    return pd.DataFrame(
        {
            "A": [0.5, -0.1, np.nan],
            "B": [0.2, 0.3, np.nan],
            "C": [np.nan, 0.4, np.nan],
        },
        index=index,
    )


@pytest.fixture
def trend() -> pd.DataFrame:
    index = pd.date_range("2023-01-31", periods=3, freq="ME")
    return pd.DataFrame(
        {
            "A": [True, True, False],
            "B": [True, False, False],
            "C": [True, True, False],
        },
        index=index,
    )


# --------------------------------------------------------------------------- #
# eligibility
# --------------------------------------------------------------------------- #
def test_eligibility_combines_momentum_and_trend(momentum, trend):
    eligible = compute_eligibility(momentum, trend)

    assert list(eligible.iloc[0]) == [True, True, False]   # C: momentum NaN
    assert list(eligible.iloc[1]) == [True, False, True]   # B: sous sa MA
    assert list(eligible.iloc[2]) == [False, False, False]  # aucune tendance


def test_eligibility_require_positive_momentum(momentum, trend):
    eligible = compute_eligibility(momentum, trend, require_positive_momentum=True)
    # A a un momentum de -0.1 en t1 : exclu si on exige un momentum positif.
    assert eligible.iloc[1]["A"] == False
    assert eligible.iloc[1]["C"] == True


# --------------------------------------------------------------------------- #
# ranking
# --------------------------------------------------------------------------- #
def test_rank_by_momentum_orders_eligible_assets(momentum, trend):
    eligible = compute_eligibility(momentum, trend)
    ranks = rank_by_momentum(momentum, eligible)

    assert ranks.iloc[0]["A"] == 1  # 0.5 meilleur que 0.2
    assert ranks.iloc[0]["B"] == 2
    assert np.isnan(ranks.iloc[0]["C"])
    # t1 : C (0.4) devant A (-0.1), B non éligible.
    assert ranks.iloc[1]["C"] == 1
    assert ranks.iloc[1]["A"] == 2
    assert np.isnan(ranks.iloc[1]["B"])


def test_rank_all_invalid_row_is_all_nan(momentum, trend):
    eligible = compute_eligibility(momentum, trend)
    ranks = rank_by_momentum(momentum, eligible)
    assert ranks.iloc[2].isna().all()


# --------------------------------------------------------------------------- #
# weight selection
# --------------------------------------------------------------------------- #
def test_select_top_1_weights(momentum, trend):
    eligible = compute_eligibility(momentum, trend)
    weights = select_top_n_weights(momentum, eligible, top_n=1)

    assert weights.iloc[0]["A"] == 1.0
    assert weights.iloc[0][CASH_COLUMN] == 0.0
    assert weights.iloc[1]["C"] == 1.0            # meilleur momentum éligible
    assert weights.iloc[2][CASH_COLUMN] == 1.0    # aucun actif éligible


def test_select_top_1_excludes_asset_below_moving_average(momentum, trend):
    eligible = compute_eligibility(momentum, trend)
    weights = select_top_n_weights(momentum, eligible, top_n=1)
    # En t1, B a le meilleur momentum (0.3) mais est sous sa MA -> jamais choisi.
    assert weights.iloc[1]["B"] == 0.0


def test_select_top_2_weights(momentum, trend):
    eligible = compute_eligibility(momentum, trend)
    weights = select_top_n_weights(momentum, eligible, top_n=2)

    assert weights.iloc[0]["A"] == pytest.approx(0.5)
    assert weights.iloc[0]["B"] == pytest.approx(0.5)
    assert weights.iloc[0][CASH_COLUMN] == pytest.approx(0.0)
    # t1 : seuls C et A éligibles -> 0.5 / 0.5.
    assert weights.iloc[1]["C"] == pytest.approx(0.5)
    assert weights.iloc[1]["A"] == pytest.approx(0.5)


def test_select_top_2_partial_fill_goes_to_cash():
    index = pd.date_range("2023-01-31", periods=1, freq="ME")
    momentum = pd.DataFrame({"A": [0.5], "B": [np.nan]}, index=index)
    trend = pd.DataFrame({"A": [True], "B": [True]}, index=index)
    eligible = compute_eligibility(momentum, trend)

    weights = select_top_n_weights(momentum, eligible, top_n=2)
    # 1 seul éligible sur 2 emplacements -> 0.5 actif + 0.5 cash.
    assert weights.iloc[0]["A"] == pytest.approx(0.5)
    assert weights.iloc[0][CASH_COLUMN] == pytest.approx(0.5)


def test_weights_sum_to_one_and_are_non_negative(momentum, trend):
    eligible = compute_eligibility(momentum, trend)
    for top_n in (1, 2):
        weights = select_top_n_weights(momentum, eligible, top_n=top_n)
        assert np.allclose(weights.sum(axis=1), 1.0)
        assert (weights.to_numpy() >= 0).all()


def test_select_rejects_cash_name_conflict():
    index = pd.date_range("2023-01-31", periods=1, freq="ME")
    momentum = pd.DataFrame({"CASH": [0.5]}, index=index)
    trend = pd.DataFrame({"CASH": [True]}, index=index)
    eligible = compute_eligibility(momentum, trend)
    with pytest.raises(ValueError):
        select_top_n_weights(momentum, eligible, top_n=1)


# --------------------------------------------------------------------------- #
# execution lag
# --------------------------------------------------------------------------- #
def test_lag_weights_shifts_by_one_and_starts_in_cash():
    index = pd.date_range("2023-01-31", periods=3, freq="ME")
    target = pd.DataFrame(
        {
            "A": [1.0, 0.0, 0.0],
            "B": [0.0, 1.0, 0.0],
            CASH_COLUMN: [0.0, 0.0, 1.0],
        },
        index=index,
    )

    executed = lag_weights_for_execution(target, periods=1)

    # Première période : pas de signal antérieur -> 100 % cash.
    assert executed.iloc[0][CASH_COLUMN] == 1.0
    assert executed.iloc[0]["A"] == 0.0
    # Le signal de t0 (A) est exécuté en t1.
    assert executed.iloc[1]["A"] == 1.0
    # Le signal de t1 (B) est exécuté en t2.
    assert executed.iloc[2]["B"] == 1.0
    assert np.allclose(executed.sum(axis=1), 1.0)


def test_lag_weights_rejects_invalid_periods():
    index = pd.date_range("2023-01-31", periods=2, freq="ME")
    target = pd.DataFrame({"A": [1.0, 1.0], CASH_COLUMN: [0.0, 0.0]}, index=index)
    with pytest.raises(ValueError):
        lag_weights_for_execution(target, periods=0)

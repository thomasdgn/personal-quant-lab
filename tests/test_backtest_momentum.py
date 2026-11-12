import numpy as np
import pandas as pd
import pytest

from src.backtest import CASH_COLUMN, backtest_monthly_allocation


def _months(n):
    return pd.date_range("2023-01-31", periods=n, freq="ME")


def _weights(index, rows):
    """Construit un DataFrame de poids à partir de lignes {colonne: poids}."""
    cols = sorted({c for row in rows for c in row})
    data = {c: [row.get(c, 0.0) for row in rows] for c in cols}
    return pd.DataFrame(data, index=index)


# --------------------------------------------------------------------------- #
# comportements de base
# --------------------------------------------------------------------------- #
def test_full_cash_keeps_capital_constant():
    index = _months(3)
    prices = pd.DataFrame({"A": [100.0, 110.0, 121.0]}, index=index)
    weights = _weights(index, [{CASH_COLUMN: 1.0}] * 3)

    result = backtest_monthly_allocation(prices, weights, initial_capital=10_000.0)

    assert np.allclose(result["Equity Curve"], 10_000.0)
    assert np.allclose(result["Turnover"], 0.0)
    assert np.allclose(result["Transaction Cost"], 0.0)


def test_single_asset_growth_is_correct():
    index = _months(3)
    prices = pd.DataFrame({"A": [100.0, 110.0, 121.0]}, index=index)
    # d0 en cash (démarrage), puis 100 % A -> capte les +10 % mensuels.
    weights = _weights(index, [{CASH_COLUMN: 1.0}, {"A": 1.0}, {"A": 1.0}])

    result = backtest_monthly_allocation(prices, weights, transaction_cost=0.0)

    assert result["Equity Curve"].iloc[0] == pytest.approx(10_000.0)
    assert result["Equity Curve"].iloc[1] == pytest.approx(11_000.0)
    assert result["Equity Curve"].iloc[2] == pytest.approx(12_100.0)
    assert not result["Equity Curve"].isna().any()
    assert not result["Net Return"].isna().any()


def test_no_cost_when_turnover_is_zero():
    index = _months(4)
    prices = pd.DataFrame({"A": [100.0, 110.0, 121.0, 133.1]}, index=index)
    weights = _weights(
        index, [{CASH_COLUMN: 1.0}, {"A": 1.0}, {"A": 1.0}, {"A": 1.0}]
    )

    result = backtest_monthly_allocation(prices, weights, transaction_cost=0.01)

    # Turnover nul après l'entrée initiale -> coût nul sur ces mois.
    assert result["Turnover"].iloc[2] == pytest.approx(0.0)
    assert result["Transaction Cost"].iloc[2] == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# convention de turnover
# --------------------------------------------------------------------------- #
def test_cash_to_asset_turnover_is_one_hundred_percent():
    index = _months(2)
    prices = pd.DataFrame({"A": [100.0, 110.0]}, index=index)
    weights = _weights(index, [{CASH_COLUMN: 1.0}, {"A": 1.0}])

    result = backtest_monthly_allocation(prices, weights, transaction_cost=0.001)

    assert result["Turnover"].iloc[1] == pytest.approx(1.0)             # 100 %, pas 50 %
    assert result["Transaction Cost"].iloc[1] == pytest.approx(0.001)   # tc * 1.0


def test_asset_to_asset_turnover_is_full_replacement_not_double():
    index = _months(3)
    prices = pd.DataFrame(
        {"A": [100.0, 110.0, 121.0], "B": [50.0, 55.0, 60.5]}, index=index
    )
    weights = _weights(
        index, [{CASH_COLUMN: 1.0}, {"A": 1.0}, {"B": 1.0}]
    )

    result = backtest_monthly_allocation(prices, weights, transaction_cost=0.001)

    # A -> B : remplacement complet = 100 % de turnover (et non 200 %).
    assert result["Turnover"].iloc[2] == pytest.approx(1.0)
    assert result["Transaction Cost"].iloc[2] == pytest.approx(0.002)  # deux ordres à 0,10 %


def test_higher_transaction_cost_reduces_net_performance():
    index = _months(3)
    prices = pd.DataFrame(
        {"A": [100.0, 110.0, 121.0], "B": [50.0, 55.0, 60.5]}, index=index
    )
    weights = _weights(index, [{CASH_COLUMN: 1.0}, {"A": 1.0}, {"B": 1.0}])

    finals = []
    for tc in (0.0, 0.001, 0.002, 0.003):
        res = backtest_monthly_allocation(prices, weights, transaction_cost=tc)
        finals.append(res["Equity Curve"].iloc[-1])

    # Strictement décroissant : plus de frais -> moins de capital final.
    assert finals[0] > finals[1] > finals[2] > finals[3]


# --------------------------------------------------------------------------- #
# preuve d'absence de look-ahead
# --------------------------------------------------------------------------- #
def test_lookahead_strategy_would_beat_correct_one():
    """Un backtest qui choisit avec le rendement du mois courant (triche) doit
    surperformer la version correcte à poids décalés. Cela prouve que le moteur
    récompense bien le look-ahead — et donc que la version correcte, qui ne
    triche pas, ne regarde pas le futur par accident."""
    index = _months(6)
    # Rendements mensuels : A et B alternent gagnant (+10 %) / perdant (-5 %).
    r_a = [0.10, -0.05, 0.10, -0.05, 0.10]
    r_b = [-0.05, 0.10, -0.05, 0.10, -0.05]
    a = [100.0]
    b = [100.0]
    for ra, rb in zip(r_a, r_b, strict=True):
        a.append(a[-1] * (1 + ra))
        b.append(b[-1] * (1 + rb))
    prices = pd.DataFrame({"A": a, "B": b}, index=index)

    # Triche : chaque mois, on détient le gagnant DU mois (utilise prix[t]).
    cheat_rows = [{CASH_COLUMN: 1.0}]
    for ra, rb in zip(r_a, r_b, strict=True):
        cheat_rows.append({"A": 1.0} if ra > rb else {"B": 1.0})

    # Correct : on détient le gagnant DU MOIS PRÉCÉDENT (poids décalés).
    correct_rows = [{CASH_COLUMN: 1.0}, {CASH_COLUMN: 1.0}]
    for i in range(1, 5):
        correct_rows.append({"A": 1.0} if r_a[i - 1] > r_b[i - 1] else {"B": 1.0})

    cheat = backtest_monthly_allocation(prices, _weights(index, cheat_rows), transaction_cost=0.0)
    correct = backtest_monthly_allocation(prices, _weights(index, correct_rows), transaction_cost=0.0)

    cheat_final = cheat["Equity Curve"].iloc[-1]
    correct_final = correct["Equity Curve"].iloc[-1]

    assert cheat_final > 10_000.0     # la triche gagne toujours
    assert correct_final < 10_000.0   # la version décalée subit le retournement
    assert cheat_final > correct_final


# --------------------------------------------------------------------------- #
# validations
# --------------------------------------------------------------------------- #
def test_rejects_negative_weights():
    index = _months(2)
    prices = pd.DataFrame({"A": [100.0, 110.0]}, index=index)
    weights = _weights(index, [{CASH_COLUMN: 1.0}, {"A": 1.5, CASH_COLUMN: -0.5}])
    with pytest.raises(ValueError):
        backtest_monthly_allocation(prices, weights)


def test_rejects_weights_above_one():
    index = _months(2)
    prices = pd.DataFrame({"A": [100.0, 110.0], "B": [50.0, 55.0]}, index=index)
    weights = _weights(index, [{CASH_COLUMN: 1.0}, {"A": 0.7, "B": 0.7}])
    with pytest.raises(ValueError):
        backtest_monthly_allocation(prices, weights)


def test_rejects_exposure_to_nan_return():
    index = _months(2)
    prices = pd.DataFrame({"A": [100.0, 110.0]}, index=index)
    # 100 % A dès le premier mois : rendement d0 indisponible -> refus.
    weights = _weights(index, [{"A": 1.0}, {"A": 1.0}])
    with pytest.raises(ValueError):
        backtest_monthly_allocation(prices, weights)


def test_rejects_missing_cash_column():
    index = _months(2)
    prices = pd.DataFrame({"A": [100.0, 110.0]}, index=index)
    weights = pd.DataFrame({"A": [0.0, 1.0]}, index=index)
    with pytest.raises(ValueError):
        backtest_monthly_allocation(prices, weights)


# --------------------------------------------------------------------------- #
# Constat 3 : les poids NaN sont toujours invalides (sans compl\u00e9tion cash)
# --------------------------------------------------------------------------- #
def test_rejects_single_nan_weight_with_cell_location():
    index = _months(2)
    prices = pd.DataFrame({"A": [100.0, 110.0]}, index=index)
    weights = _weights(index, [{CASH_COLUMN: 1.0}, {"A": 1.0, CASH_COLUMN: 0.0}])
    weights.loc[index[1], CASH_COLUMN] = np.nan

    with pytest.raises(ValueError, match="NaN cell\\(s\\).*CASH"):
        backtest_monthly_allocation(prices, weights)


def test_rejects_multiple_nan_weights_with_all_cell_locations():
    index = _months(2)
    prices = pd.DataFrame({"A": [100.0, 110.0], "B": [50.0, 55.0]}, index=index)
    weights = _weights(index, [{CASH_COLUMN: 1.0}, {"A": 0.5, "B": 0.5, CASH_COLUMN: 0.0}])
    weights.loc[index[0], "A"] = np.nan
    weights.loc[index[1], "B"] = np.nan

    with pytest.raises(ValueError, match="column='A'.*column='B'"):
        backtest_monthly_allocation(prices, weights)


def test_rejects_nan_weights_in_a_single_column():
    index = _months(3)
    prices = pd.DataFrame({"A": [100.0, 110.0, 121.0]}, index=index)
    weights = _weights(index, [
        {CASH_COLUMN: 1.0},
        {"A": 1.0, CASH_COLUMN: 0.0},
        {"A": 1.0, CASH_COLUMN: 0.0},
    ])
    weights.loc[index[1]:, "A"] = np.nan

    with pytest.raises(ValueError, match="column='A'.*column='A'"):
        backtest_monthly_allocation(prices, weights)


# --------------------------------------------------------------------------- #
# Constat 3 : les poids doivent totaliser exactement 1 (cash explicite)
# --------------------------------------------------------------------------- #
def test_rejects_underallocated_row():
    # Scénario Codex : ligne ETF_A=0.5, CASH=0.0 (somme 0.5) -> ValueError.
    index = _months(2)
    prices = pd.DataFrame({"A": [100.0, 110.0]}, index=index)
    weights = _weights(index, [{CASH_COLUMN: 1.0}, {"A": 0.5, CASH_COLUMN: 0.0}])
    with pytest.raises(ValueError, match="sum to 1.0"):
        backtest_monthly_allocation(prices, weights)


def test_accepts_fully_allocated_rows():
    index = _months(4)
    prices = pd.DataFrame(
        {"A": [100.0, 110.0, 121.0, 133.1], "B": [50.0, 55.0, 60.5, 66.55]}, index=index
    )
    # 100% A ; 50/50 A/cash ; 40/40/20 A/B/cash : toutes sommes = 1 -> acceptées.
    weights = _weights(index, [
        {CASH_COLUMN: 1.0},
        {"A": 1.0, CASH_COLUMN: 0.0},
        {"A": 0.5, CASH_COLUMN: 0.5},
        {"A": 0.4, "B": 0.4, CASH_COLUMN: 0.2},
    ])
    result = backtest_monthly_allocation(prices, weights)
    assert len(result) == 4
    # Invariants : Invested Exposure = somme des poids hors CASH ; + Cash = 1.
    assert np.allclose(result["Invested Exposure"] + result["Cash Weight"], 1.0)
    assert result["Invested Exposure"].iloc[3] == pytest.approx(0.8)
    assert result["Cash Weight"].iloc[3] == pytest.approx(0.2)


def test_weight_sum_tolerance():
    index = _months(2)
    prices = pd.DataFrame({"A": [100.0, 110.0]}, index=index)
    # 1er mois en cash (rendement indisponible), 2e mois somme = 1 + 1e-12 -> accepté.
    ok = _weights(index, [{CASH_COLUMN: 1.0}, {"A": 1.0 + 1e-12, CASH_COLUMN: 0.0}])
    backtest_monthly_allocation(prices, ok)
    # Hors tolérance -> rejeté (le check de somme précède le calcul des rendements).
    for bad_sum in (0.999, 1.001):
        bad = _weights(index, [{CASH_COLUMN: 1.0}, {"A": bad_sum, CASH_COLUMN: 0.0}])
        with pytest.raises(ValueError, match="sum to 1.0"):
            backtest_monthly_allocation(prices, bad)

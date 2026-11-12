"""Indépendance temporelle et contrats du simulateur / macro / registre."""
import pandas as pd
import pytest

from src.account_simulator import simulate_account
from src.costs import FeeModel
from src.macro import available_observations, load_observations, macro_context
from src.provenance import record_trial
from src.tactical_research import build_targets, configurations


def test_account_buys_after_signal_not_before_gap():
    dates = pd.to_datetime(["2026-01-30", "2026-02-02", "2026-02-03"])
    prices = pd.DataFrame({"A": [10, 20, 22]}, index=dates)
    target = pd.DataFrame({"A": [1.], "CASH": [0.]}, index=pd.to_datetime(["2026-01-31"]))
    sim = simulate_account(prices, target, fee_model=FeeModel(proportional=0), initial_capital=100,
                           monthly_contribution=0)
    assert sim["curve"]["nav"].tolist() == pytest.approx([100, 100, 110])
    assert sim["orders"]["date"].iloc[0] == dates[1]
    assert sim["orders"]["quantity"].iloc[0] == 5
    changed = prices.copy()
    changed.iloc[-1] = 100
    replay = simulate_account(changed, target, fee_model=FeeModel(proportional=0), initial_capital=100,
                              monthly_contribution=0)
    assert replay["orders"].iloc[0].equals(sim["orders"].iloc[0])


def test_account_cash_and_fees_conserved_with_minimum():
    dates = pd.bdate_range("2026-01-01", "2026-04-02")
    prices = pd.DataFrame({"A": 7.}, index=dates)
    target = pd.DataFrame({"A": [1.], "CASH": [0.]}, index=pd.to_datetime(["2025-12-31"]))
    fees = FeeModel(tariff="decouverte", commission_cap=.005, minimum_order_amount=100)
    result = simulate_account(prices, target, fee_model=fees, initial_capital=0, monthly_contribution=100)
    orders, curve = result["orders"], result["curve"]
    assert (curve["cash"] >= 0).all() and (orders["amount"] >= 100).all()
    assert curve["nav"].iloc[-1] + orders["fee"].sum() == pytest.approx(curve["contributed"].iloc[-1])
    assert not (orders["date"] < pd.Timestamp("2026-02-01")).any()


def test_macro_revisions_known_only_after_release_and_collection(tmp_path):
    path = tmp_path / "m.csv"
    path.write_text("series_id,observation_date,release_at,acquired_at,value,source,vintage\n"
                    "CPI,2026-01-01,2026-02-10T10:00:00Z,2026-02-10T10:10:00Z,2.5,official,first\n"
                    "CPI,2026-01-01,2026-03-10T10:00:00Z,2026-03-10T10:10:00Z,2.8,official,revised\n", encoding="utf-8")
    data = load_observations(path)
    assert available_observations(data, "2026-02-10T10:05:00Z").empty
    assert macro_context(data, "2026-02-15")["observations"][0]["value"] == 2.5
    assert macro_context(data, "2026-03-15")["observations"][0]["value"] == 2.8


def test_trials_persist_and_count_distinct_specs(tmp_path):
    db = tmp_path / "trials.db"
    identity, count = record_trial(db, {"ma": 6}, {"data": "v1"})
    assert count == 1
    assert record_trial(db, {"ma": 6}, {"data": "v1"}) == (identity, 1)
    assert record_trial(db, {"ma": 6}, {"data": "v2"})[1] == 2


def test_target_prefix_unchanged_when_future_prices_change():
    dates = pd.bdate_range("2018-01-01", "2026-08-31")
    prices = pd.DataFrame({"CW8.PA": [100 + i * .1 for i in range(len(dates))],
                           "PAEEM.PA": 30., "ESE.PA": 20.}, index=dates)
    cfg = next(c for c in configurations() if c["family"] == "trend")
    first = build_targets(prices, cfg)
    prices.loc["2026-01-01":, "CW8.PA"] *= .5
    second = build_targets(prices, cfg)
    pd.testing.assert_frame_equal(first.loc[:"2025-12-31"], second.loc[:"2025-12-31"])


def test_cached_functions_do_not_share_entries(monkeypatch):
    import app.cache as cache

    monkeypatch.setattr(cache, "project_revision", lambda root: "same-inputs")

    @cache.project_cache(show_spinner=False)
    def first():
        return "first"

    @cache.project_cache(show_spinner=False)
    def second():
        return "second"

    assert first() == "first" and second() == "second"

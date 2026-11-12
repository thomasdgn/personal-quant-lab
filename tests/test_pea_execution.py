"""Contrats économiques PEA : frais, admissibilité, conservation du cash et reprise."""
import json

import pandas as pd
import pytest

from src.backtest import backtest_monthly_allocation
from src.contribution_plan import plan_contribution, purchase_calendar
from src.costs import FeeModel
from src.notify import NotifyConfig, build_events, send_events
from src.pea_account import import_transactions, reconcile, readiness
from src.trading_calendar import last_session_of_month, session_age


def test_discovery_caps_and_both_sides():
    fees = FeeModel(tariff="decouverte", commission_cap=.005, free_buy_tickers=("PARTNER",))
    assert fees.order_cost(100) == pytest.approx(.5)
    assert fees.order_cost(500) == pytest.approx(1.99)
    assert fees.order_cost(1000) == pytest.approx(5)
    assert fees.order_cost(100, "PARTNER") == 0
    assert fees.order_cost(100, "PARTNER", side="SELL") == pytest.approx(.5)
    with pytest.raises(ValueError):
        fees.order_cost(float("nan"))


def test_minimum_lot_can_cross_target_and_accumulates_cash():
    fees = FeeModel(tariff="decouverte", commission_cap=.005, minimum_order_amount=100)
    first = plan_contribution({}, {"W": 7, "E": 30}, {"W": .85, "E": .15}, contribution=100, fee_model=fees)
    assert first["total_spent"] == 0  # 15 parts = 105 €, plus commission
    second = plan_contribution({}, {"W": 7, "E": 30}, {"W": .85, "E": .15}, contribution=100,
                               cash_available=first["cash_after"], fee_model=fees)
    buys = second["table"].query("parts_a_acheter > 0")
    assert not buys.empty and (buys["montant"] >= 100).all()
    assert second["total_spent"] + second["cash_after"] == pytest.approx(200)


def test_drift_rebalance_and_switch_charge_both_orders():
    idx = pd.date_range("2020-01-31", periods=3, freq="ME")
    prices = pd.DataFrame({"A": [100, 120, 120], "B": [100, 100, 100]}, index=idx)
    weights = pd.DataFrame({"A": [0, .5, .5], "B": [0, .5, .5], "CASH": [1, 0, 0]}, index=idx)
    result = backtest_monthly_allocation(prices, weights, transaction_cost=.001)
    assert result["Turnover"].iloc[-1] == pytest.approx(5 / 110)
    assert result["Transaction Cost"].iloc[-1] == pytest.approx(10 / 110 * .001)
    weights.iloc[2] = [0, 1, 0]
    result = backtest_monthly_allocation(prices, weights, transaction_cost=.001)
    assert result["Traded Notional"].iloc[-1] == pytest.approx(120 / 110)


def test_notification_uses_followed_policy_and_retries_only_failed(tmp_path):
    snap = {"metadata": {"report_month": "2026-10"}, "policy": {"followed": "fixed"},
            "strategies": {"fixed": {"target_weights": {"W": 1}, "invested_exposure": 1}},
            "momentum_strategy": {"selected_assets": ["A"]}}
    previous = {**snap, "momentum_strategy": {"selected_assets": ["B"]}}
    events = build_events(snap, previous)
    assert [e["code"] for e in events] == ["REPORT_READY"]
    assert "fixed : W" in events[0]["message"]
    calls = []

    def post(*args):
        calls.append(args)
        return 500 if len(calls) == 1 else 200

    opts = dict(config=NotifyConfig(enabled=True, topic="test"), log_path=tmp_path / "n.jsonl", http_post=post)
    assert send_events(events, **opts)[0]["status"] == "error"
    assert send_events(events, **opts)[0]["status"] == "sent"
    assert send_events(events, **opts)[0]["status"] == "duplicate"
    assert len(calls) == 2


def test_exchange_month_end_and_persistent_anchor():
    assert last_session_of_month("2026-10-01") == pd.Timestamp("2026-10-30")
    assert last_session_of_month("2024-03-01") == pd.Timestamp("2024-03-28")  # Vendredi saint
    assert session_age("2024-03-28", "2024-04-01") == 0
    with pytest.raises(ValueError, match="persistante"):
        purchase_calendar("2026-10", 5)
    assert purchase_calendar("2027-04", 5, "2026-11")["buy"]


def test_report_friday_close_has_no_future_signal_label():
    from src.monthly_pipeline import MonthlyPipelineConfig, run_monthly_pipeline

    dates = pd.bdate_range("2016-01-01", "2026-10-30")
    prices = pd.DataFrame({"CW8.PA": [100 + i * .02 for i in range(len(dates))]}, index=dates)
    report = run_monthly_pipeline(prices, MonthlyPipelineConfig(), report_date="2026-10-30",
                                  generation_time="2026-10-30T20:00:00").report
    assert report.metadata["signal_date"] == "2026-10-30"


def test_import_reconcile_and_invalidation(tmp_path):
    csv = tmp_path / "import.csv"
    csv.write_text("operation_id,date,enveloppe,type,ticker,parts,prix,montant,frais\n"
                   "1,2026-10-01,pea,VERSEMENT,,0,0,200,0\n"
                   "2,2026-10-02,pea,ACHAT,W,10,10,100,0.5\n", encoding="utf-8")
    ledger = tmp_path / "ledger.csv"
    assert import_transactions(csv, ledger)["added"] == 2 and not ledger.exists()
    import_transactions(csv, ledger, apply=True)
    assert import_transactions(csv, ledger)["duplicates"] == 2
    snapshot = tmp_path / "snapshot.yaml"
    snapshot.write_text("source: relevé fictif pour test\ndate: 2026-10-02\nlignes:\n"
                        "  - {enveloppe: pea, ticker: W, parts: 10}\nliquidites_eur: {pea: 99.5}\n", encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    assert reconcile(ledger, snapshot, receipt_path=receipt)["ok"]
    prices = pd.DataFrame({"W": [10]}, index=pd.to_datetime(["2026-10-02"]))
    assert readiness(prices, ["W"], transactions_path=ledger, receipt_path=receipt, as_of="2026-10-02")["ready"]
    ledger.write_text(ledger.read_text() + "\n")
    assert not readiness(prices, ["W"], transactions_path=ledger, receipt_path=receipt, as_of="2026-10-02")["ready"]
    assert json.loads(receipt.read_text())["ok"]

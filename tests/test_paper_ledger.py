"""Portefeuille fictif du paper trading et champs du journal de décision."""

import json

import pandas as pd
import pytest

import main
from src.paper_ledger import build_paper_ledger, decision_points, generate_performance_report, ledger_summary_lines
from src.paper_trading import PaperTradingError, update_manual_decision


def _entry(signal, month, status, chosen=None, system="momentum_vt", targets=None):
    return {
        "schema_version": "1.0", "report_month": month, "signal_date": signal,
        "manual_decision_status": status, "manual_selected_strategy": chosen,
        "manual_approved_weights": None, "system_suggested_strategy": system,
        "target_weights": targets or {},
    }


@pytest.fixture
def prices():
    index = pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"])
    return pd.DataFrame({
        "A.PA": [100.0, 110.0, 99.0, 99.0],
        "B.PA": [100.0, 100.0, 120.0, 120.0],
        "CW8.PA": [100.0, 100.0, 100.0, 110.0],
    }, index=index)


@pytest.fixture
def entries():
    return [
        _entry("2026-01-31", "2026-02", "APPROVED_PAPER", "momentum",
               targets={"momentum": {"A.PA": 1.0, "CASH": 0.0}, "momentum_vt": {"A.PA": 0.5, "CASH": 0.5}}),
        _entry("2026-02-28", "2026-03", "REJECTED",
               targets={"momentum": {"B.PA": 1.0}, "momentum_vt": {"B.PA": 1.0, "CASH": 0.0}}),
        _entry("2026-03-31", "2026-04", "APPROVED_PAPER", "benchmark",
               targets={"benchmark": {"CW8.PA": 1.0}, "momentum_vt": {"CW8.PA": 1.0}}),
    ]


def test_ledger_hand_computed_over_three_months(entries, prices):
    ledger = build_paper_ledger(entries, prices, transaction_cost=0.0)
    assert ledger["n_months"] == 3 and ledger["start"] == "2026-02-28"
    monthly = ledger["monthly"]
    # Paper : A (+10 %), A conservé malgré le REJECTED (-10 %), puis CW8 (+10 %).
    assert monthly["paper_return"].tolist() == pytest.approx([0.10, -0.10, 0.10])
    # Système : 50 % A (+5 %), B (+20 %), CW8 (+10 %).
    assert monthly["system_return"].tolist() == pytest.approx([0.05, 0.20, 0.10])
    assert ledger["metrics"]["paper"]["total_return"] == pytest.approx(1.1 * 0.9 * 1.1 - 1)
    assert ledger["metrics"]["benchmark"]["total_return"] == pytest.approx(0.10)
    assert ledger["value_added"] == pytest.approx((1.1 * 0.9 * 1.1) - (1.05 * 1.2 * 1.1))
    assert ledger["metrics"]["paper"]["max_drawdown"] == pytest.approx(0.99 / 1.1 - 1)


def test_costs_are_charged_on_turnover(entries, prices):
    ledger = build_paper_ledger(entries, prices, transaction_cost=0.01)
    # Entrée : un achat ; bascule A -> CW8 : vente puis achat, soit trois côtés.
    assert ledger["metrics"]["paper"]["costs"] == pytest.approx(0.03)


def test_pending_months_and_same_signal_override():
    entries = [
        _entry("2026-01-31", "2026-02", "PENDING", targets={"momentum_vt": {"A.PA": 1.0}}),
        _entry("2026-01-31", "2026-03", "APPROVED_PAPER", "momentum", targets={"momentum": {"B.PA": 1.0}}),
    ]
    points = decision_points(entries)
    assert len(points) == 1 and points.iloc[0]["report_month"] == "2026-03"
    assert points.iloc[0]["paper_weights"] == {"B.PA": 1.0}


def test_no_approved_decision_returns_empty_ledger(prices):
    ledger = build_paper_ledger([_entry("2026-01-31", "2026-02", "PENDING")], prices)
    assert ledger["n_months"] == 0 and "APPROVED_PAPER" in ledger["warnings"][0]
    assert "APPROVED_PAPER" in ledger_summary_lines(ledger)[0]


def test_entry_without_prices_is_cash_and_warned(prices):
    entries = [_entry("2026-01-31", "2026-02", "APPROVED_PAPER", "momentum",
                      targets={"momentum": {"ZZZ.PA": 1.0}, "momentum_vt": {"ZZZ.PA": 1.0}})]
    ledger = build_paper_ledger(entries, prices, transaction_cost=0.0)
    assert any("ZZZ.PA" in w for w in ledger["warnings"])
    assert ledger["monthly"]["paper_return"].tolist() == pytest.approx([0.0, 0.0, 0.0])


def test_incomplete_month_is_excluded(entries, prices):
    daily = prices.copy()
    daily.loc[pd.Timestamp("2026-05-12")] = [100.0, 100.0, 120.0]
    assert build_paper_ledger(entries, daily)["end"] == "2026-04-30"


def test_missing_benchmark_raises(entries, prices):
    with pytest.raises(ValueError, match="Benchmark"):
        build_paper_ledger(entries, prices.drop(columns="CW8.PA"))


def test_performance_report(entries, prices, tmp_path):
    ledger = build_paper_ledger(entries, prices)
    text = generate_performance_report(ledger, tmp_path / "perf.md").read_text(encoding="utf-8")
    assert "Valeur ajoutée" in text and "REJECTED" in text
    "\n".join(ledger_summary_lines(ledger)).encode("cp1252")


# --- journal de décision --------------------------------------------------------
def _approvable():
    return {"available_strategies": ["benchmark", "momentum"], "target_weights": {"momentum": {"A.PA": 1.0}},
            "manual_decision_status": "PENDING"}


def test_decision_journal_fields_are_stored_and_merged():
    first = update_manual_decision(_approvable(), "APPROVED_PAPER", strategy="momentum",
                                   journal={"confidence": 4, "pros": "tendance", "cons": None})
    assert first["decision_journal"] == {"confidence": 4, "pros": "tendance"}
    second = update_manual_decision(first, "APPROVED_PAPER", strategy="momentum", journal={"next_check": "vol"})
    assert second["decision_journal"] == {"confidence": 4, "pros": "tendance", "next_check": "vol"}
    assert "decision_journal" not in update_manual_decision(_approvable(), "SKIPPED")


@pytest.mark.parametrize("journal", [{"confidence": 0}, {"confidence": 6}, {"confidence": "4"}, {"mood": "ok"}])
def test_decision_journal_validation(journal):
    with pytest.raises(PaperTradingError):
        update_manual_decision(_approvable(), "SKIPPED", journal=journal)


def test_cli_paper_decision_with_journal_and_performance(tmp_path, capsys):
    entry = {**_approvable(), "schema_version": "1.0", "report_month": "2026-02", "signal_date": "2026-01-31",
             "system_suggested_strategy": "momentum"}
    (tmp_path / "2026-02-paper-entry.json").write_text(json.dumps(entry), encoding="utf-8")
    code = main.main(["paper-decision", "--month", "2026-02", "--status", "APPROVED_PAPER", "--strategy", "momentum",
                      "--confidence", "3", "--pros", "signal clair", "--paper-dir", str(tmp_path)])
    assert code == 0
    saved = json.loads((tmp_path / "2026-02-paper-entry.json").read_text(encoding="utf-8"))
    assert saved["decision_journal"] == {"confidence": 3, "pros": "signal clair"}
    assert main.main(["paper-decision", "--month", "2026-02", "--status", "SKIPPED", "--confidence", "9",
                      "--paper-dir", str(tmp_path)]) == 1
    capsys.readouterr()

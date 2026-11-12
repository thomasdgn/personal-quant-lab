"""Positions réelles, modèle de frais et planificateur de versement (proposition)."""

import json
from pathlib import Path

import pandas as pd
import pytest

import main
from src.contribution_plan import generate_plan_report, plan_contribution, plan_lines, resolve_target
from src.costs import FeeModel, load_fee_model
from src.positions import envelope_weights, load_positions, value_positions
from tests.conftest import FIXTURE_CONFIG

ROOT = Path(__file__).resolve().parents[1]


# --- frais ----------------------------------------------------------------------
def test_order_cost_formula():
    model = FeeModel(proportional=0.001, fixed_per_order=1.0, minimum_per_order=2.0, spread_bps={"A": 20})
    assert model.order_cost(0) == 0.0
    assert model.order_cost(500) == pytest.approx(2.0)            # minimum > 1 + 0,5
    assert model.order_cost(5_000) == pytest.approx(6.0)          # 1 + 5
    assert model.order_cost(1_000, "A") == pytest.approx(2.0 + 1.0)  # demi-spread 10 bps
    assert model.effective_rate(500) == pytest.approx(0.004)


def test_fee_model_validation_and_loading(tmp_path):
    with pytest.raises(ValueError):
        FeeModel(proportional=0.5)
    with pytest.raises(ValueError):
        FeeModel(fixed_per_order=-1)
    assert load_fee_model(FIXTURE_CONFIG / "strategy_params.yaml").proportional == pytest.approx(0.001)
    legacy = tmp_path / "p.yaml"
    legacy.write_text("backtest:\n  transaction_cost: 0.002\n", encoding="utf-8")
    assert load_fee_model(legacy).proportional == pytest.approx(0.002)
    bad = tmp_path / "b.yaml"
    bad.write_text("costs:\n  courtage: 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="courtage"):
        load_fee_model(bad)


# --- positions ------------------------------------------------------------------
def _positions_file(tmp_path, body):
    path = tmp_path / "positions.yaml"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def prices():
    index = pd.bdate_range("2026-08-03", "2026-08-31")
    return pd.DataFrame({"A.PA": 10.0, "B.PA": 20.0, "CW8.PA": 700.0}, index=index)


def test_load_and_value_positions(tmp_path, prices):
    assert load_positions(tmp_path / "absent.yaml") is None
    path = _positions_file(tmp_path, "date: 2026-08-31\nlignes:\n  - {enveloppe: pea, ticker: A.PA, parts: 3}\n"
                                     "liquidites_eur:\n  pea: 70\n")
    valuation = value_positions(load_positions(path), prices)
    assert valuation["enveloppes"]["pea"] == {"titres": 30.0, "liquidites": 70.0, "total": 100.0}
    assert envelope_weights(valuation, "pea") == pytest.approx({"A.PA": 0.3, "CASH": 0.7})


@pytest.mark.parametrize("body, message", [
    ("lignes:\n  - {enveloppe: pea, ticker: A.PA, parts: -1}\n", "parts"),
    ("lignes:\n  - {enveloppe: pea, ticker: A.PA, parts: 1}\n  - {enveloppe: pea, ticker: A.PA, parts: 2}\n", "dupliquée"),
    ("lignes:\n  - {ticker: A.PA, parts: 1}\n", "enveloppe"),
])
def test_positions_validation(tmp_path, body, message):
    with pytest.raises(ValueError, match=message):
        load_positions(_positions_file(tmp_path, body))


def test_missing_price_for_held_line(tmp_path, prices):
    path = _positions_file(tmp_path, "lignes:\n  - {enveloppe: pea, ticker: ZZ.PA, parts: 1}\n")
    with pytest.raises(ValueError, match="ZZ.PA"):
        value_positions(load_positions(path), prices)


# --- planificateur ----------------------------------------------------------------
QUOTES = {"A.PA": 10.0, "B.PA": 20.0}


def test_plan_exact_arithmetic_whole_shares_within_budget():
    plan = plan_contribution({}, QUOTES, {"A.PA": 0.5, "B.PA": 0.5}, contribution=100.0,
                             fee_model=FeeModel(proportional=0.0))
    buys = plan["table"]["parts_a_acheter"].to_dict()
    assert buys == {"A.PA": 5, "B.PA": 2}
    assert plan["total_spent"] == pytest.approx(90.0) and plan["cash_after"] == pytest.approx(10.0)
    assert all(isinstance(v, int) and v >= 0 for v in buys.values())


def test_plan_includes_fees_and_never_exceeds_budget():
    model = FeeModel(proportional=0.001, fixed_per_order=1.0)
    plan = plan_contribution({}, QUOTES, {"A.PA": 1.0}, contribution=100.0, fee_model=model, max_fee_rate=0.5)
    assert plan["table"].loc["A.PA", "parts_a_acheter"] == 9
    assert plan["total_spent"] <= 100.0 + 1e-9
    assert plan["total_fees"] == pytest.approx(1.0 + 0.09)


def test_plan_only_buys_underweight_assets():
    # A déjà surpondéré : aucun achat de A, jamais de vente.
    plan = plan_contribution({"A.PA": 20}, QUOTES, {"A.PA": 0.2, "B.PA": 0.8}, contribution=100.0,
                             fee_model=FeeModel(proportional=0.0))
    assert plan["table"].loc["A.PA", "parts_a_acheter"] == 0
    assert plan["table"].loc["B.PA", "parts_a_acheter"] == 5
    assert (plan["table"]["parts_a_acheter"] >= 0).all()


def test_plan_target_already_reached():
    plan = plan_contribution({"A.PA": 5, "B.PA": 2}, QUOTES, {"A.PA": 50 / 90, "B.PA": 40 / 90}, contribution=0.0)
    assert plan["table"]["parts_a_acheter"].sum() == 0
    assert plan["max_drift_pct"] < 0.01 and plan["rebalancing"] is None


def test_plan_keeps_target_cash_and_explains_leftover():
    plan = plan_contribution({}, QUOTES, {"A.PA": 0.4, "CASH": 0.6}, contribution=100.0,
                             fee_model=FeeModel(proportional=0.0))
    assert plan["table"].loc["A.PA", "parts_a_acheter"] == 4
    assert "liquidités visées" in plan["notes"][0]


def test_plan_drops_order_with_excessive_fee_and_flags_expensive_share():
    plan = plan_contribution({}, {"A.PA": 10.0, "CW8.PA": 700.0}, {"A.PA": 0.5, "CW8.PA": 0.5}, contribution=100.0,
                             fee_model=FeeModel(proportional=0.0, fixed_per_order=5.0))
    assert plan["table"]["parts_a_acheter"].sum() == 0
    assert any("abandonné" in note for note in plan["notes"])
    assert any("CW8.PA coûte" in note for note in plan["notes"])


def test_plan_optional_rebalancing_when_drift_needs_sales():
    plan = plan_contribution({"A.PA": 100}, QUOTES, {"A.PA": 0.1, "B.PA": 0.9}, contribution=20.0,
                             fee_model=FeeModel(proportional=0.0), tolerance_pct=5)
    assert plan["rebalancing"] is not None
    assert any(trade["parts"] < 0 for trade in plan["rebalancing"]["trades"])


def test_plan_validation_errors():
    with pytest.raises(ValueError, match="Prix"):
        plan_contribution({}, {}, {"A.PA": 1.0}, contribution=100.0)
    with pytest.raises(ValueError):
        plan_contribution({}, QUOTES, {"A.PA": 0.7}, contribution=100.0)
    with pytest.raises(ValueError):
        plan_contribution({}, QUOTES, {"A.PA": 1.0}, contribution=-1.0)


def _entry(month, status, chosen=None):
    return {"report_month": month, "signal_date": f"{month}-01", "manual_decision_status": status,
            "manual_selected_strategy": chosen,
            "target_weights": {"benchmark": {"CW8.PA": 1.0, "CASH": 0.0}, "momentum_vt": {"A.PA": 0.4, "CASH": 0.6}}}


def test_resolve_target_uses_last_approved_strategy_on_latest_weights():
    target = resolve_target([_entry("2026-07", "APPROVED_PAPER", "momentum_vt"), _entry("2026-09", "PENDING")])
    assert target["strategy"] == "momentum_vt" and target["report_month"] == "2026-09"
    assert target["weights"] == {"A.PA": 0.4, "CASH": 0.6}
    assert resolve_target([_entry("2026-09", "PENDING")])["strategy"] == "benchmark"
    with pytest.raises(ValueError):
        resolve_target([])


def test_plan_report_and_console_lines(tmp_path):
    target = resolve_target([_entry("2026-09", "APPROVED_PAPER", "momentum_vt")])
    plan = plan_contribution({}, QUOTES, target["weights"], contribution=100.0)
    text = generate_plan_report(plan, target, tmp_path / "plan.md").read_text(encoding="utf-8")
    assert "aucun ordre passé" in text and "| A.PA |" in text
    "\n".join(plan_lines(plan, target)).encode("cp1252")


# --- CLI ------------------------------------------------------------------------
def test_cli_plan_contribution_and_patrimoine_use_positions(tmp_path, prices, capsys):
    data = tmp_path / "prices.csv"
    prices.rename_axis("Date").to_csv(data)
    paper = tmp_path / "paper"
    paper.mkdir()
    entry = {"schema_version": "1.0", **_entry("2026-09", "APPROVED_PAPER", "momentum_vt")}
    (paper / "2026-09-paper-entry.json").write_text(json.dumps(entry), encoding="utf-8")
    positions = _positions_file(tmp_path, "date: 2026-08-31\nlignes:\n  - {enveloppe: pea, ticker: A.PA, parts: 2}\n"
                                          "liquidites_eur:\n  pea: 50\n")
    code = main.main(["plan-contribution", "--transactions", "absent-transactions.csv", "--amount", "100", "--positions", str(positions), "--paper-dir", str(paper),
                      "--data", str(data), "--output-dir", str(tmp_path / "plans")])
    assert code == 0
    out = capsys.readouterr().out
    assert "ACHETER" in out and "aucun ordre passé" in out
    assert len(list((tmp_path / "plans").glob("*-plan.md"))) == 1

    holdings = tmp_path / "holdings.yaml"
    holdings.write_text("valeurs_eur:\n  livret_a: 1000\n", encoding="utf-8")
    assert main.main(["patrimoine", "--transactions", "absent-transactions.csv", "--holdings", str(holdings), "--positions", str(positions), "--data", str(data),
                      "--output", str(tmp_path / "patrimoine.md")]) == 0
    assert "Valeur pea issue des positions" in capsys.readouterr().out


def test_purchase_calendar_and_waiting_month():
    from src.contribution_plan import plan_contribution, purchase_calendar

    assert purchase_calendar("2026-10", 1)["buy"]
    cal = purchase_calendar("2026-10", 2)  # ancrage par défaut : janvier -> mois impairs
    assert not cal["buy"] and cal["next_buy"] == "2026-11" and cal["months_to_next"] == 1
    assert purchase_calendar("2026-10", 2, "2026-10")["buy"]
    assert purchase_calendar("2027-01", 3, "2026-10")["buy"] and not purchase_calendar("2027-02", 3, "2026-10")["buy"]
    with pytest.raises(ValueError, match="entre 1 et 12"):
        purchase_calendar("2026-10", 0)
    waiting = plan_contribution({}, {"WPEA.PA": 7.0}, {"WPEA.PA": 1.0, "CASH": 0.0}, contribution=150.0,
                                buy=False)
    assert waiting["table"]["parts_a_acheter"].sum() == 0 and waiting["cash_after"] == pytest.approx(150.0)
    assert "Mois d'attente" in waiting["notes"][0]


def test_purchase_frequency_config_validation(tmp_path):
    import yaml

    from src.patrimoine import load_patrimoine_config

    raw = yaml.safe_load((FIXTURE_CONFIG / "patrimoine.yaml").read_text(encoding="utf-8"))
    for key, value, message in (("frequence_achat_mois", 0, "frequence_achat_mois"),
                                ("premier_mois_achat", "octobre", "premier_mois_achat")):
        bad = {**raw, "profil": {**raw["profil"], key: value}}
        path = tmp_path / "p.yaml"
        path.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_patrimoine_config(path)
    good = {**raw, "profil": {**raw["profil"], "frequence_achat_mois": 2, "premier_mois_achat": "2026-10"}}
    path.write_text(yaml.safe_dump(good, allow_unicode=True), encoding="utf-8")
    assert load_patrimoine_config(path)["profil"]["frequence_achat_mois"] == 2

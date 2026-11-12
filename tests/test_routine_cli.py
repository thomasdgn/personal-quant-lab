"""Routine mensuelle (run-month), état (status), patrimoine et DCA en CLI."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import main
from src.patrimoine import compute_allocation, generate_patrimoine_report, load_holdings, load_patrimoine_config
from src.routine import collect_status, decision_command, next_steps, previous_snapshot_path
from tests.conftest import FIXTURE_CONFIG

ROOT = Path(__file__).resolve().parents[1]

ASSETS_YAML = """universe:
  - {ticker: CW8.PA, name: W, category: monde, role: candidate, universe_active: true, notes: ''}
  - {ticker: ESE.PA, name: S, category: us, role: candidate, universe_active: true, notes: ''}
  - {ticker: CSH2.PA, name: M, category: monetaire, role: cash_proxy, universe_active: true, notes: ''}
"""


@pytest.fixture
def lab(tmp_path):
    """Mini-laboratoire : prix quotidiens synthétiques, univers, dossiers de sortie."""
    index = pd.bdate_range("2016-01-01", "2026-08-31")
    rng = np.random.default_rng(3)
    prices = pd.DataFrame({
        "CW8.PA": 100 * np.cumprod(1 + rng.normal(0.0004, 0.01, len(index))),
        "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.0003, 0.012, len(index))),
        "CSH2.PA": 100 * np.power(1.0001, np.arange(len(index))),
    }, index=index)
    prices.index.name = "Date"
    data = tmp_path / "prices.csv"
    prices.to_csv(data)
    assets = tmp_path / "assets.yaml"
    assets.write_text(ASSETS_YAML, encoding="utf-8")
    return {
        "root": tmp_path, "data": data, "assets": assets,
        "monthly": tmp_path / "monthly", "paper": tmp_path / "paper",
    }


def _run_month(lab, report_date):
    return main.main([
        "run-month", "--report-date", report_date, "--data", str(lab["data"]), "--assets", str(lab["assets"]),
        "--output-dir", str(lab["monthly"]), "--paper-dir", str(lab["paper"]),
    ])


@pytest.mark.slow
def test_run_month_creates_report_entry_and_comparison(lab, capsys):
    assert _run_month(lab, "2026-07-31") in (0, 2)
    assert _run_month(lab, "2026-08-31") in (0, 2)
    out = capsys.readouterr().out
    assert (lab["monthly"] / "2026-08-report.md").exists()
    entry = json.loads((lab["paper"] / "2026-08-paper-entry.json").read_text(encoding="utf-8"))
    assert entry["manual_decision_status"] == "PENDING"
    assert (lab["paper"] / "comparison-2026-07-2026-08.json").exists()
    assert "paper-decision --month 2026-08" in out
    assert "Performance paper" in out
    snapshot = json.loads((lab["monthly"] / "2026-08-report.json").read_text(encoding="utf-8"))
    assert snapshot["universe"]["cash_proxy"] == "CSH2.PA"


@pytest.mark.slow
def test_run_month_keeps_an_approved_entry(lab, capsys):
    _run_month(lab, "2026-08-31")
    assert main.main(["paper-decision", "--month", "2026-08", "--status", "APPROVED_PAPER",
                      "--strategy", "momentum_vt", "--paper-dir", str(lab["paper"])]) == 0
    _run_month(lab, "2026-08-31")
    entry = json.loads((lab["paper"] / "2026-08-paper-entry.json").read_text(encoding="utf-8"))
    assert entry["manual_decision_status"] == "APPROVED_PAPER"
    assert "déjà décidée" in capsys.readouterr().out


@pytest.mark.slow
def test_status_reports_pending_decisions(lab, capsys):
    _run_month(lab, "2026-08-31")
    assert main.main(["status", "--data", str(lab["data"]), "--assets", str(lab["assets"]),
                      "--monthly-dir", str(lab["monthly"]), "--paper-dir", str(lab["paper"])]) == 0
    out = capsys.readouterr().out
    assert "2026-08" in out and "Prochaines actions" in out


@pytest.mark.slow
def test_collect_status_and_next_steps(lab):
    _run_month(lab, "2026-08-31")
    status = collect_status(data_path=lab["data"], configured_tickers=["CW8.PA", "PAEEM.PA"],
                            monthly_dir=lab["monthly"], paper_dir=lab["paper"], today="2026-09-20")
    assert status["data"]["age_days"] == 20
    assert status["data"]["missing_tickers"] == ["PAEEM.PA"]
    assert status["journal"]["pending_months"] == ["2026-08"]
    assert not status["journal"]["rule_met"]
    steps = status["next_steps"]
    assert steps[0].endswith("run-month --refresh-data")
    assert any("2026-08" in step for step in steps)


def test_next_steps_when_everything_is_done():
    status = {
        "today": "2026-09-05",
        "data": {"exists": True, "age_days": 1, "missing_tickers": []},
        "last_report": {"report_month": "2026-09", "pipeline_status": "OK"},
        "journal": {"pending_months": []},
    }
    assert next_steps(status) == ["Rien à faire : routine du mois terminée."]


@pytest.mark.slow
def test_previous_snapshot_and_decision_command(lab):
    _run_month(lab, "2026-07-31")
    _run_month(lab, "2026-08-31")
    assert previous_snapshot_path(lab["monthly"], "2026-08").name == "2026-07-report.json"
    assert previous_snapshot_path(lab["monthly"], "2026-07") is None
    assert "--strategy momentum" in decision_command("2026-08", "momentum")


# --- patrimoine ---------------------------------------------------------------
def test_holdings_file_and_empty_values(tmp_path):
    config = load_patrimoine_config(FIXTURE_CONFIG / "patrimoine.yaml")
    assert load_holdings(tmp_path / "absent.yaml") == ({}, None)
    empty = compute_allocation({}, config)
    assert empty["empty"] and not empty["drift_detected"]
    holdings = tmp_path / "holdings.yaml"
    holdings.write_text("date: 2026-09-01\nvaleurs_eur:\n  pea: 1000\n  livret_a: 500\n", encoding="utf-8")
    values, as_of = load_holdings(holdings)
    assert values == {"pea": 1000.0, "livret_a": 500.0} and as_of == "2026-09-01"
    result = generate_patrimoine_report(config, {}, tmp_path / "r.md")
    assert "Aucune valeur renseignée" in result["recommendation"]
    text = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "Valeur réelle" in text and "Aucune valeur renseignée" in text


def test_holdings_rejects_non_numeric(tmp_path):
    holdings = tmp_path / "holdings.yaml"
    holdings.write_text("valeurs_eur:\n  pea: beaucoup\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_holdings(holdings)


def test_projection_real_value_uses_inflation():
    config = load_patrimoine_config(FIXTURE_CONFIG / "patrimoine.yaml")
    from src.patrimoine import compute_projection
    projection = compute_projection(1000, 0, 0, 10, inflation_pct=2.0,
                                    scenario_rates_pct={"pessimiste": 0, "central": 0, "optimiste": 0})
    assert projection["scenarios"]["central"]["valeur_finale_reelle_eur"] == pytest.approx(1000 / 1.02 ** 10)
    assert config["profil"]["inflation_pct"] == 2.0


def test_patrimoine_command(tmp_path, capsys):
    holdings = tmp_path / "holdings.yaml"
    holdings.write_text("valeurs_eur:\n  pea: 3000\n  livret_a: 1000\n", encoding="utf-8")
    output = tmp_path / "patrimoine.md"
    assert main.main(["patrimoine", "--transactions", "absent-transactions.csv", "--holdings", str(holdings), "--output", str(output)]) == 0
    assert output.exists() and "4,000.00" in capsys.readouterr().out


# --- DCA -----------------------------------------------------------------------
def test_dca_command(lab, capsys):
    output = lab["root"] / "dca.md"
    assert main.main(["dca", "--data", str(lab["data"]), "--assets", str(lab["assets"]),
                      "--monthly", "400", "--output", str(output)]) == 0
    assert output.exists()
    out = capsys.readouterr().out
    assert "400 €/mois" in out and "momentum_vt" in out


def test_regime_command_prints_current_regime_and_verdict(lab, monkeypatch, capsys):
    import src.market_regime as mr

    fake_study = {
        "evaluation": {}, "backtest": {},
        "walk_forward": {
            "current": {"signal_date": "2026-08-31", "probability_logistic": 0.62, "exposure_logistic": 1.0},
            "financial": {"verdict": {"ml_benchmark": {"useful": False, "reason": "Sharpe 0.5 vs 1.0"}}},
        },
    }
    monkeypatch.setattr(mr, "run_regime_study", lambda prices, monthly, config: fake_study)
    monkeypatch.setattr(mr, "generate_regime_report", lambda *args: None)
    assert main.main(["regime", "--data", str(lab["data"]), "--assets", str(lab["assets"]),
                      "--output", str(lab["root"] / "regime.md")]) == 0
    out = capsys.readouterr().out
    assert "62.0%" in out and "non retenu" in out


def test_usage_error_returns_1_not_critical_code(capsys):
    assert main.main(["run-month", "--unknown-option"]) == 1
    assert main.main(["--help"]) == 0


@pytest.mark.slow
def test_new_commands_output_is_console_safe(lab, capsys):
    # La console Windows (cp1252) doit pouvoir afficher toute la sortie des commandes.
    _run_month(lab, "2026-08-31")
    main.main(["status", "--data", str(lab["data"]), "--assets", str(lab["assets"]),
               "--monthly-dir", str(lab["monthly"]), "--paper-dir", str(lab["paper"])])
    main.main(["dca", "--data", str(lab["data"]), "--assets", str(lab["assets"]),
               "--output", str(lab["root"] / "dca.md")])
    capsys.readouterr().out.encode("cp1252")

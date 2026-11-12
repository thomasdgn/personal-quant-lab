from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from src.patrimoine import (
    compute_allocation,
    compute_projection,
    generate_patrimoine_report,
    load_patrimoine_config,
)


CONFIG_PATH = Path(__file__).resolve().parent / "fixtures" / "config" / "patrimoine.yaml"  # copie figée


@pytest.fixture
def config():
    return load_patrimoine_config(CONFIG_PATH)


def test_load_patrimoine_config_charges_file(config):
    assert config["profil"]["horizon_ans"] == 30
    assert config["enveloppes"][0]["id"] == "pea"


def test_load_patrimoine_config_missing_field_raises_value_error(tmp_path, config):
    del config["profil"]["horizon_ans"]
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="horizon_ans"):
        load_patrimoine_config(path)


def test_compute_allocation_calculates_current_distribution(config):
    result = compute_allocation({"pea": 800, "livret_a": 100, "ldds": 100}, config)
    assert result["total_eur"] == pytest.approx(1000)
    assert result["current_pct"] == pytest.approx({"actions": 80, "liquidites": 20, "mixte": 0})
    assert result["drift_pct"]["actions"] == pytest.approx(-20)


def test_compute_allocation_detects_drift_above_tolerance(config):
    result = compute_allocation({"pea": 900, "livret_a": 100}, config)
    assert result["drift_detected"] is True
    assert "actions" in result["drift_types"]


def test_compute_allocation_no_drift_at_exact_threshold(config):
    result = compute_allocation({"pea": 950, "livret_a": 50}, config)
    assert result["max_abs_drift_pct"] == pytest.approx(5)
    assert result["drift_detected"] is False


def test_compute_allocation_ignores_inactive_envelope(config):
    result = compute_allocation({"pea": 1000, "cto": 9000}, config)
    assert result["total_eur"] == pytest.approx(1000)
    assert result["current_pct"]["actions"] == pytest.approx(100)
    assert result["drift_detected"] is False


def test_compute_allocation_rejects_negative_value(config):
    with pytest.raises(ValueError, match="négative"):
        compute_allocation({"pea": -1}, config)


def test_compute_projection_central_scenario_matches_monthly_formula():
    result = compute_projection(1_000, 100, 7, 2)
    monthly_rate = 0.07 / 12
    months = 24
    expected = 1_000 * (1 + monthly_rate) ** months + 100 * (((1 + monthly_rate) ** months - 1) / monthly_rate)
    assert result["valeur_finale_eur"] == pytest.approx(expected)
    assert result["scenarios"]["central"]["valeur_finale_eur"] == pytest.approx(expected)


def test_compute_projection_returns_three_scenarios_and_zero_payment_is_valid():
    result = compute_projection(1_000, 0, 7, 1)
    assert set(result["scenarios"]) == {"pessimiste", "central", "optimiste"}
    assert result["scenarios"]["central"]["total_verse_eur"] == pytest.approx(1_000)


def test_compute_projection_rejects_zero_horizon():
    with pytest.raises(ValueError, match="horizon_ans"):
        compute_projection(0, 0, 7, 0)


def test_generate_patrimoine_report_creates_non_empty_file(tmp_path, config):
    output = tmp_path / "patrimoine_report.md"
    result = generate_patrimoine_report(config, {"pea": 1000, "livret_a": 0, "ldds": 0}, output)
    assert output.exists() and output.stat().st_size > 0
    assert "PEA" in output.read_text(encoding="utf-8")
    assert result["recommendation"]


def test_generate_patrimoine_report_is_idempotent(tmp_path, config):
    output = tmp_path / "patrimoine_report.md"
    values = {"pea": 1000, "livret_a": 0, "ldds": 0, "cto": 0, "assurance_vie": 0}
    first = generate_patrimoine_report(deepcopy(config), values, output)
    first_content = output.read_text(encoding="utf-8")
    second = generate_patrimoine_report(deepcopy(config), values, output)
    assert output.read_text(encoding="utf-8") == first_content
    assert second["allocation"] == first["allocation"]


def test_report_recommends_configuration_review_without_active_actions(tmp_path, config):
    for envelope in config["enveloppes"]:
        if envelope["type"] == "actions":
            envelope["actif"] = False
    result = generate_patrimoine_report(config, {"livret_a": 100}, tmp_path / "report.md")
    assert result["recommendation"] == "Aucune enveloppe actions active. Revoir la configuration."

"""Expositions / véhicules : choix sous budget, pas de double comptage, proxy synthétique."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import main
from src.contribution_plan import plan_contribution
from src.universe import load_universe
from src.vehicles import (
    choose_vehicle,
    map_target_to_vehicles,
    splice_history,
    tracking_stats,
    vehicles_by_exposure,
)

ROOT = Path(__file__).resolve().parents[1]
ASSETS = [
    {"ticker": "CW8.PA", "exposure": "msci_world", "vehicle_priority": 1},
    {"ticker": "WPEA.PA", "exposure": "msci_world", "vehicle_priority": 2, "proxy": "CW8.PA"},
    {"ticker": "PAASI.PA", "exposure": "pacific", "vehicle_priority": 1},
]
QUOTES = {"CW8.PA": 700.0, "WPEA.PA": 7.0, "PAASI.PA": 40.0}


def test_project_universe_exposures():
    assets = load_universe(ROOT / "config" / "assets.yaml")
    groups = vehicles_by_exposure(assets)
    assert groups["msci_world"] == ["CW8.PA", "WPEA.PA"]
    assert next(a for a in assets if a["ticker"] == "WPEA.PA")["proxy"] == "CW8.PA"


@pytest.mark.parametrize("field, value, message", [
    ("vehicle_priority", 0, "vehicle_priority"), ("exposure", "", "exposure"), ("proxy", "A.PA", "proxy"),
])
def test_invalid_vehicle_fields(tmp_path, field, value, message):
    path = tmp_path / "assets.yaml"
    path.write_text("universe:\n  - {ticker: A.PA, name: A, category: c, universe_active: true, notes: '', "
                    f"{field}: {value!r}}}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_universe(path)


def test_choose_vehicle_switches_only_when_preferred_is_unaffordable():
    groups = vehicles_by_exposure(ASSETS)
    assert choose_vehicle("msci_world", groups, QUOTES, 1000.0) == ("CW8.PA", None)
    vehicle, note = choose_vehicle("msci_world", groups, QUOTES, 400.0)
    assert vehicle == "WPEA.PA" and "dépasse le budget" in note
    assert choose_vehicle("msci_world", groups, {"CW8.PA": 700.0}, 400.0) == ("CW8.PA", None)


def test_mapping_counts_existing_vehicle_without_double_counting():
    # 1 CW8 détenue (700 €) + 400 € de budget ; cible 100 % MSCI World.
    weights, notes = map_target_to_vehicles({"CW8.PA": 1.0, "CASH": 0.0}, {"CW8.PA": 700.0}, QUOTES, ASSETS, 400.0)
    assert weights["CW8.PA"] == pytest.approx(700 / 1100)
    assert weights["WPEA.PA"] == pytest.approx(400 / 1100)
    assert sum(weights.values()) == pytest.approx(1.0)
    plan = plan_contribution({"CW8.PA": 1}, QUOTES, weights, contribution=400.0)
    assert plan["table"].loc["CW8.PA", "parts_a_acheter"] == 0
    assert plan["table"].loc["WPEA.PA", "parts_a_acheter"] == 57
    assert any("déjà détenu" in n for n in notes)


def test_mapping_keeps_cash_and_other_exposures():
    weights, _ = map_target_to_vehicles({"PAASI.PA": 0.4, "CASH": 0.6}, {}, QUOTES, ASSETS, 400.0)
    assert weights == pytest.approx({"PAASI.PA": 0.4, "CASH": 0.6})


def test_splice_history_is_continuous_and_flagged():
    index = pd.bdate_range("2020-01-01", periods=300)
    proxy = pd.Series(100 * np.cumprod(1 + np.full(300, 0.001)), index=index)
    vehicle = pd.Series(np.nan, index=index)
    vehicle.iloc[200:] = 10 * proxy.iloc[200:] / proxy.iloc[200]
    spliced, flag = splice_history(vehicle, proxy)
    assert flag.sum() == 200 and not flag.iloc[200:].any()
    assert spliced.pct_change().dropna().to_numpy() == pytest.approx(0.001)
    assert spliced.iloc[200] == pytest.approx(10.0)
    with pytest.raises(ValueError):
        splice_history(pd.Series(np.nan, index=index), proxy)


def test_tracking_stats():
    index = pd.bdate_range("2024-01-01", periods=60)
    proxy = pd.Series(np.linspace(100, 110, 60), index=index)
    stats = tracking_stats(proxy * 0.1, proxy)
    assert stats["tracking_difference"] == pytest.approx(0.0, abs=1e-12) and stats["correlation"] == pytest.approx(1.0)
    assert tracking_stats(proxy.iloc[:5], proxy)["tracking_difference"] is None


def test_cli_plan_switches_vehicle_and_vehicles_command(tmp_path, capsys):
    index = pd.bdate_range("2024-01-01", "2026-08-31")
    rng = np.random.default_rng(2)
    base = np.cumprod(1 + rng.normal(0.0004, 0.01, len(index)))
    prices = pd.DataFrame({"CW8.PA": 500 * base, "WPEA.PA": 5 * base}, index=index)
    prices.loc[prices.index < "2025-01-01", "WPEA.PA"] = np.nan
    data = tmp_path / "prices.csv"
    prices.rename_axis("Date").to_csv(data)
    paper = tmp_path / "paper"
    paper.mkdir()
    entry = {"schema_version": "1.0", "report_month": "2026-09", "signal_date": "2026-08-31",
             "manual_decision_status": "APPROVED_PAPER", "manual_selected_strategy": "benchmark",
             "target_weights": {"benchmark": {"CW8.PA": 1.0, "CASH": 0.0}}}
    (paper / "2026-09-paper-entry.json").write_text(json.dumps(entry), encoding="utf-8")
    assert main.main(["plan-contribution", "--transactions", "absent-transactions.csv", "--amount", "400", "--positions", str(tmp_path / "none.yaml"),
                      "--paper-dir", str(paper), "--data", str(data), "--output-dir", str(tmp_path / "plans")]) == 0
    out = capsys.readouterr().out
    assert "WPEA.PA" in out and "dépasse le budget" in out
    assert main.main(["plan-contribution", "--transactions", "absent-transactions.csv", "--amount", "400", "--no-vehicle-switch", "--positions",
                      str(tmp_path / "none.yaml"), "--paper-dir", str(paper), "--data", str(data),
                      "--output-dir", str(tmp_path / "plans")]) == 0
    assert "Aucun achat proposé" in capsys.readouterr().out

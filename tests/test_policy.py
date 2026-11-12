"""Politique d'investissement : chargement, contrôles, rapport 1.3 et journal."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import main
from src.monthly_pipeline import MonthlyPipelineConfig, PipelineValidationError, run_monthly_pipeline
from src.paper_trading import create_paper_entry_from_snapshot
from src.policy import InvestmentPolicy, load_policy, policy_checks
from src.reporting import generate_markdown_report, save_report_snapshot
from src.strategies import REGISTRY
from tests.conftest import FIXTURE_CONFIG

ROOT = Path(__file__).resolve().parents[1]


def _prices(with_bond=True):
    index = pd.date_range("2016-01-31", periods=90, freq="ME")
    rng = np.random.default_rng(9)
    frame = pd.DataFrame({"CW8.PA": 100 * np.cumprod(1 + rng.normal(0.008, 0.04, 90)),
                          "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.006, 0.05, 90)),
                          "OBLI.PA": 100 * np.cumprod(1 + rng.normal(0.002, 0.01, 90))}, index=index)
    return frame if with_bond else frame.drop(columns="OBLI.PA")


ROLES = {"CW8.PA": "candidate", "ESE.PA": "candidate", "OBLI.PA": "defensive"}


def _run(policy, prices=None, roles=ROLES):
    prices = _prices() if prices is None else prices
    return run_monthly_pipeline(prices, MonthlyPipelineConfig(), generation_time=prices.index[-1] + pd.Timedelta(days=1),
                                asset_roles=roles, policy=policy)


def test_default_and_project_policy():
    assert InvestmentPolicy().strategie_suivie == "momentum_vt"
    policy = load_policy(FIXTURE_CONFIG / "policy.yaml")
    assert policy.strategie_suivie == "momentum_vt" and policy.drawdown_max_accepte == 0.25
    # La politique réelle du projet (choix personnel) doit simplement être valide et cohérente.
    project = load_policy(ROOT / "config" / "policy.yaml")
    assert project.strategie_suivie in REGISTRY
    if project.strategie_suivie == "allocation_fixe":
        assert abs(sum(project.allocation_fixe.values()) - 1.0) < 1e-9
    assert load_policy(ROOT / "absent.yaml") == InvestmentPolicy()


@pytest.mark.parametrize("body, message", [
    ("strategie_suivie: magie\n", "strategie_suivie inconnue"),
    ("drawdown_max_accepte: 25\n", "drawdown_max_accepte"),
    ("coeur_satellite:\n  part_coeur: 1.5\n", "part_coeur"),
    ("coeur_satellite:\n  satellite: core_satellite\n", "satellite invalide"),
    ("reequilibrage: trimestriel\n", "reequilibrage"),
    ("strategy: momentum\n", "clé inconnue 'strategy'"),
])
def test_invalid_policy_messages(tmp_path, body, message):
    path = tmp_path / "policy.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=message) as exc:
        load_policy(path)
    assert str(path) in str(exc.value)


def test_pipeline_follows_core_satellite_policy_and_lists_registry():
    policy = InvestmentPolicy(strategie_suivie="core_satellite", part_coeur=0.7, satellite="momentum")
    report = _run(policy).report
    assert report.policy["followed"] == "core_satellite" and report.policy["core_weight"] == 0.7
    assert set(report.strategies) >= {"benchmark", "momentum", "momentum_vt", "inverse_vol", "static_80_20",
                                      "dual_momentum", "top3_trend", "core_satellite"}
    weights = report.policy["target_weights"]
    assert sum(weights.values()) == pytest.approx(1.0) and weights["CW8.PA"] >= 0.7 - 1e-9
    assert report.policy["drawdown_within_limit"] in (True, False)


def test_policy_requiring_bond_fails_clearly_without_bond():
    with pytest.raises(PipelineValidationError, match="static_60_40"):
        _run(InvestmentPolicy(strategie_suivie="static_60_40"), prices=_prices(with_bond=False),
             roles={"CW8.PA": "candidate", "ESE.PA": "candidate"})


def test_snapshot_markdown_and_paper_entry_follow_policy(tmp_path):
    result = _run(InvestmentPolicy(strategie_suivie="inverse_vol"))
    snapshot = json.loads(save_report_snapshot(result, tmp_path / "s.json").read_text(encoding="utf-8"))
    assert snapshot["schema_version"] == "1.4" and snapshot["policy"]["followed"] == "inverse_vol"
    assert snapshot["strategies"]["inverse_vol"]["target_weights"]
    text = generate_markdown_report(result, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "Stratégie suivie selon la politique" in text and "Inverse volatilité" in text
    assert "Toutes les stratégies du registre" in text and "**(suivie)**" in text
    entry = create_paper_entry_from_snapshot(snapshot, tmp_path / "s.json")
    assert entry["system_suggested_strategy"] == "inverse_vol"
    assert {"inverse_vol", "static_80_20", "core_satellite"} <= set(entry["available_strategies"])
    assert entry["target_weights"]["inverse_vol"] == snapshot["strategies"]["inverse_vol"]["target_weights"]


def test_legacy_snapshot_entry_unchanged():
    legacy = {"schema_version": "1.2", "metadata": {"report_month": "2026-08"}, "manual_decision": {},
              "volatility_targeted_strategy": {"enabled": True, "target_weights": {"A": 0.5, "CASH": 0.5}}}
    entry = create_paper_entry_from_snapshot(legacy, "x.json")
    assert entry["system_suggested_strategy"] == "momentum_vt"
    assert entry["available_strategies"] == ["benchmark", "momentum", "momentum_vt"]


def test_policy_checks_warn_on_drawdown_and_significance():
    research = {"strategies": [
        {"key": "momentum_vt", "label": "VT", "max_drawdown": -0.30, "sharpe_diff": -0.5,
         "sharpe_diff_low": -0.9, "sharpe_diff_high": -0.1},
        {"key": "inverse_vol", "label": "IV", "max_drawdown": -0.1, "sharpe_diff": 0.3,
         "sharpe_diff_low": 0.05, "sharpe_diff_high": 0.5},
    ]}
    checks = policy_checks(InvestmentPolicy(), research, None)
    levels = [c["level"] for c in checks]
    assert levels.count("WARNING") == 2 and any("IV" in c["message"] for c in checks)
    assert policy_checks(InvestmentPolicy(strategie_suivie="core_satellite"), research, None)[0]["level"] == "INFO"
    assert "research" in policy_checks(InvestmentPolicy(), None, None)[0]["message"]


def test_policy_command(tmp_path, capsys):
    policy = tmp_path / "policy.yaml"
    policy.write_text("strategie_suivie: benchmark\n", encoding="utf-8")
    assert main.main(["policy", "--policy", str(policy), "--research", str(tmp_path / "none.json"),
                      "--monthly-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Stratégie suivie    : benchmark" in out and "research" in out
    out.encode("cp1252")

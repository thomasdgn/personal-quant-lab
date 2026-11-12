"""Lab v7 : allocation fixe suivie par la politique, règle de krach, régularité des
versements, plan de versement aligné sur la politique, frais fixes regroupés."""

import json

import numpy as np
import pandas as pd
import pytest

import main
from app.data import crash_rule_view
from src.costs import FeeModel
from src.ledger import contribution_regularity
from src.monthly_pipeline import MonthlyPipelineConfig, run_monthly_pipeline
from src.plans import Hypotheses, PlanDef, Pocket, _fees
from src.policy import InvestmentPolicy, load_policy
from src.reporting import generate_markdown_report, save_report_snapshot

ROLES = {"CW8.PA": "candidate", "PAEEM.PA": "candidate", "OBLI.PA": "defensive"}


def _prices(crash=False):
    index = pd.date_range("2016-01-31", periods=100, freq="ME")
    rng = np.random.default_rng(3)
    world = 100 * np.cumprod(1 + rng.normal(0.008, 0.035, 100))
    em = 50 * np.cumprod(1 + rng.normal(0.006, 0.05, 100))
    if crash:  # krach de -45 % sur les derniers mois
        world[-6:] = world[-7] * np.linspace(0.9, 0.55, 6)
        em[-6:] = em[-7] * np.linspace(0.9, 0.55, 6)
    return pd.DataFrame({"CW8.PA": world, "PAEEM.PA": em,
                         "OBLI.PA": 10 * np.cumprod(1 + rng.normal(0.002, 0.01, 100))}, index=index)


def _policy(**changes):
    base = {"strategie_suivie": "allocation_fixe", "allocation_fixe": {"CW8.PA": 0.85, "PAEEM.PA": 0.15},
            "plan_suivi": "monde_emergents", "regle_krach": "Je ne vends rien et je continue mes versements.",
            "seuil_krach": 0.30}
    base.update(changes)
    return InvestmentPolicy(**base)


def test_policy_parsing_and_validation(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("strategie_suivie: allocation_fixe\nplan_suivi: monde_emergents\n"
                    "allocation_fixe:\n  CW8.PA: 0.85\n  PAEEM.PA: 0.15\n"
                    "regle_krach:\n  texte: Je ne vends rien.\n  seuil_baisse: 0.25\n", encoding="utf-8")
    policy = load_policy(path)
    assert policy.allocation_fixe == {"CW8.PA": 0.85, "PAEEM.PA": 0.15}
    assert policy.regle_krach == "Je ne vends rien." and policy.seuil_krach == 0.25
    with pytest.raises(ValueError, match="somme"):
        InvestmentPolicy(strategie_suivie="allocation_fixe", allocation_fixe={"CW8.PA": 0.5})
    with pytest.raises(ValueError, match="exige"):
        InvestmentPolicy(strategie_suivie="allocation_fixe")
    with pytest.raises(ValueError, match="seuil_baisse"):
        InvestmentPolicy(seuil_krach=1.5)
    path.write_text("regle_krach:\n  message: x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="regle_krach"):
        load_policy(path)


def test_pipeline_follows_fixed_allocation_and_crash_rule(tmp_path):
    prices = _prices()
    result = run_monthly_pipeline(prices, MonthlyPipelineConfig(), generation_time=prices.index[-1] + pd.Timedelta(days=1),
                                  asset_roles=ROLES, policy=_policy())
    report = result.report
    assert report.policy["followed"] == "allocation_fixe" and report.policy["plan"] == "monde_emergents"
    assert report.policy["target_weights"]["CW8.PA"] == pytest.approx(0.85)
    assert "85% CW8.PA" in report.strategies["allocation_fixe"]["label"]
    crash = report.policy["crash_rule"]
    assert crash["text"].startswith("Je ne vends rien") and not crash["triggered"]
    assert "CRASH_RULE" not in {a.code for a in report.alerts}
    markdown = generate_markdown_report(result, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "Ta règle de krach" in markdown and "non déclenchée" in markdown
    snapshot = json.loads(save_report_snapshot(result, tmp_path / "r.json").read_text(encoding="utf-8"))
    assert snapshot["schema_version"] == "1.4" and snapshot["policy"]["crash_rule"]["threshold"] == 0.30


def test_crash_rule_triggers_warning_alert():
    prices = _prices(crash=True)
    result = run_monthly_pipeline(prices, MonthlyPipelineConfig(), generation_time=prices.index[-1] + pd.Timedelta(days=1),
                                  asset_roles=ROLES, policy=_policy())
    crash = result.report.policy["crash_rule"]
    assert crash["triggered"] and crash["current_drawdown"] <= -0.30
    alert = next(a for a in result.report.alerts if a.code == "CRASH_RULE")
    assert alert.level == "WARNING" and "Je ne vends rien" in alert.message
    assert result.report.metadata["pipeline_status"] in ("OK_WITH_WARNINGS", "CRITICAL")


def test_contribution_regularity():
    transactions = pd.DataFrame({"date": pd.to_datetime(["2026-01-05", "2026-02-03", "2026-04-02", "2026-05-04"]),
                                 "type": ["VERSEMENT", "VERSEMENT", "VERSEMENT", "VERSEMENT"]})
    bench = pd.Series([100, 100, 85, 88, 95], index=pd.date_range("2026-01-31", periods=5, freq="ME"))
    reg = contribution_regularity(transactions, benchmark=bench, as_of="2026-05-20")
    assert reg["months"] == 5 and reg["months_paid"] == 4 and reg["missed"] == ["2026-03"]
    assert reg["current_streak"] == 2
    # mars (-15 %) et avril (-12 %) sont des mois de baisse > 10 % ; seul avril a été versé.
    assert reg["stress_months"] == 2 and reg["stress_months_paid"] == 1
    assert contribution_regularity(None) is None
    assert contribution_regularity(transactions.assign(type="ACHAT")) is None


def test_plan_contribution_uses_policy_allocation(tmp_path, capsys):
    index = pd.bdate_range("2025-01-01", "2026-08-31")
    rng = np.random.default_rng(5)
    base = np.cumprod(1 + rng.normal(0.0003, 0.01, len(index)))
    prices = pd.DataFrame({"CW8.PA": 500 * base, "WPEA.PA": 5 * base, "PAEEM.PA": 30 * base}, index=index)
    data = tmp_path / "prices.csv"
    prices.rename_axis("Date").to_csv(data)
    policy = tmp_path / "policy.yaml"
    policy.write_text("strategie_suivie: allocation_fixe\nallocation_fixe:\n  CW8.PA: 0.85\n  PAEEM.PA: 0.15\n",
                      encoding="utf-8")
    (tmp_path / "paper").mkdir()
    assert main.main(["plan-contribution", "--transactions", str(tmp_path / "none.csv"), "--amount", "400",
                      "--positions", str(tmp_path / "none.yaml"), "--paper-dir", str(tmp_path / "paper"),
                      "--data", str(data), "--output-dir", str(tmp_path / "plans"), "--policy", str(policy)]) == 0
    out = capsys.readouterr().out
    assert "allocation fixe de la politique" in out and "WPEA.PA" in out


def test_fixed_fees_are_grouped_for_small_lines():
    plan = PlanDef(id="p", nom="P", resume="", pour_qui="", temps="5min", complexite=1, horizon_min_ans=1,
                   zones=("monde",), poches=(Pocket("M", "pea", 1.0, "etf", {"CW8.PA": 0.85, "PAEEM.PA": 0.15}),),
                   routine=())
    flat = FeeModel(proportional=0.0, fixed_per_order=1.5)
    fee = _fees(plan, "pea", 150.0, flat, Hypotheses())
    # Monde : 63,75 € par ligne (< 75 € = 1,5 / 2 %) et émergents idem : achats regroupés, frais ≈ 2 %.
    assert fee == pytest.approx(150.0 * 0.02)
    assert _fees(plan, "pea", 1000.0, flat, Hypotheses()) == pytest.approx(3.0)  # deux ordres de 500 €


def test_dashboard_crash_rule_view(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text("regle_krach:\n  texte: Je ne vends rien.\n", encoding="utf-8")
    view = crash_rule_view(policy, monthly_dir=tmp_path)
    assert view["text"] == "Je ne vends rien." and view["threshold"] == 0.30 and not view["triggered"]
    policy.write_text("strategie_suivie: benchmark\n", encoding="utf-8")
    assert crash_rule_view(policy, monthly_dir=tmp_path) is None


def test_purchase_frequency_lowers_simulated_fixed_fees():
    plan = PlanDef(id="p", nom="P", resume="", pour_qui="", temps="5min", complexite=1, horizon_min_ans=1,
                   zones=("monde",), poches=(Pocket("M", "pea", 1.0, "etf", {"WPEA.PA": 1.0}),), routine=())
    flat = FeeModel(proportional=0.0, fixed_per_order=1.99)
    monthly = _fees(plan, "pea", 150.0, flat, Hypotheses())
    every_two = _fees(plan, "pea", 150.0, flat, Hypotheses(frequence_achat_mois=2))
    assert monthly == pytest.approx(1.99) and every_two == pytest.approx(1.99 / 2)


def test_plan_contribution_cli_waiting_month(tmp_path, capsys):
    index = pd.bdate_range("2025-01-01", "2026-08-31")
    prices = pd.DataFrame({"CW8.PA": 500.0, "WPEA.PA": 5.0, "PAEEM.PA": 30.0}, index=index)
    data = tmp_path / "prices.csv"
    prices.rename_axis("Date").to_csv(data)
    policy = tmp_path / "policy.yaml"
    policy.write_text("strategie_suivie: allocation_fixe\nallocation_fixe:\n  CW8.PA: 0.85\n  PAEEM.PA: 0.15\n",
                      encoding="utf-8")
    common = ["plan-contribution", "--transactions", str(tmp_path / "none.csv"), "--amount", "150",
              "--positions", str(tmp_path / "none.yaml"), "--paper-dir", str(tmp_path), "--data", str(data),
              "--output-dir", str(tmp_path / "plans"), "--policy", str(policy), "--frequency", "2"]
    assert main.main([*common, "--month", "2026-10"]) == 0
    out = capsys.readouterr().out
    assert "prochain achat en 2026-11" in out and "ACHETER" not in out
    assert (tmp_path / "plans" / "2026-10-plan.md").exists()
    assert main.main([*common, "--month", "2026-11"]) == 0
    assert "ACHETER" in capsys.readouterr().out

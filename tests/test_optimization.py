"""Audit des frais et étude « rendement maximal » (hors-ligne, déterministe)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import main
from src.costs import FeeModel
from src.fee_audit import fee_audit, fee_audit_lines, future_value, order_schedule
from src.investor_profile import profile_from_dict
from src.max_return import (
    add_leveraged,
    conclusion_lines,
    default_options,
    generate_max_return_report,
    neutralize_equities,
    run_max_return_study,
)
from src.monthly_pipeline import MonthlyPipelineConfig
from src.plans import HISTORICAL, Hypotheses, Scenario
from src.strategies import StrategyContext
from src.taxes import TaxConfig

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = {"WPEA.PA": 0.85, "PAEEM.PA": 0.15}
QUOTES = {"WPEA.PA": 7.0, "PAEEM.PA": 37.0}


def test_order_schedule_groups_small_orders_with_flat_fees():
    free = order_schedule(WEIGHTS, QUOTES, 150.0, FeeModel(proportional=0.0), months=24)
    flat = order_schedule(WEIGHTS, QUOTES, 150.0, FeeModel(proportional=0.0, fixed_per_order=1.99), months=24)
    assert free["fees_per_year"] == 0.0
    assert flat["orders_per_year"] < free["orders_per_year"]  # émergents regroupés
    assert flat["fees_per_year"] == pytest.approx(flat["orders_per_year"] * 1.99)
    assert 0 < flat["fee_rate"] < 0.02


def test_future_value_and_audit():
    assert future_value(100.0, 0.0, 12) == pytest.approx(1200.0)
    assert future_value(100.0, 0.06, 12) > 1200.0
    audit = fee_audit(WEIGHTS, QUOTES, monthly=150.0, capital=500.0, horizon_years=15, annual_return=0.06,
                      fee_models={"Mon courtier": FeeModel(proportional=0.0, fixed_per_order=1.99),
                                  "Gratuit": FeeModel(proportional=0.0)},
                      current="Mon courtier", ter_pct={"WPEA.PA": 0.20, "PAEEM.PA": 0.30, "CW8.PA": 0.38},
                      ter_alternatives={"CW8": {"CW8.PA": 0.85, "PAEEM.PA": 0.15}}, taxes=TaxConfig())
    assert audit["cheapest"] == "Gratuit" and audit["saving_vs_cheapest"] > 0
    assert audit["ter"]["Ton allocation"]["ter_pct"] == pytest.approx(0.215)
    assert audit["ter"]["CW8"]["value_lost"] > audit["ter"]["Ton allocation"]["value_lost"] > 0
    assert audit["taxes"]["saving"] == pytest.approx(audit["projection"]["gain"] * (31.4 - 18.6) / 100)
    assert any("Fiscalité" in line for line in fee_audit_lines(audit))


def _monthly(n=240):
    index = pd.date_range("2005-01-31", periods=n, freq="ME")
    rng = np.random.default_rng(12)
    spec = {"CW8.PA": (0.007, 0.045), "PAEEM.PA": (0.006, 0.06), "ESE.PA": (0.008, 0.05),
            "PUST.PA": (0.011, 0.06), "OBLI.PA": (0.002, 0.012)}
    return pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(m, s, n)) for t, (m, s) in spec.items()}, index=index)


ROLES = {"CW8.PA": "candidate", "PAEEM.PA": "candidate", "ESE.PA": "candidate", "PUST.PA": "candidate",
         "OBLI.PA": "defensive"}


def test_leverage_and_neutralization():
    monthly = _monthly()
    lev = add_leveraged(monthly, ["CW8.PA"], financing_pct=1.2, ter_pct=0.6)
    r, r2 = monthly["CW8.PA"].pct_change().dropna(), lev["LEV2:CW8.PA"].pct_change().dropna()
    assert r2.to_numpy() == pytest.approx((2 * r - 1.2 / 100 / 12 - 0.6 / 100 / 12).to_numpy())
    neutral = neutralize_equities(monthly, ROLES, "CW8.PA")
    logs = np.log1p(neutral.pct_change()).dropna()
    sharpe = logs.mean() / logs.std()
    assert sharpe["PUST.PA"] == pytest.approx(sharpe["CW8.PA"]) and sharpe["ESE.PA"] == pytest.approx(sharpe["CW8.PA"])
    pd.testing.assert_series_equal(neutral["OBLI.PA"], monthly["OBLI.PA"])  # défensif inchangé


def test_max_return_study_and_report(tmp_path):
    raw = {"capital_initial_eur": 500, "versement_mensuel_eur": 150, "objectif": "independance", "horizon_ans": 10,
           "reaction_baisse": "acheter_plus", "temps_mensuel": "hobby", "zones": ["monde"], "experience": "debutant"}
    profile = profile_from_dict(raw)
    ctx = StrategyContext(config=MonthlyPipelineConfig(), equities=("CW8.PA", "PAEEM.PA", "ESE.PA", "PUST.PA"),
                          bond="OBLI.PA")
    scenarios = {"historique": HISTORICAL,
                 "central": Scenario("central", "Central", 6.0, 2.5, surperformance="nulle")}
    study = run_max_return_study(default_options({"CW8.PA": 0.85, "PAEEM.PA": 0.15}), _monthly(), roles=ROLES,
                                 ctx=ctx, transaction_cost=0.001, scenarios=scenarios, profile=profile,
                                 hyp=Hypotheses(simulations=100), taxes=TaxConfig(),
                                 fee_model=FeeModel(proportional=0.0), n_sims=100)
    central = study["scenarios"]["central"]["rows"]
    assert set(central) == {"ton_plan", "monde", "sp500", "nasdaq", "momentum", "levier_monde", "levier_nasdaq"}
    for row in central.values():
        assert row["p10"] <= row["p50"] <= row["p90"] and 0 <= row["prob_ruin"] <= 1
    assert central["levier_monde"]["prob_ruin"] > central["monde"]["prob_ruin"]
    assert central["levier_monde"]["p90"] > central["monde"]["p90"]
    assert central["levier_monde"]["drawdown_median"] < central["monde"]["drawdown_median"]
    assert study["history"]["levier_nasdaq"]["max_drawdown"] < study["history"]["nasdaq"]["max_drawdown"]
    assert any("risquée" in line for line in conclusion_lines(study))
    text = generate_max_return_report(study, tmp_path / "plans" / "rm.md").read_text(encoding="utf-8")
    assert "Scénario Central" in text and "bulle internet" in text and "pédagogique" in text
    assert (tmp_path / "plans" / "figures" / "rendement_max.png").exists()


def test_fee_cli_offline(tmp_path, capsys):
    index = pd.bdate_range("2025-01-01", "2026-08-31")
    prices = pd.DataFrame({"CW8.PA": 700.0, "WPEA.PA": 7.0, "PAEEM.PA": 37.0}, index=index)
    data = tmp_path / "prices.csv"
    prices.rename_axis("Date").to_csv(data)
    policy = tmp_path / "policy.yaml"
    policy.write_text("strategie_suivie: allocation_fixe\nallocation_fixe:\n  CW8.PA: 0.85\n  PAEEM.PA: 0.15\n",
                      encoding="utf-8")
    out = tmp_path / "frais.md"
    assert main.main(["frais", "--profile", str(ROOT / "config" / "profil.example.yaml"), "--policy", str(policy),
                      "--data", str(data), "--output", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Frais d'ordre" in printed and "EUR" in printed
    report = out.read_text(encoding="utf-8")
    assert "Frais annuels des ETF" in report and "WPEA.PA" in report

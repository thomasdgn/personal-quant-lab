"""Résumé du mois en HTML autonome et pages v4 du tableau de bord (helpers)."""

import json

import numpy as np
import pandas as pd
import pytest

import main
from app.data import load_stress, policy_view, real_portfolio
from src.month_summary import build_month_summary, write_month_summary

SNAPSHOT = {
    "metadata": {"report_month": "2026-09", "pipeline_status": "OK_WITH_WARNINGS", "signal_date": "2026-08-31",
                 "last_observation": "2026-09-23"},
    "policy": {"label": "Momentum + VT", "max_drawdown_limit": 0.25, "target_weights": {"PAASI.PA": 0.42, "CASH": 0.58}},
    "alerts": [{"level": "WARNING", "message": "Volatilité élevée"}, {"level": "INFO", "message": "Mois partiel"}],
}


def test_summary_contains_policy_alerts_plan_and_portfolio(tmp_path):
    plan = tmp_path / "2026-09-plan.md"
    plan.write_text("# Plan\n\n## Achats proposés (parts entières, sans vente)\n\n| Ticker |\n| --- |\n| WPEA.PA |\n\n"
                    "## Remarques\n\n- x\n", encoding="utf-8")
    portfolio = {"perf": {"final_value": 800.0, "net_contributions": 790.0, "mwr": 0.05, "fees_total": 1.2,
                          "comparison": {"real_twr": 0.01}}, "pea": {"alerts": ["PEA de moins de 5 ans"]}}
    text = build_month_summary(SNAPSHOT, plan_path=plan, paper_lines=["Mes décisions +1 %"], portfolio=portfolio)
    assert "PAASI.PA | 42.0%" in text and "1 importantes, 1 informatives" in text
    assert "WPEA.PA" in text and "Remarques" not in text
    assert "TRI annualisé 5.0%" in text and "PEA de moins de 5 ans" in text
    old_plan = tmp_path / "2026-08-plan.md"
    old_plan.write_text("x", encoding="utf-8")
    assert "Aucun plan pour ce mois" in build_month_summary(SNAPSHOT, plan_path=old_plan)
    html = write_month_summary(SNAPSHOT, tmp_path / "resume.html").read_text(encoding="utf-8")
    assert "<title>Résumé du mois 2026-09</title>" in html and 'name="viewport"' in html
    assert not list(tmp_path.glob("resume.md"))  # Markdown intermédiaire jamais laissé sur disque


def test_dashboard_v4_helpers(tmp_path):
    view = policy_view(research_path=tmp_path / "none.json", monthly_dir=tmp_path)
    assert view["policy"].strategie_suivie and view["snapshot"] is None
    data = real_portfolio(transactions_path=tmp_path / "none.csv")
    assert data["perf"] is None and not data["has_transactions"] and data["pea"]["alerts"]
    assert load_stress(tmp_path / "none.json") is None


@pytest.mark.slow
def test_run_month_html_writes_month_summary(tmp_path, capsys):
    index = pd.bdate_range("2016-01-01", "2026-08-31")
    rng = np.random.default_rng(3)
    prices = pd.DataFrame({"CW8.PA": 100 * np.cumprod(1 + rng.normal(0.0004, 0.01, len(index))),
                           "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.0003, 0.012, len(index)))}, index=index)
    data = tmp_path / "prices.csv"
    prices.rename_axis("Date").to_csv(data)
    assets = tmp_path / "assets.yaml"
    assets.write_text("universe:\n  - {ticker: CW8.PA, name: W, category: m, universe_active: true, notes: ''}\n"
                      "  - {ticker: ESE.PA, name: S, category: u, universe_active: true, notes: ''}\n", encoding="utf-8")
    monthly = tmp_path / "reports" / "monthly"
    code = main.main(["run-month", "--report-date", "2026-08-31", "--html", "--data", str(data), "--assets", str(assets),
                      "--output-dir", str(monthly), "--paper-dir", str(tmp_path / "paper"),
                      "--transactions", str(tmp_path / "none.csv")])
    assert code in (0, 2)
    summary = monthly / "2026-08-resume.html"
    assert summary.exists() and "Allocation proposée" in summary.read_text(encoding="utf-8")
    assert (monthly / "2026-08-report.html").exists()
    snapshot = json.loads((monthly / "2026-08-report.json").read_text(encoding="utf-8"))
    assert snapshot["policy"]["followed"] == "momentum_vt"
    assert "Résumé du mois" in capsys.readouterr().out

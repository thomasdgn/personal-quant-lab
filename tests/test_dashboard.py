"""Tableau de bord : helpers de lecture et rendu Streamlit sans erreur."""

import json
from pathlib import Path

import pytest

from app.data import (
    alerts_table,
    figure_paths,
    journal_table,
    load_snapshots,
    patrimoine_summary,
    snapshot_history,
    target_allocation,
)
from tests.conftest import FIXTURE_CONFIG

ROOT = Path(__file__).resolve().parents[1]
MONTHLY = ROOT / "reports" / "monthly"


def test_helpers_read_committed_reports():
    snapshots = load_snapshots(MONTHLY)
    assert snapshots, "des rapports mensuels versionnés sont attendus"
    history = snapshot_history(snapshots)
    assert list(history["mois"]) == sorted(history["mois"])
    path, latest = snapshots[-1]
    allocation = target_allocation(latest)
    assert abs(allocation["poids"].sum() - 1.0) < 1e-6
    assert set(alerts_table(latest).columns) >= {"niveau", "code", "message"}
    assert all(p.exists() for p in figure_paths(latest, path).values())


def test_helpers_are_robust_to_legacy_snapshot(tmp_path):
    legacy = {"schema_version": "1.0", "metadata": {"report_month": "2026-01"}, "manual_decision": {},
              "volatility_targeted_strategy": {"enabled": False},
              "momentum_strategy": {"target_weights": {"CW8.PA": 1.0, "CASH": 0.0}, "selected_assets": ["CW8.PA"]}}
    assert target_allocation(legacy)["actif"].tolist() == ["CW8.PA"]
    assert figure_paths(legacy, tmp_path / "2026-01-report.json") == {}
    assert alerts_table(legacy).empty


def test_journal_and_patrimoine(tmp_path):
    entry = {"schema_version": "1.0", "report_month": "2026-09", "manual_decision_status": "PENDING"}
    (tmp_path / "2026-09-paper-entry.json").write_text(json.dumps(entry), encoding="utf-8")
    assert journal_table(tmp_path)["décision"].tolist() == ["PENDING"]
    summary = patrimoine_summary(FIXTURE_CONFIG / "patrimoine.yaml", tmp_path / "absent.yaml")
    assert summary["allocation"]["empty"]


PAGES = ["home.py", "month.py", "history.py", "performance.py", "plan.py", "research.py", "journal.py",
         "patrimoine.py", "policy.py", "portfolio.py", "stress.py", "profile.py", "plans.py", "strategies.py",
         "robustness.py", "optimization.py", "pea.py"]


@pytest.mark.slow
def test_dashboard_renders_every_page_without_exception():
    testing = pytest.importorskip("streamlit.testing.v1")
    app = testing.AppTest.from_file(str(ROOT / "app" / "dashboard.py"), default_timeout=90)
    app.run()
    assert not app.exception
    assert any("Accueil" in element.value for element in app.title)  # page d'accueil par défaut
    for page in PAGES[1:]:
        app.switch_page(f"app_pages/{page}")
        app.run()
        assert not app.exception, page
        assert app.title, page  # chaque page a son en-tête
    app.switch_page("app_pages/month.py")
    app.run()
    assert any("Rapport" in element.value for element in app.title)


def test_series_helpers_and_research_and_plan(tmp_path):
    from app.data import latest_plan, load_research, long_series, series_frame

    snapshot = {"series": [
        {"date": "2026-07-31", "benchmark_equity": 100.0, "momentum_equity": 101.0, "benchmark_drawdown": 0.0,
         "momentum_drawdown": -0.01, "exposure": 1.0, "held": "ESE.PA"},
        {"date": "2026-08-31", "benchmark_equity": 102.0, "momentum_equity": 103.0, "benchmark_drawdown": 0.0,
         "momentum_drawdown": 0.0, "exposure": 0.5, "held": "ESE.PA"},
    ]}
    frame = series_frame(snapshot)
    assert list(frame.index.strftime("%Y-%m")) == ["2026-07", "2026-08"]
    equity = long_series(frame, "equity")
    assert set(equity["stratégie"]) == {"Buy & Hold", "Momentum"} and len(equity) == 4
    assert series_frame({}).empty
    assert load_research(tmp_path / "absent.json") is None
    assert latest_plan(tmp_path) is None
    (tmp_path / "2026-08-plan.md").write_text("a", encoding="utf-8")
    (tmp_path / "2026-09-plan.md").write_text("b", encoding="utf-8")
    assert latest_plan(tmp_path).name == "2026-09-plan.md"


def test_ui_charts_and_profile_fallback():
    import pandas as pd

    from app import ui
    from app.planning import load_profile_or_example

    fan = {"months": [0, 12, 24], "contributed": [0, 1200, 2400], "contributed_real": [0, 1180, 2320],
           "real": {f"p{q}": [0, 1000 + q, 2000 + 2 * q] for q in (5, 10, 25, 50, 75, 90, 95)},
           "nominal": {f"p{q}": [0, 1000 + q, 2000 + 2 * q] for q in (5, 10, 25, 50, 75, 90, 95)}}
    assert ui.fan_chart(fan, goal=3000).to_dict()["layer"]
    frame = pd.DataFrame({"plan": ["A", "B"], "bas": [1, 2], "mid": [2, 3], "haut": [3, 4],
                          "adéquation": ["adapté", "peu adapté"]})
    spec = ui.range_chart(frame, label="plan", low="bas", mid="mid", high="haut", color="adéquation",
                          reference=2.5).to_dict()
    assert spec["layer"][0]["encoding"]["color"]["scale"]["range"] == ["#16a34a", "#dc2626"]
    assert ui.eur(1234.5) == "1 234 €" and ui.pct(None) == "n/a" and ui.pct(0.123, 1) == "12.3%"
    profile, is_example = load_profile_or_example()
    assert profile.horizon_ans >= 1 and isinstance(is_example, bool)

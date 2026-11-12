from pathlib import Path

import pandas as pd

from src.universe import (
    generate_validation_report,
    load_universe,
    validate_universe,
)


def _asset(ticker="TEST.PA", *, active=True):
    return {
        "ticker": ticker,
        "name": "ETF de test",
        "category": "monde",
        "universe_active": active,
        "notes": "",
    }


def _history(first_date: str, last_date: str) -> pd.DataFrame:
    index = pd.to_datetime([first_date, last_date])
    return pd.DataFrame({"Close": [100.0, 110.0]}, index=index)


def test_load_universe_returns_only_active_assets(tmp_path):
    path = tmp_path / "assets.yaml"
    path.write_text(
        """universe:
  - ticker: CW8.PA
    name: MSCI World
    category: monde
    universe_active: true
    notes: ""
  - ticker: GOVF.PA
    name: EuroMTS All-Maturity
    category: obligations_souveraines
    universe_active: false
    notes: UNAVAILABLE
""",
        encoding="utf-8",
    )

    assets = load_universe(path)

    assert [asset["ticker"] for asset in assets] == ["CW8.PA"]


def test_project_universe_contains_thirteen_assets_and_ten_active():
    config_path = Path(__file__).parents[1] / "config" / "assets.yaml"

    all_assets = load_universe(config_path, include_inactive=True)
    active_assets = load_universe(config_path)

    # 2026-09-23 : PSP5.PA (vrai S&P 500 PEA) ajouté inactif ; l'univers actif est inchangé.
    assert len(all_assets) == 13
    assert len(active_assets) == 10
    assert {asset["ticker"] for asset in all_assets if not asset["universe_active"]} == {
        "GOVF.PA",
        "CRPE.PA",
        "PSP5.PA",
    }


def test_validate_universe_sufficient_history_has_no_short_flag(monkeypatch):
    monkeypatch.setattr(
        "src.universe.yf.download",
        lambda **kwargs: _history("2020-01-02", "2026-08-03"),
    )

    result = validate_universe([_asset()], "2015-01-01", "2026-08-03")[0]

    assert result["universe_active"] is True
    assert result["first_date"] == "2020-01-02"
    assert result["history_months"] == 80
    assert "SHORT_HISTORY" not in result["flags"]


def test_validate_universe_short_history_sets_flag(monkeypatch):
    monkeypatch.setattr(
        "src.universe.yf.download",
        lambda **kwargs: _history("2024-04-02", "2026-08-03"),
    )

    result = validate_universe([_asset()], "2015-01-01", "2026-08-03")[0]

    assert result["universe_active"] is True
    assert result["history_months"] == 29
    assert result["flags"] == ["SHORT_HISTORY"]


def test_validate_universe_empty_download_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        "src.universe.yf.download",
        lambda **kwargs: pd.DataFrame(),
    )

    result = validate_universe([_asset()], "2015-01-01", "2026-08-03")[0]

    assert result["universe_active"] is False
    assert result["first_date"] is None
    assert result["history_months"] is None
    assert result["flags"] == ["UNAVAILABLE"]


def test_validate_universe_download_exception_is_unavailable(monkeypatch):
    def raise_download_error(**kwargs):
        raise RuntimeError("service indisponible")

    monkeypatch.setattr("src.universe.yf.download", raise_download_error)

    result = validate_universe([_asset()], "2015-01-01", "2026-08-03")[0]

    assert result["universe_active"] is False
    assert result["flags"] == ["UNAVAILABLE"]
    assert "RuntimeError" in result["notes"]


def test_generate_validation_report_is_non_empty(tmp_path):
    result = {
        **_asset("CW8.PA"),
        "first_date": "2015-01-02",
        "last_date": "2026-08-03",
        "history_months": 140,
        "flags": [],
    }
    path = tmp_path / "reports" / "universe_validation_report.md"

    generate_validation_report([result], path)

    content = path.read_text(encoding="utf-8")
    assert path.stat().st_size > 0
    assert "| CW8.PA |" in content
    assert "Mois d'historique" in content


def test_generate_validation_report_is_idempotent(tmp_path):
    result = {
        **_asset("WPEA.PA"),
        "first_date": "2024-04-02",
        "last_date": "2026-08-03",
        "history_months": 29,
        "flags": ["SHORT_HISTORY"],
    }
    path = tmp_path / "universe.md"

    generate_validation_report([result], path)
    first_content = path.read_text(encoding="utf-8")
    generate_validation_report([result], path)

    assert path.read_text(encoding="utf-8") == first_content

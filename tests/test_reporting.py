import json

import numpy as np
import pandas as pd
import pytest

import main as cli
from src.monthly_pipeline import MonthlyPipelineConfig, run_monthly_pipeline
from src.reporting import generate_markdown_report, load_previous_snapshot, save_report_snapshot

CONFIG_PATH = "config/strategy_params.yaml"


def _synthetic_prices(n_months=80, seed=3):
    index = pd.date_range("2016-01-31", periods=n_months, freq="ME")
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "CW8.PA": 100 * np.cumprod(1 + rng.normal(0.008, 0.04, n_months)),
        "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.006, 0.05, n_months)),
    }, index=index)


@pytest.fixture
def result():
    prices = _synthetic_prices()
    config = MonthlyPipelineConfig()
    return run_monthly_pipeline(prices, config, generation_time=prices.index.max() + pd.Timedelta(days=1))


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def test_markdown_file_created_with_required_sections(result, tmp_path):
    path = generate_markdown_report(result, tmp_path / "2026-07-report.md")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    for section in ("# Rapport mensuel", "## Qualité des données", "## Benchmark",
                    "## Stratégie Momentum", "## Comparaison des allocations",
                    "## Risque", "## Alertes", "## Décision manuelle", "## Limites"):
        assert section in text


def test_markdown_has_educational_warning_and_pending_decision(result, tmp_path):
    text = generate_markdown_report(result, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "éducatives et de paper trading" in text
    assert "Décision : À renseigner" in text


def test_markdown_formats_weights_as_percent(result, tmp_path):
    import re
    text = generate_markdown_report(result, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "%" in text
    # Pas de "nan" isolé (valeur NaN mal formatée) ; "finance" ne doit pas matcher.
    assert re.search(r"\bnan\b", text.lower()) is None


def test_markdown_has_no_order_language(result, tmp_path):
    text = generate_markdown_report(result, tmp_path / "r.md").read_text(encoding="utf-8").lower()
    for word in ("achetez", "vendez", "ordre à exécuter"):
        assert word not in text


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #
def test_json_is_valid_and_versioned(result, tmp_path):
    path = save_report_snapshot(result, tmp_path / "2026-07-report.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"]
    for key in ("metadata", "data_quality", "universe", "benchmark", "momentum_strategy",
                "volatility_targeted_strategy", "allocation_comparison", "risk", "alerts",
                "manual_decision"):
        assert key in data


def test_json_has_no_nan_or_infinity(result, tmp_path):
    path = save_report_snapshot(result, tmp_path / "r.json")
    raw = path.read_text(encoding="utf-8")
    assert "NaN" not in raw and "Infinity" not in raw


def test_json_manual_decision_pending(result, tmp_path):
    data = json.loads(save_report_snapshot(result, tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["manual_decision"]["status"] == "PENDING"
    assert data["manual_decision"]["approved_weights"] is None


def test_json_weights_are_numeric_and_dates_iso(result, tmp_path):
    data = json.loads(save_report_snapshot(result, tmp_path / "r.json").read_text(encoding="utf-8"))
    for weight in data["volatility_targeted_strategy"]["target_weights"].values():
        assert isinstance(weight, (int, float))
    # Dates ISO (YYYY-MM-DD).
    pd.Timestamp(data["metadata"]["signal_date"])
    assert len(data["metadata"]["signal_date"]) == 10


def test_json_roundtrip(result, tmp_path):
    path = save_report_snapshot(result, tmp_path / "r.json")
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["metadata"]["schema_version"] == result.report.metadata["schema_version"]


def test_json_includes_temporal_fields(result, tmp_path):
    data = json.loads(save_report_snapshot(result, tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["partial_month"] == result.report.data_quality["partial_month"]
    assert data["freshness_reference"] == result.report.metadata["freshness_reference"]


def test_load_previous_snapshot(result, tmp_path):
    save_report_snapshot(result, tmp_path / "2026-06-report.json")
    prev = load_previous_snapshot(tmp_path, "2026-07")
    assert prev is not None
    assert load_previous_snapshot(tmp_path, "2026-01") is None  # aucun antérieur


def test_load_previous_snapshot_defaults_missing_temporal_fields(tmp_path):
    old_snapshot = {
        "schema_version": "1.0",
        "metadata": {"report_month": "2026-06"},
    }
    path = tmp_path / "2026-06-report.json"
    path.write_text(json.dumps(old_snapshot), encoding="utf-8")
    loaded = load_previous_snapshot(tmp_path, "2026-07")
    assert loaded["partial_month"] is None
    assert loaded["freshness_reference"] is None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _write_local_data(tmp_path):
    # Données quotidiennes se terminant aujourd'hui : un rapport courant (sans
    # report_date) est alors « frais » et ne déclenche pas d'alerte STALE_DATA
    # critique. Déterministe et sans Internet (seul l'ancrage temporel suit
    # l'horloge, ce qui n'affecte pas les assertions de code de sortie).
    end = pd.Timestamp.now().normalize()
    index = pd.bdate_range(end=end, periods=2800)  # ~11 ans de séances ouvrées
    rng = np.random.default_rng(3)
    prices = pd.DataFrame({
        "CW8.PA": 100 * np.cumprod(1 + rng.normal(0.0004, 0.01, len(index))),
        "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.0003, 0.012, len(index))),
    }, index=index)
    data_path = tmp_path / "prices.csv"
    prices.to_csv(data_path)
    return data_path


@pytest.mark.slow
def test_cli_generates_reports_offline(tmp_path):
    data_path = _write_local_data(tmp_path)
    out_dir = tmp_path / "out"
    code = cli.main(["monthly-report", "--config", CONFIG_PATH,
                     "--data", str(data_path), "--output-dir", str(out_dir)])
    assert code == 0
    md = list(out_dir.glob("*-report.md"))
    js = list(out_dir.glob("*-report.json"))
    assert len(md) == 1 and len(js) == 1
    json.loads(js[0].read_text(encoding="utf-8"))  # JSON valide


def test_cli_missing_local_data_without_refresh_errors(tmp_path):
    code = cli.main(["monthly-report", "--config", CONFIG_PATH,
                     "--data", str(tmp_path / "absent.csv"), "--output-dir", str(tmp_path / "o")])
    assert code == 1  # pas de téléchargement silencieux


def test_cli_validate_command():
    assert cli.main(["validate", "--config", CONFIG_PATH]) == 0


@pytest.mark.slow
def test_cli_parser_accepts_report_date(tmp_path):
    data_path = _write_local_data(tmp_path)
    out_dir = tmp_path / "out"
    code = cli.main(["monthly-report", "--config", CONFIG_PATH, "--data", str(data_path),
                     "--output-dir", str(out_dir), "--report-date", "2021-06-30"])
    assert code == 0
    data = json.loads(next(out_dir.glob("*-report.json")).read_text(encoding="utf-8"))
    assert data["metadata"]["report_date"] == "2021-06-30"


# --------------------------------------------------------------------------- #
# Constat 1 : Markdown et JSON publient les mêmes dates (tronquées)
# --------------------------------------------------------------------------- #
def test_markdown_and_json_dates_consistent(tmp_path):
    prices = _synthetic_prices()
    config = MonthlyPipelineConfig()
    cutoff = prices.index[-13]
    result = run_monthly_pipeline(prices, config, report_date=cutoff,
                                  generation_time=cutoff + pd.Timedelta(days=1))
    md = generate_markdown_report(result, tmp_path / "r.md").read_text(encoding="utf-8")
    data = json.loads(save_report_snapshot(result, tmp_path / "r.json").read_text(encoding="utf-8"))
    meta = data["metadata"]
    assert pd.Timestamp(meta["last_observation"]) <= cutoff
    # Les dates du JSON apparaissent telles quelles dans le Markdown.
    assert meta["last_observation"] in md
    assert meta["signal_date"] in md
    assert meta["report_date"] in md


# --------------------------------------------------------------------------- #
# Constat 2 : statut CRITICAL -> code CLI 2, rapports quand même générés
# --------------------------------------------------------------------------- #
def _write_stale_data(tmp_path):
    index = pd.date_range("2016-01-31", periods=80, freq="ME")
    rng = np.random.default_rng(4)
    prices = pd.DataFrame({
        "CW8.PA": 100 * np.cumprod(1 + rng.normal(0.007, 0.03, 80)),
        "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.006, 0.04, 80)),
    }, index=index)
    path = tmp_path / "stale.csv"
    prices.to_csv(path)
    return path, index.max()


@pytest.mark.slow
def test_cli_critical_returns_code_2_and_generates_reports(tmp_path):
    data_path, last = _write_stale_data(tmp_path)
    out_dir = tmp_path / "out"
    stale_date = (last + pd.Timedelta(days=120)).date().isoformat()
    code = cli.main(["monthly-report", "--config", CONFIG_PATH, "--data", str(data_path),
                     "--output-dir", str(out_dir), "--report-date", stale_date])
    assert code == 2
    md = list(out_dir.glob("*-report.md"))
    js = list(out_dir.glob("*-report.json"))
    assert len(md) == 1 and len(js) == 1  # générés malgré le statut CRITICAL
    data = json.loads(js[0].read_text(encoding="utf-8"))
    assert data["metadata"]["pipeline_status"] == "CRITICAL"
    # Statut identique dans le Markdown.
    assert "CRITICAL" in md[0].read_text(encoding="utf-8")


@pytest.mark.slow
def test_cli_normal_returns_code_0(tmp_path):
    data_path = _write_local_data(tmp_path)
    code = cli.main(["monthly-report", "--config", CONFIG_PATH, "--data", str(data_path),
                     "--output-dir", str(tmp_path / "o")])
    assert code == 0


# --------------------------------------------------------------------------- #
# Constat 4 : VT désactivé -> Markdown/JSON explicites
# --------------------------------------------------------------------------- #
def _disabled_result():
    from dataclasses import replace
    prices = _synthetic_prices()
    base = MonthlyPipelineConfig()
    config = replace(base, volatility_targeting=replace(base.volatility_targeting, enabled=False))
    return run_monthly_pipeline(prices, config, generation_time=prices.index.max() + pd.Timedelta(days=1))


def test_markdown_vt_disabled_is_explicit(tmp_path):
    text = generate_markdown_report(_disabled_result(), tmp_path / "r.md").read_text(encoding="utf-8")
    assert "Volatility Targeting : désactivé dans la configuration" in text
    assert "non applicable" in text


def test_json_vt_disabled_is_stable_and_serializable(tmp_path):
    data = json.loads(save_report_snapshot(_disabled_result(), tmp_path / "r.json").read_text(encoding="utf-8"))
    vt = data["volatility_targeted_strategy"]
    assert vt["enabled"] is False
    assert vt["status"] == "DISABLED"
    assert vt["target_volatility"] is None
    assert vt["target_weights"] is None
    assert "Momentum + Volatility Targeting" not in vt["name"]
    # Schéma principal stable : toutes les clés de haut niveau présentes.
    for key in ("metadata", "momentum_strategy", "volatility_targeted_strategy", "benchmark"):
        assert key in data

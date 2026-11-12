"""Graphiques du rapport mensuel, liens Markdown et champ figures du snapshot."""

import json

import numpy as np
import pandas as pd
import pytest

from src.monthly_pipeline import MonthlyPipelineConfig, run_monthly_pipeline
from src.report_figures import FIGURE_NAMES, save_monthly_figures
from src.reporting import generate_markdown_report, save_report_snapshot


@pytest.fixture(scope="module")
def result():
    index = pd.date_range("2016-01-31", periods=80, freq="ME")
    rng = np.random.default_rng(5)
    prices = pd.DataFrame({
        "CW8.PA": 100 * np.cumprod(1 + rng.normal(0.008, 0.04, 80)),
        "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.006, 0.05, 80)),
    }, index=index)
    return run_monthly_pipeline(prices, MonthlyPipelineConfig(), generation_time=index[-1] + pd.Timedelta(days=1))


def test_pipeline_exposes_weights_and_volatility(result):
    assert result.vt_weights is not None and result.momentum_weights is not None
    assert np.allclose(result.vt_weights.sum(axis=1), 1.0)
    assert result.realized_volatility is not None


def test_save_monthly_figures_writes_all_pngs(result, tmp_path):
    paths = save_monthly_figures(result, tmp_path / "figures", "2022-08")
    assert set(paths) == set(FIGURE_NAMES)
    for path in paths.values():
        assert path.exists() and path.read_bytes()[:4] == b"\x89PNG"


def test_markdown_and_json_reference_figures_relatively(result, tmp_path):
    figures = save_monthly_figures(result, tmp_path / "figures", "2022-08")
    md = generate_markdown_report(result, tmp_path / "2022-08-report.md", figures)
    text = md.read_text(encoding="utf-8")
    assert "![Capital théorique (frais inclus)](figures/2022-08-equity.png)" in text
    assert "## Journal de décision" in text
    snapshot = json.loads(save_report_snapshot(result, tmp_path / "2022-08-report.json", figures)
                          .read_text(encoding="utf-8"))
    assert snapshot["figures"]["drawdown"] == "figures/2022-08-drawdown.png"
    assert snapshot["schema_version"] == "1.4"


def test_report_without_figures_says_so(result, tmp_path):
    text = generate_markdown_report(result, tmp_path / "r.md").read_text(encoding="utf-8")
    assert "Graphiques non générés" in text
    snapshot = json.loads(save_report_snapshot(result, tmp_path / "r.json").read_text(encoding="utf-8"))
    assert snapshot["figures"] == {}

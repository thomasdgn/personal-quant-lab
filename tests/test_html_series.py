"""Export HTML autonome, séries mensuelles du snapshot (1.2) et JSON de recherche."""

import base64
import json

import numpy as np
import pandas as pd

from src.html_report import markdown_to_html
from src.monthly_pipeline import MonthlyPipelineConfig, run_monthly_pipeline
from src.reporting import save_report_snapshot


def test_markdown_to_html_embeds_images_and_tables(tmp_path):
    (tmp_path / "figures").mkdir()
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
    (tmp_path / "figures" / "a.png").write_bytes(png)
    md = tmp_path / "r.md"
    md.write_text("# Rapport 2026-09\n\n| A | B |\n| --- | ---: |\n| x | 1 % |\n\n![graph](figures/a.png)\n",
                  encoding="utf-8")
    html = markdown_to_html(md).read_text(encoding="utf-8")
    assert "<title>Rapport 2026-09</title>" in html
    assert 'class="table-wrap"><table>' in html and "data:image/png;base64," in html
    assert "figures/a.png" not in html and 'name="viewport"' in html


def test_snapshot_contains_monthly_series(tmp_path):
    index = pd.date_range("2016-01-31", periods=80, freq="ME")
    rng = np.random.default_rng(5)
    prices = pd.DataFrame({"CW8.PA": 100 * np.cumprod(1 + rng.normal(0.008, 0.04, 80)),
                           "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.006, 0.05, 80))}, index=index)
    result = run_monthly_pipeline(prices, MonthlyPipelineConfig(), generation_time=index[-1] + pd.Timedelta(days=1))
    snapshot = json.loads(save_report_snapshot(result, tmp_path / "s.json").read_text(encoding="utf-8"))
    series = snapshot["series"]
    assert snapshot["schema_version"] == "1.4" and len(series) == len(result.momentum_backtest)
    last = series[-1]
    assert {"benchmark_equity", "momentum_vt_drawdown", "exposure", "held"} <= set(last)
    assert last["momentum_vt_equity"] == result.vt_backtest["Equity Curve"].iloc[-1]
    assert all(row["momentum_drawdown"] <= 0 for row in series if row["momentum_drawdown"] is not None)

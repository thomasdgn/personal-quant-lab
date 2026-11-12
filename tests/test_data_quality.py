"""Mise à jour incrémentale, contrôles qualité et archives brutes (hors-ligne)."""

import numpy as np
import pandas as pd
import pytest

import main
from src.cli import common as cli_common
from src.data_quality import archive_raw, incremental_refresh, quality_checks
from src.monthly_pipeline import MonthlyPipelineConfig, run_monthly_pipeline


def _source(end="2026-09-18"):
    index = pd.bdate_range("2026-01-01", end)
    steps = np.arange(len(index))
    return pd.DataFrame({"A.PA": 100 * 1.001 ** steps, "B.PA": 50 * 1.0005 ** steps}, index=index)


class FakeDownloader:
    """Simule yfinance : renvoie la « vérité » source à partir de ``start``."""

    def __init__(self, truth):
        self.truth, self.calls = truth, []

    def __call__(self, tickers, start):
        self.calls.append((list(tickers), start))
        return self.truth.loc[self.truth.index >= start, [t for t in tickers if t in self.truth.columns]]


def test_incremental_only_downloads_recent_days():
    truth = _source()
    existing = truth.loc[:"2026-09-11"]
    fake = FakeDownloader(truth)
    prices, info = incremental_refresh(existing, ["A.PA", "B.PA"], fake, start="2015-01-01")
    assert info["mode"] == "incremental" and info["new_rows"] == 5 and info["adjusted_tickers"] == []
    assert len(fake.calls) == 1 and fake.calls[0][1] == "2026-09-01"
    pd.testing.assert_frame_equal(prices, truth, check_freq=False)


def test_rewritten_history_triggers_full_download_of_that_ticker():
    truth = _source()
    existing = truth.loc[:"2026-09-11"].copy()
    existing["A.PA"] *= 1.02  # l'ancienne version ajustée diffère de 2 %
    fake = FakeDownloader(truth)
    prices, info = incremental_refresh(existing, ["A.PA", "B.PA"], fake, start="2015-01-01")
    assert info["adjusted_tickers"] == ["A.PA"]
    assert fake.calls[1] == (["A.PA"], "2015-01-01")
    pd.testing.assert_series_equal(prices["A.PA"], truth["A.PA"], check_freq=False)


def test_new_ticker_is_downloaded_in_full_and_full_mode():
    truth = _source().assign(**{"C.PA": 10.0})
    existing = truth.loc[:"2026-09-11", ["A.PA", "B.PA"]]
    prices, info = incremental_refresh(existing, ["A.PA", "B.PA", "C.PA"], FakeDownloader(truth), start="2015-01-01")
    assert info["new_tickers"] == ["C.PA"] and prices["C.PA"].notna().sum() == len(truth)
    full, info = incremental_refresh(existing, ["A.PA"], FakeDownloader(truth), start="2015-01-01", full=True)
    assert info["mode"] == "full" and list(full.columns) == ["A.PA"]


def test_ticker_without_recent_data_keeps_history_and_is_reported():
    truth = _source()
    existing = truth.loc[:"2026-09-11"]
    delisted = truth[["A.PA"]]
    prices, info = incremental_refresh(existing, ["A.PA", "B.PA"], FakeDownloader(delisted), start="2015-01-01")
    assert info["no_new_data"] == ["B.PA"]
    assert prices["B.PA"].dropna().index.max() == pd.Timestamp("2026-09-11")


def test_quality_checks_detect_jump_stale_and_gap():
    prices = _source()
    prices.loc["2026-09-10", "A.PA"] *= 1.3
    prices.loc["2026-09-10":, "B.PA"] = np.nan              # figé depuis 6 séances
    c = pd.Series(20.0, index=prices.index)
    c.loc["2026-08-24":"2026-08-27"] = np.nan              # trou de 4 séances
    prices["C.PA"] = c
    found = {(a["ticker"], a["type"]) for a in quality_checks(prices)}
    assert ("A.PA", "JUMP") in found and ("B.PA", "STALE") in found and ("C.PA", "GAP") in found
    assert quality_checks(_source()) == []
    assert quality_checks(prices, ignore=["A.PA", "B.PA", "C.PA"]) == []


def test_old_anomalies_outside_window_are_ignored():
    prices = _source()
    prices.loc["2026-02-10", "A.PA"] *= 1.5
    assert quality_checks(prices) == []
    assert quality_checks(prices, since="2026-01-01")


def test_archive_keeps_only_latest(tmp_path):
    for day in range(1, 9):
        archive_raw(_source().head(3), tmp_path, stamp=f"2026-09-0{day}", keep=6)
    names = sorted(p.name for p in tmp_path.glob("*.csv"))
    assert len(names) == 6 and names[0] == "2026-09-03-prices.csv"
    assert archive_raw(pd.DataFrame(), tmp_path) is None


def test_pipeline_raises_data_anomaly_alert():
    index = pd.date_range("2016-01-31", periods=80, freq="ME")
    rng = np.random.default_rng(0)
    prices = pd.DataFrame({"CW8.PA": 100 * np.cumprod(1 + rng.normal(0.008, 0.02, 80)),
                           "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.006, 0.02, 80))}, index=index)
    prices.iloc[-1, 1] = prices.iloc[-2, 1] * 1.4
    report = run_monthly_pipeline(prices, MonthlyPipelineConfig(), generation_time=index[-1]).report
    alert = next(a for a in report.alerts if a.code == "DATA_ANOMALY")
    assert alert.level == "WARNING" and "ESE.PA" in alert.message
    assert report.data_quality["anomalies"][0]["type"] == "JUMP"


@pytest.mark.slow
def test_refresh_data_command_is_incremental(tmp_path, monkeypatch, capsys):
    truth = _source().rename(columns={"A.PA": "CW8.PA", "B.PA": "ESE.PA"})
    assets = tmp_path / "assets.yaml"
    assets.write_text("universe:\n  - {ticker: CW8.PA, name: W, category: monde, universe_active: true, notes: ''}\n"
                      "  - {ticker: ESE.PA, name: S, category: us, universe_active: true, notes: ''}\n",
                      encoding="utf-8")
    data = tmp_path / "processed" / "prices.csv"
    data.parent.mkdir()
    truth.loc[:"2026-09-11"].rename_axis("Date").to_csv(data)
    fake = FakeDownloader(truth)
    monkeypatch.setattr(cli_common, "download_prices", lambda tickers, start: fake(tickers, start))
    assert main.main(["refresh-data", "--data", str(data), "--assets", str(assets)]) == 0
    out = capsys.readouterr().out
    assert "incrémental" in out and "nouvelles séances : 5" in out
    assert (tmp_path / "raw").exists() and len(list((tmp_path / "raw").glob("*.csv"))) == 1
    assert main.main(["refresh-data", "--full", "--data", str(data), "--assets", str(assets)]) == 0
    assert fake.calls[-1][1] == main.DOWNLOAD_START

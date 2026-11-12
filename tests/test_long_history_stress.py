"""Historique long par proxys (synthétique, signalé) et stress tests — hors-ligne."""

import numpy as np
import pandas as pd
import pytest

import main
from src.cli import common as cli_common
from src.costs import FeeModel
from src.long_history import (
    build_long_history,
    load_long_config,
    load_long_history,
    refresh_long_history,
    synthetic_mask,
    synthetic_share,
    to_eur_monthly,
)
from src.monthly_pipeline import MonthlyPipelineConfig
from src.stress import dca_outcomes, stress_table, strategy_backtests, synthetic_share_by_month
from src.strategies import StrategyContext

CONFIG = {"fx_ticker": "EURUSD=X", "start": "2004-01-01",
          "chains": {"A.PA": [{"ticker": "AEUR", "currency": "EUR"}, {"ticker": "AUSD", "currency": "USD"}]}}


def test_config_validation(tmp_path):
    path = tmp_path / "long.yaml"
    path.write_text("chains:\n  A.PA:\n    - {ticker: X, currency: GBP}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="currency"):
        load_long_config(path)
    with pytest.raises(FileNotFoundError):
        load_long_config(tmp_path / "absent.yaml")


def test_usd_proxies_converted_to_eur():
    index = pd.date_range("2004-01-01", periods=70, freq="B")
    daily = pd.DataFrame({"AUSD": 110.0, "AEUR": 50.0, "EURUSD=X": 1.10}, index=index)
    monthly = to_eur_monthly(daily, CONFIG)
    assert monthly["AUSD"].iloc[0] == pytest.approx(100.0) and monthly["AEUR"].iloc[0] == 50.0


def test_chain_splices_returns_and_tracks_sources():
    index = pd.date_range("2004-01-31", periods=48, freq="ME")
    growth = pd.Series(1.01 ** np.arange(48), index=index)
    real = pd.DataFrame({"A.PA": np.where(index >= "2006-01-31", 20 * growth, np.nan)}, index=index)
    proxies = pd.DataFrame({"AEUR": np.where(index >= "2005-01-31", 7 * growth, np.nan), "AUSD": 3 * growth},
                           index=index)
    built = build_long_history(real, proxies, CONFIG)
    prices, sources = built["prices"]["A.PA"], built["sources"]["A.PA"]
    assert prices.notna().all()
    assert prices.pct_change().dropna().to_numpy() == pytest.approx(0.01)  # continuité exacte des rendements
    assert prices.loc["2006-01-31"] == pytest.approx(20 * growth.loc["2006-01-31"])  # raccord au premier prix réel
    assert sources.loc["2004-06-30"] == "AUSD" and sources.loc["2005-06-30"] == "AEUR"
    assert sources.loc["2007-01-31"] == "A.PA"
    info = synthetic_share(built["sources"])["A.PA"]
    assert info["real_start"] == "2006-01-31" and info["synthetic_months"] == 24
    assert synthetic_mask(built["sources"])["A.PA"].sum() == 24
    assert {t["proxy"] for t in built["tracking"]} == {"AEUR", "AUSD"}


def test_refresh_and_reload(tmp_path):
    index = pd.bdate_range("2004-01-01", "2008-12-31")
    real = pd.DataFrame({"A.PA": np.where(index >= "2007-01-01", 10.0, np.nan)}, index=index).astype(float)
    real["A.PA"] = real["A.PA"] * np.linspace(1, 1.2, len(index))
    proxies = pd.DataFrame({"AEUR": np.linspace(5, 6, len(index)), "AUSD": np.linspace(5, 6, len(index)),
                            "EURUSD=X": 1.0}, index=index)
    calls = []

    def fake(tickers, start):
        calls.append((tuple(tickers), start))
        return proxies[[t for t in tickers if t in proxies.columns]]

    out, src_out = tmp_path / "long.csv", tmp_path / "sources.csv"
    refresh_long_history(real, fake, CONFIG, out, src_out)
    prices, sources = load_long_history(out, src_out)
    assert prices.index.min() >= pd.Timestamp("2004-01-01") and prices["A.PA"].notna().all()
    assert calls[0][1] == "2004-01-01" and "EURUSD=X" in calls[0][0]
    with pytest.raises(FileNotFoundError, match="refresh-data --long"):
        load_long_history(tmp_path / "x.csv", src_out)


# --- stress -------------------------------------------------------------------
def _bt(equity: list[float], start="2007-10-31") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(equity), freq="ME")
    return pd.DataFrame({"Equity Curve": equity, "Invested Exposure": 1.0, "Net Return": pd.Series(equity).pct_change()
                         .fillna(0).to_numpy()}, index=index)


def test_stress_table_drawdown_and_recovery():
    windows = (("Test", "2007-11-30", "2008-02-29"),)
    bt = _bt([100, 110, 99, 88, 95, 105, 111, 120])
    table = stress_table({"s": bt}, windows=windows)
    row = table.iloc[0]
    assert row["actif"] and row["drawdown_max"] == pytest.approx(88 / 110 - 1)
    assert row["rendement"] == pytest.approx(95 / 110 - 1)
    assert row["mois_recuperation"] == 3  # creux fin janvier 2008, plus haut 110 dépassé fin avril
    late = _bt([100, 101, 102], start="2008-01-31")
    assert not stress_table({"late": late}, windows=windows).iloc[0]["actif"]


def test_dca_outcomes_deterministic_with_constant_returns():
    returns = pd.Series([0.01] * 60)
    result = dca_outcomes(returns, monthly_contribution=100.0, horizon_months=24,
                          fee_model=FeeModel(proportional=0.0), n_sims=50)
    expected = sum(100 * 1.01 ** k for k in range(1, 25))
    assert result["final_gross"]["p5"] == pytest.approx(expected) == result["final_gross"]["p95"]
    assert result["prob_drawdown_beyond_limit"] == 0.0 and result["prob_loss"] == 0.0
    gain = expected - 2400
    assert result["final_net"]["p50"] == pytest.approx(expected - gain * 0.314)  # < 5 ans : flat tax 2026
    with pytest.raises(ValueError):
        dca_outcomes(pd.Series([0.01] * 5), monthly_contribution=100, horizon_months=12)


def test_dca_outcomes_detects_deep_drawdowns():
    returns = pd.Series([0.05] * 11 + [-0.5])
    result = dca_outcomes(returns, monthly_contribution=100.0, horizon_months=36, n_sims=200, block=6)
    assert result["prob_drawdown_beyond_limit"] > 0.5


def test_synthetic_share_and_backtests_on_registry():
    index = pd.date_range("2004-01-31", periods=80, freq="ME")
    rng = np.random.default_rng(1)
    monthly = pd.DataFrame({"CW8.PA": 100 * np.cumprod(1 + rng.normal(0.006, 0.04, 80)),
                            "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.006, 0.05, 80))}, index=index)
    sources = pd.DataFrame({"CW8.PA": ["X"] * 40 + ["CW8.PA"] * 40, "ESE.PA": ["ESE.PA"] * 80}, index=index)
    share = synthetic_share_by_month(sources, ["CW8.PA", "ESE.PA"])
    assert share.iloc[0] == 0.5 and share.iloc[-1] == 0.0
    ctx = StrategyContext(config=MonthlyPipelineConfig(), equities=("CW8.PA", "ESE.PA"), bond=None)
    backtests = strategy_backtests(monthly, ctx, transaction_cost=0.001)
    assert "benchmark" in backtests and "static_60_40" not in backtests


@pytest.mark.slow
def test_cli_long_refresh_research_and_stress(tmp_path, monkeypatch, capsys):
    index = pd.bdate_range("2004-01-01", "2016-12-30")
    rng = np.random.default_rng(4)
    world = 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(index)))
    real = pd.DataFrame({"CW8.PA": np.where(index >= "2012-01-01", world, np.nan),
                         "ESE.PA": 50 * np.cumprod(1 + rng.normal(0.0003, 0.012, len(index))),
                         "OBLI.PA": np.where(index >= "2008-01-01", 10 * np.cumprod(1 + rng.normal(0.0001, 0.003,
                                                                                               len(index))), np.nan)},
                        index=index)
    data = tmp_path / "processed" / "prices.csv"
    data.parent.mkdir()
    real.rename_axis("Date").to_csv(data)
    proxies = pd.DataFrame({"WORLD": world * 1.5, "EURUSD=X": 1.0}, index=index)
    long_cfg = tmp_path / "long.yaml"
    long_cfg.write_text("fx_ticker: EURUSD=X\nstart: '2004-01-01'\nchains:\n  CW8.PA:\n"
                        "    - {ticker: WORLD, currency: USD}\n", encoding="utf-8")
    assets = tmp_path / "assets.yaml"
    assets.write_text("universe:\n"
                      "  - {ticker: CW8.PA, name: W, category: m, universe_active: true, notes: ''}\n"
                      "  - {ticker: ESE.PA, name: S, category: u, universe_active: true, notes: ''}\n"
                      "  - {ticker: OBLI.PA, name: O, category: o, role: defensive, universe_active: true, notes: ''}\n",
                      encoding="utf-8")
    monkeypatch.setattr(cli_common, "download_prices",
                        lambda tickers, start: pd.concat([real, proxies], axis=1)[[t for t in tickers
                                                                                  if t in real or t in proxies]])
    long_data = tmp_path / "processed" / "long_history.csv"
    assert main.main(["refresh-data", "--long", "--data", str(data), "--assets", str(assets),
                      "--long-config", str(long_cfg), "--long-data", str(long_data)]) == 0
    assert "SYNTHÉTIQUE" in capsys.readouterr().out and long_data.exists()
    # ESE.PA et OBLI.PA n'ont pas de chaîne : seul CW8.PA est prolongé.
    common = ["--assets", str(assets), "--long-config", str(long_cfg), "--long-data", str(long_data)]
    out_dir = tmp_path / "research"
    assert main.main(["research", "--long", *common, "--output", str(out_dir / "r.md")]) == 0
    assert "SYNTHÉTIQUE" in (out_dir / "r.md").read_text(encoding="utf-8")
    assert main.main(["stress", *common, "--sims", "50", "--years", "5", "--output", str(out_dir / "stress.md")]) == 0
    text = (out_dir / "stress.md").read_text(encoding="utf-8")
    assert "Fenêtres de crise" in text and "part synthétique" in text and (out_dir / "stress.json").exists()

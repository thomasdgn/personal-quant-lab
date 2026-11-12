"""Rôles d'actifs (candidate / defensive / cash_proxy), proxy cash et CLI refresh-data."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import main
from src.cli import common as cli_common
from src.backtest import backtest_monthly_allocation
from src.monthly_pipeline import MonthlyPipelineConfig, UniverseConfig, load_config, run_monthly_pipeline
from src.universe import asset_roles, load_universe

ROOT = Path(__file__).resolve().parents[1]


def _prices(n_months=80, seed=1):
    index = pd.date_range("2016-01-31", periods=n_months, freq="ME")
    rng = np.random.default_rng(seed)
    data = {
        "CW8.PA": 100 * np.cumprod(1 + rng.normal(0.008, 0.04, n_months)),
        "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.006, 0.05, n_months)),
        "OBLI.PA": 100 * np.cumprod(1 + rng.normal(0.003, 0.01, n_months)),
        "CSH2.PA": 100 * np.power(1.002, np.arange(n_months)),
    }
    return pd.DataFrame(data, index=index)


ROLES = {"CW8.PA": "candidate", "ESE.PA": "candidate", "OBLI.PA": "defensive", "CSH2.PA": "cash_proxy"}


def _run(prices, config=None, roles=ROLES):
    config = config or MonthlyPipelineConfig()
    return run_monthly_pipeline(prices, config, generation_time=prices.index.max() + pd.Timedelta(days=1),
                                asset_roles=roles)


# --- universe.py -------------------------------------------------------------
def _write_universe(tmp_path, extra=""):
    path = tmp_path / "assets.yaml"
    path.write_text(
        "universe:\n"
        "  - {ticker: CW8.PA, name: W, category: monde, universe_active: true, notes: ''}\n"
        f"  - {{ticker: CSH2.PA, name: M, category: monetaire, universe_active: true, notes: ''{extra}}}\n",
        encoding="utf-8",
    )
    return path


def test_role_defaults_to_candidate(tmp_path):
    assets = load_universe(_write_universe(tmp_path))
    assert asset_roles(assets) == {"CW8.PA": "candidate", "CSH2.PA": "candidate"}


def test_explicit_role_is_loaded(tmp_path):
    assets = load_universe(_write_universe(tmp_path, ", role: cash_proxy"))
    assert asset_roles(assets)["CSH2.PA"] == "cash_proxy"


def test_invalid_role_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Rôle invalide"):
        load_universe(_write_universe(tmp_path, ", role: magic"))


def test_project_config_roles():
    roles = asset_roles(load_universe(ROOT / "config" / "assets.yaml"))
    assert roles["CSH2.PA"] == "cash_proxy"
    assert roles["OBLI.PA"] == "defensive"
    assert roles["CW8.PA"] == "candidate"
    config = load_config(ROOT / "config" / "strategy_params.yaml")
    assert isinstance(config.universe, UniverseConfig)


# --- backtest ----------------------------------------------------------------
def test_backtest_accepts_cash_return_series():
    index = pd.date_range("2020-01-31", periods=3, freq="ME")
    prices = pd.DataFrame({"A": [100.0, 110.0, 121.0]}, index=index)
    weights = pd.DataFrame({"A": [0.0, 0.0, 0.5], "CASH": [1.0, 1.0, 0.5]}, index=index)
    cash = pd.Series([np.nan, 0.01], index=index[:2])
    bt = backtest_monthly_allocation(prices, weights, transaction_cost=0.0, cash_return=cash)
    assert bt["Gross Return"].tolist() == pytest.approx([0.0, 0.01, 0.05])


# --- pipeline ----------------------------------------------------------------
def test_cash_proxy_is_never_ranked_and_pays_cash():
    result = _run(_prices())
    universe = result.report.universe
    assert "CSH2.PA" not in universe["assets"]
    assert universe["cash_proxy"] == "CSH2.PA"
    assert "CSH2.PA" not in (result.report.momentum_strategy.target_weights or {})
    bt = result.momentum_backtest
    cash_months = bt.index[(bt["Cash Weight"] == 1.0) & (bt["Turnover"] == 0.0)][1:]
    assert len(cash_months) > 0
    assert bt.loc[cash_months, "Gross Return"].to_numpy() == pytest.approx(0.002)


def test_cash_proxy_disabled_uses_fixed_rate():
    config = replace(MonthlyPipelineConfig(), universe=UniverseConfig(use_cash_proxy_return=False))
    result = _run(_prices(), config)
    assert result.report.universe["cash_proxy"] is None
    bt = result.momentum_backtest
    assert (bt.loc[bt["Cash Weight"] == 1.0, "Gross Return"] == 0.0).all()


def test_defensive_excluded_when_not_candidate():
    config = replace(MonthlyPipelineConfig(), universe=UniverseConfig(defensive_as_candidates=False))
    result = _run(_prices(), config)
    assert "OBLI.PA" not in result.report.universe["assets"]
    assert result.report.universe["excluded_by_role"] == ["OBLI.PA"]
    assert "OBLI.PA" in _run(_prices()).report.universe["assets"]


def test_universe_mismatch_alerts():
    roles = {**ROLES, "PAEEM.PA": "candidate"}
    prices = _prices().assign(**{"XXX.PA": 50.0})
    result = _run(prices, roles=roles)
    codes = {a.code: a for a in result.report.alerts}
    assert codes["UNIVERSE_MISMATCH"].level == "WARNING"
    assert "PAEEM.PA" in codes["UNIVERSE_MISMATCH"].message
    assert codes["UNIVERSE_EXTRA"].level == "INFO"
    assert "XXX.PA" not in result.report.universe["assets"]
    assert result.report.universe["missing_from_data"] == ["PAEEM.PA"]


def test_without_roles_behaviour_is_unchanged():
    prices = _prices()[["CW8.PA", "ESE.PA"]]
    config = MonthlyPipelineConfig()
    gen = prices.index.max() + pd.Timedelta(days=1)
    legacy = run_monthly_pipeline(prices, config, generation_time=gen)
    with_roles = run_monthly_pipeline(prices, config, generation_time=gen,
                                      asset_roles={"CW8.PA": "candidate", "ESE.PA": "candidate"})
    pd.testing.assert_frame_equal(legacy.momentum_backtest, with_roles.momentum_backtest)


# --- CLI ---------------------------------------------------------------------
def test_refresh_data_command_downloads_and_saves(tmp_path, monkeypatch, capsys):
    prices = _prices()
    captured = {}

    def fake_download(tickers, start):
        captured["tickers"], captured["start"] = tickers, start
        return prices[[t for t in tickers if t in prices.columns]]

    monkeypatch.setattr(cli_common, "download_prices", fake_download)
    out = tmp_path / "prices.csv"
    code = main.main(["refresh-data", "--data", str(out), "--assets", str(ROOT / "config" / "assets.yaml")])
    assert code == 0
    assert out.exists()
    assert "CSH2.PA" in captured["tickers"] and captured["start"] == main.DOWNLOAD_START
    assert "ATTENTION" in capsys.readouterr().out  # tickers configurés sans prix signalés


def test_default_data_falls_back_to_legacy_file(tmp_path, monkeypatch):
    legacy = tmp_path / "momentum_universe.csv"
    legacy.write_text("x", encoding="utf-8")
    monkeypatch.setattr(cli_common, "DEFAULT_DATA", tmp_path / "universe_prices.csv")
    monkeypatch.setattr(cli_common, "LEGACY_DATA", legacy)
    assert cli_common._resolve_data_path(tmp_path / "universe_prices.csv") == legacy
    assert cli_common._resolve_data_path(tmp_path / "other.csv") == tmp_path / "other.csv"

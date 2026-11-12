import numpy as np
import pandas as pd
import pytest

from src.monthly_pipeline import (
    MonthlyPipelineConfig,
    load_config,
    run_monthly_pipeline,
)


def _synthetic_prices(n_months=80, seed=0):
    """Prix mensuels synthétiques pour deux ETF + un actif à historique court."""
    index = pd.date_range("2016-01-31", periods=n_months, freq="ME")
    rng = np.random.default_rng(seed)
    a = 100 * np.cumprod(1 + rng.normal(0.008, 0.04, n_months))
    b = 100 * np.cumprod(1 + rng.normal(0.006, 0.05, n_months))
    df = pd.DataFrame({"CW8.PA": a, "ESE.PA": b}, index=index)
    # Actif à historique court -> doit être exclu.
    short = pd.Series(np.nan, index=index)
    short.iloc[-10:] = 100 * np.cumprod(1 + rng.normal(0.01, 0.05, 10))
    df["SHORT.PA"] = short
    return df


def _prices_ending_on(last_observation):
    """Série mensuelle longue complétée par une observation finale précise."""
    last_observation = pd.Timestamp(last_observation)
    previous_month_end = last_observation - pd.offsets.MonthEnd(1)
    index = pd.date_range("2016-01-31", previous_month_end, freq="ME").append(
        pd.DatetimeIndex([last_observation])
    )
    steps = np.arange(len(index))
    return pd.DataFrame({
        "CW8.PA": 100 * np.power(1.008, steps),
        "ESE.PA": 100 * np.power(1.006, steps),
    }, index=index)


@pytest.fixture
def config():
    return MonthlyPipelineConfig()


@pytest.fixture
def prices():
    return _synthetic_prices()


def _gen_time(prices):
    return prices.index.max() + pd.Timedelta(days=1)


# --------------------------------------------------------------------------- #
# exécution complète
# --------------------------------------------------------------------------- #
def test_pipeline_runs_and_produces_all_sections(prices, config):
    result = run_monthly_pipeline(prices, config, generation_time=_gen_time(prices))
    report = result.report
    for attr in ("metadata", "data_quality", "universe", "benchmark",
                 "momentum_strategy", "volatility_targeted_strategy",
                 "allocation_comparison", "risk", "alerts", "manual_decision"):
        assert getattr(report, attr) is not None
    assert report.metadata["schema_version"]
    assert report.momentum_strategy.name
    assert report.volatility_targeted_strategy.target_volatility == config.volatility_targeting.target_volatility


def test_pipeline_excludes_short_history_asset(prices, config):
    result = run_monthly_pipeline(prices, config, generation_time=_gen_time(prices))
    assert "SHORT.PA" in result.report.data_quality["excluded_assets"]
    assert "SHORT.PA" not in result.report.universe["assets"]


def test_pipeline_weights_valid_and_cash_coherent(prices, config):
    report = run_monthly_pipeline(prices, config, generation_time=_gen_time(prices)).report
    for strat in (report.momentum_strategy, report.volatility_targeted_strategy):
        w = strat.target_weights
        assert all(-1e-9 <= v <= 1 + 1e-9 for v in w.values())
        assert abs(sum(w.values()) - 1.0) < 1e-6
        assert abs(strat.cash_weight + strat.invested_exposure - 1.0) < 1e-9


def test_pipeline_capital_positive_and_metrics_present(prices, config):
    result = run_monthly_pipeline(prices, config, generation_time=_gen_time(prices))
    assert (result.vt_backtest["Equity Curve"] > 0).all()
    strat = result.report.volatility_targeted_strategy
    for metric in (strat.cagr, strat.annualized_volatility, strat.sharpe, strat.max_drawdown):
        assert metric is not None


def test_pipeline_reproducible(prices, config):
    g = _gen_time(prices)
    a = run_monthly_pipeline(prices, config, generation_time=g).vt_backtest["Equity Curve"]
    b = run_monthly_pipeline(prices, config, generation_time=g).vt_backtest["Equity Curve"]
    assert np.allclose(a.to_numpy(), b.to_numpy())


def test_invalid_config_rejected():
    bad = MonthlyPipelineConfig()
    object.__setattr__(bad.momentum, "lookback_months", 0)
    with pytest.raises(ValueError):
        bad.validate()


def test_load_config_reads_yaml(tmp_path):
    path = tmp_path / "params.yaml"
    path.write_text(
        "benchmark:\n  ticker: CW8.PA\nmomentum:\n  lookback_months: 6\n  skip_months: 1\n",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.benchmark_ticker == "CW8.PA"
    assert cfg.momentum.lookback_months == 6


# --------------------------------------------------------------------------- #
# anti-look-ahead & mois partiel
# --------------------------------------------------------------------------- #
def test_report_date_truncates_history(prices, config):
    cutoff = prices.index[-13]
    result = run_monthly_pipeline(prices, config, report_date=cutoff, generation_time=_gen_time(prices))
    # Aucun mois postérieur à la date d'arrêté.
    assert result.monthly_prices.index.max() <= cutoff
    assert pd.Timestamp(result.report.metadata["signal_date"]) <= cutoff


def test_report_date_gives_same_result_as_pre_truncated(prices, config):
    cutoff = prices.index[-13]
    g = _gen_time(prices)
    full = run_monthly_pipeline(prices, config, report_date=cutoff, generation_time=g)
    trimmed = run_monthly_pipeline(prices.loc[:cutoff], config, report_date=cutoff, generation_time=g)
    assert np.allclose(full.vt_backtest["Equity Curve"].to_numpy(),
                       trimmed.vt_backtest["Equity Curve"].to_numpy())


def test_partial_month_excluded_from_signal(config):
    # Données quotidiennes s'arrêtant au milieu d'un mois -> mois partiel.
    daily = pd.date_range("2016-01-01", "2023-03-10", freq="D")
    rng = np.random.default_rng(1)
    prices = pd.DataFrame({
        "CW8.PA": 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(daily))),
        "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.0002, 0.012, len(daily))),
    }, index=daily)
    result = run_monthly_pipeline(prices, config, generation_time=pd.Timestamp("2023-03-11"))
    # Le signal officiel s'arrête à février 2023 (dernier mois complet).
    assert result.report.metadata["signal_date"] == "2023-02-28"
    assert result.report.data_quality["partial_month"] == "2023-03"


def test_replay_excludes_partial_report_month(config):
    prices = _prices_ending_on("2026-07-08")
    report = run_monthly_pipeline(
        prices, config, report_date="2026-07-31", generation_time="2026-08-01"
    ).report
    assert report.metadata["signal_date"] == "2026-06-30"
    assert report.data_quality["partial_month"] == "2026-07"


def test_replay_includes_complete_report_month(config):
    prices = _prices_ending_on("2026-07-31")
    report = run_monthly_pipeline(
        prices, config, report_date="2026-07-31", generation_time="2026-08-01"
    ).report
    assert report.metadata["signal_date"] == "2026-07-31"
    assert report.data_quality["partial_month"] is None


def test_calendar_month_end_on_weekend_is_complete(config):
    prices = _prices_ending_on("2021-07-31")  # samedi
    report = run_monthly_pipeline(
        prices, config, report_date="2021-07-31", generation_time="2021-08-01"
    ).report
    assert report.metadata["signal_date"] == "2021-07-31"
    assert report.data_quality["partial_month"] is None


def test_last_exchange_session_before_weekend_completes_month(config):
    prices = _prices_ending_on("2021-07-30")
    report = run_monthly_pipeline(
        prices, config, report_date="2021-07-31", generation_time="2021-08-01"
    ).report
    assert report.metadata["signal_date"] == "2021-07-31"
    assert report.data_quality["partial_month"] is None


def test_no_future_data_used(prices, config):
    cutoff = prices.index[-13]
    result = run_monthly_pipeline(prices, config, report_date=cutoff, generation_time=_gen_time(prices))
    future_prices = prices.loc[prices.index > cutoff]
    # Les prix mensuels utilisés n'incluent aucune date future.
    assert result.monthly_prices.index.max() < future_prices.index.min()


# --------------------------------------------------------------------------- #
# alertes
# --------------------------------------------------------------------------- #
def _codes(report):
    return {a.code for a in report.alerts}


def test_alert_stale_data(config):
    prices = _prices_ending_on("2026-07-08")
    report = run_monthly_pipeline(
        prices, config, generation_time="2026-10-01",
    ).report
    stale = [a for a in report.alerts if a.code == "STALE_DATA"]
    assert stale and stale[0].level == "CRITICAL"
    assert report.data_quality["data_age_days"] == 85
    assert report.metadata["freshness_reference"] == "2026-10-01"
    assert report.metadata["pipeline_status"] == "CRITICAL"


def test_current_report_with_fresh_data_has_no_stale_alert(config):
    prices = _prices_ending_on("2026-08-01")
    report = run_monthly_pipeline(
        prices, config, generation_time="2026-08-02",
    ).report
    assert report.data_quality["data_age_days"] == 1
    assert report.metadata["freshness_reference"] == "2026-08-02"
    assert "STALE_DATA" not in _codes(report)


def test_alert_asset_excluded(prices, config):
    report = run_monthly_pipeline(prices, config, generation_time=_gen_time(prices)).report
    assert "ASSET_EXCLUDED" in _codes(report)


def test_alert_data_not_refreshed_flag(prices, config):
    report = run_monthly_pipeline(prices, config, generation_time=_gen_time(prices), data_refreshed=False).report
    assert "DATA_NOT_REFRESHED" in _codes(report)


def test_alerts_have_valid_levels_and_no_order_language(prices, config):
    report = run_monthly_pipeline(prices, config, generation_time=_gen_time(prices)).report
    forbidden = ("achet", "vend", "ordre à exécuter", "buy", "sell")
    for alert in report.alerts:
        assert alert.level in ("INFO", "WARNING", "CRITICAL")
        assert not any(word in alert.message.lower() for word in forbidden)


def test_full_cash_alert_when_all_defensive(config):
    # Marché baissier prolongé -> momentum reste en cash -> exposition VT nulle.
    index = pd.date_range("2016-01-31", periods=60, freq="ME")
    declining = pd.DataFrame({
        "CW8.PA": np.linspace(200, 100, 60),
        "ESE.PA": np.linspace(200, 90, 60),
    }, index=index)
    report = run_monthly_pipeline(declining, config, generation_time=index.max() + pd.Timedelta(days=1)).report
    assert report.volatility_targeted_strategy.cash_weight > 0.999
    assert "FULL_CASH" in _codes(report)


def test_manual_decision_is_pending(prices, config):
    report = run_monthly_pipeline(prices, config, generation_time=_gen_time(prices)).report
    assert report.manual_decision["status"] == "PENDING"
    assert report.manual_decision["approved_weights"] is None


# --------------------------------------------------------------------------- #
# Constat 1 : aucune métadonnée postérieure à report_date
# --------------------------------------------------------------------------- #
def _replay_prices():
    """Données mensuelles 2016-01 -> 2026-08 (au-delà des dates de replay)."""
    index = pd.date_range("2016-01-31", "2026-08-31", freq="ME")
    rng = np.random.default_rng(11)
    return pd.DataFrame({
        "CW8.PA": 100 * np.cumprod(1 + rng.normal(0.007, 0.04, len(index))),
        "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.006, 0.05, len(index))),
    }, index=index)


@pytest.mark.parametrize("report_date", ["2025-08-31", "2026-06-30", "2026-07-07"])
def test_metadata_never_uses_future_data(report_date, config):
    prices = _replay_prices()
    report = run_monthly_pipeline(
        prices, config, report_date=report_date,
        generation_time=pd.Timestamp(report_date) + pd.Timedelta(days=1),
    ).report
    rd = pd.Timestamp(report_date)
    last_obs = pd.Timestamp(report.metadata["last_observation"])
    max_asset = max(pd.Timestamp(d) for d in report.data_quality["last_date_per_asset"].values())
    assert last_obs <= rd
    assert max_asset <= rd
    assert report.data_quality["data_age_days"] >= 0
    assert pd.Timestamp(report.metadata["signal_date"]) <= rd


def test_reproduces_negative_data_age_scenario():
    # Scénario initial : report_date=2021-08-31, données jusqu'en 2026.
    # Avant correction : data_age_days = -364 (fuite temporelle).
    prices = _replay_prices()
    report = run_monthly_pipeline(
        prices, config=MonthlyPipelineConfig(), report_date="2021-08-31",
        generation_time=pd.Timestamp("2021-09-01"),
    ).report
    assert report.data_quality["data_age_days"] >= 0
    assert pd.Timestamp(report.metadata["last_observation"]) <= pd.Timestamp("2021-08-31")


def test_future_observation_does_not_affect_freshness():
    # Une observation postérieure au cutoff ne doit pas influencer data_age_days.
    prices = _replay_prices()
    cutoff = "2022-01-31"
    full = run_monthly_pipeline(prices, MonthlyPipelineConfig(), report_date=cutoff,
                                generation_time=pd.Timestamp(cutoff) + pd.Timedelta(days=1)).report
    trimmed = run_monthly_pipeline(prices.loc[:cutoff], MonthlyPipelineConfig(), report_date=cutoff,
                                   generation_time=pd.Timestamp(cutoff) + pd.Timedelta(days=1)).report
    assert full.data_quality["data_age_days"] == trimmed.data_quality["data_age_days"]
    assert full.metadata["last_observation"] == trimmed.metadata["last_observation"]


# --------------------------------------------------------------------------- #
# Constat 2 : propagation du statut CRITICAL
# --------------------------------------------------------------------------- #
def _two_asset_prices():
    index = pd.date_range("2016-01-31", periods=80, freq="ME")
    rng = np.random.default_rng(5)
    return pd.DataFrame({
        "CW8.PA": 100 * np.cumprod(1 + rng.normal(0.008, 0.03, 80)),
        "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.006, 0.04, 80)),
    }, index=index)


def _calm_prices():
    """Hausse très régulière et peu volatile : aucune alerte de risque VT."""
    index = pd.date_range("2016-01-31", periods=80, freq="ME")
    rng = np.random.default_rng(9)
    return pd.DataFrame({
        "CW8.PA": 100 * np.cumprod(1 + rng.normal(0.010, 0.003, 80)),
        "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.009, 0.003, 80)),
    }, index=index)


def test_status_ok_when_no_warning_or_critical():
    prices = _calm_prices()
    report = run_monthly_pipeline(prices, MonthlyPipelineConfig(), data_refreshed=True,
                                  generation_time=prices.index.max() + pd.Timedelta(days=1)).report
    assert not any(a.level in ("WARNING", "CRITICAL") for a in report.alerts)
    assert report.metadata["pipeline_status"] == "OK"


def test_status_ok_with_info_only():
    prices = _calm_prices()
    report = run_monthly_pipeline(prices, MonthlyPipelineConfig(), data_refreshed=False,
                                  generation_time=prices.index.max() + pd.Timedelta(days=1)).report
    assert any(a.level == "INFO" for a in report.alerts)
    assert not any(a.level in ("WARNING", "CRITICAL") for a in report.alerts)
    assert report.metadata["pipeline_status"] == "OK"


def test_status_warning_when_only_warnings():
    prices = _synthetic_prices()  # actif SHORT.PA -> ASSET_EXCLUDED (WARNING)
    report = run_monthly_pipeline(prices, MonthlyPipelineConfig(), data_refreshed=True,
                                  generation_time=_gen_time(prices)).report
    assert any(a.level == "WARNING" for a in report.alerts)
    assert not any(a.level == "CRITICAL" for a in report.alerts)
    assert report.metadata["pipeline_status"] == "OK_WITH_WARNINGS"


def test_status_critical_dominates_warning():
    prices = _synthetic_prices()  # SHORT.PA -> WARNING, et stale -> CRITICAL
    stale_date = prices.index.max() + pd.Timedelta(days=45)
    report = run_monthly_pipeline(prices, MonthlyPipelineConfig(), report_date=stale_date,
                                  generation_time=stale_date + pd.Timedelta(days=1)).report
    assert any(a.level == "CRITICAL" for a in report.alerts)
    assert any(a.level == "WARNING" for a in report.alerts)
    assert report.metadata["pipeline_status"] == "CRITICAL"


# --------------------------------------------------------------------------- #
# Constat 4 : volatility_targeting.enabled = false
# --------------------------------------------------------------------------- #
from dataclasses import replace  # noqa: E402


def _disabled_config():
    base = MonthlyPipelineConfig()
    return replace(base, volatility_targeting=replace(base.volatility_targeting, enabled=False))


def test_vt_disabled_marks_section_and_skips_logic(monkeypatch):
    import src.monthly_pipeline as mp

    def _boom(*args, **kwargs):
        raise AssertionError("build_vol_targeted_weights ne doit pas être appelé quand VT désactivé.")

    monkeypatch.setattr(mp, "build_vol_targeted_weights", _boom)

    prices = _two_asset_prices()
    result = run_monthly_pipeline(prices, _disabled_config(),
                                  generation_time=prices.index.max() + pd.Timedelta(days=1))
    vt = result.report.volatility_targeted_strategy
    assert vt.status == "DISABLED"
    assert vt.enabled is False
    assert vt.target_volatility is None
    assert vt.target_weights is None
    assert "Momentum + Volatility Targeting" not in vt.name
    # Momentum et benchmark restent calculés normalement.
    assert result.report.momentum_strategy.target_weights is not None
    assert result.report.benchmark.cagr is not None


def test_vt_disabled_produces_no_vt_alerts():
    prices = _two_asset_prices()
    report = run_monthly_pipeline(prices, _disabled_config(),
                                  generation_time=prices.index.max() + pd.Timedelta(days=1)).report
    vt_codes = {"REDUCED_EXPOSURE", "MOMENTUM_VT_DIVERGENCE", "HIGH_VOLATILITY",
                "FULL_CASH", "HIGH_DRAWDOWN", "HIGH_TURNOVER", "HIGH_COST", "METRIC_UNAVAILABLE"}
    assert not any(a.code in vt_codes for a in report.alerts)


def test_vt_enabled_still_computes_vt(monkeypatch):
    # Non-régression : avec enabled=true, la logique VT est bien appelée.
    import src.monthly_pipeline as mp
    called = {"vt": False}
    original = mp.build_vol_targeted_weights

    def _spy(*args, **kwargs):
        called["vt"] = True
        return original(*args, **kwargs)

    monkeypatch.setattr(mp, "build_vol_targeted_weights", _spy)
    prices = _two_asset_prices()
    report = run_monthly_pipeline(prices, MonthlyPipelineConfig(),
                                  generation_time=prices.index.max() + pd.Timedelta(days=1)).report
    assert called["vt"] is True
    assert report.volatility_targeted_strategy.status == "ACTIVE"
    assert report.volatility_targeted_strategy.target_volatility == 0.10

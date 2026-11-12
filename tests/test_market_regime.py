import numpy as np
import pandas as pd
import pytest

from src.market_regime import (
    FEATURE_COLUMNS,
    TARGET_END_COLUMN,
    backtest_ml_strategy,
    build_ml_dataset,
    evaluate_models,
    generate_regime_report,
    split_dataset,
    train_models,
)


@pytest.fixture(scope="module")
def synthetic_prices():
    index = pd.bdate_range("2016-01-01", "2026-08-31")
    rng = np.random.default_rng(42)
    regimes = np.where((np.arange(len(index)) // 90) % 2 == 0, 0.0010, -0.0007)
    returns = regimes + rng.normal(0, 0.008, len(index))
    daily = pd.DataFrame({"CW8.PA": 100 * np.cumprod(1 + returns)}, index=index)
    monthly = daily.resample("ME").last()
    return daily, monthly


@pytest.fixture(scope="module")
def dataset(synthetic_prices):
    return build_ml_dataset(*synthetic_prices)


@pytest.fixture(scope="module")
def trained(dataset):
    split = split_dataset(dataset, "2021-12-31", "2023-12-31")
    X_train, y_train, X_val, y_val, X_test, y_test, dates = split
    models = train_models(X_train, y_train)
    return models, X_train, y_train, X_val, y_val, X_test, y_test, dates


def test_build_ml_dataset_returns_dataframe_without_nan(dataset):
    assert isinstance(dataset, pd.DataFrame)
    assert isinstance(dataset.index, pd.DatetimeIndex)
    assert not dataset.isna().any().any()
    assert set(FEATURE_COLUMNS).issubset(dataset.columns)


def test_features_do_not_use_prices_after_month_m(synthetic_prices):
    daily, monthly = synthetic_prices
    cutoff = pd.Timestamp("2021-06-30")
    original = build_ml_dataset(daily, monthly)
    changed_daily = daily.copy()
    changed_monthly = monthly.copy()
    changed_daily.loc[changed_daily.index > cutoff, "CW8.PA"] *= 4
    changed_monthly.loc[changed_monthly.index > cutoff, "CW8.PA"] *= 4
    changed = build_ml_dataset(changed_daily, changed_monthly)
    pd.testing.assert_series_equal(
        original.loc[cutoff, FEATURE_COLUMNS],
        changed.loc[cutoff, FEATURE_COLUMNS],
    )


def test_forward_target_uses_exactly_three_future_months(synthetic_prices, dataset):
    _, monthly = synthetic_prices
    observation = dataset.index[10]
    expected_return = monthly["CW8.PA"].shift(-3).loc[observation] / monthly["CW8.PA"].loc[observation] - 1
    assert dataset.loc[observation, "forward_return_3m"] == pytest.approx(expected_return)
    assert dataset.loc[observation, "target"] == int(expected_return > 0)


def test_partial_last_month_is_not_used_as_target_endpoint(synthetic_prices):
    daily, monthly = synthetic_prices
    partial_daily = daily.loc[:"2026-08-12"]
    partial_monthly = monthly.loc[:"2026-08-31"].copy()
    partial_monthly.loc[pd.Timestamp("2026-08-31"), "CW8.PA"] = partial_daily["CW8.PA"].iloc[-1]
    result = build_ml_dataset(partial_daily, partial_monthly)
    assert result[TARGET_END_COLUMN].max() <= pd.Timestamp("2026-07-31")


def test_split_dataset_is_strictly_temporal_and_purged(dataset):
    X_train, _, X_val, _, X_test, _, dates = split_dataset(dataset, "2021-12-31", "2023-12-31")
    assert X_train.index.max() < X_val.index.min() < X_test.index.min()
    assert dataset.loc[X_train.index, TARGET_END_COLUMN].max() <= pd.Timestamp("2021-12-31")
    assert dataset.loc[X_val.index, TARGET_END_COLUMN].max() <= pd.Timestamp("2023-12-31")
    assert dates["train"].equals(X_train.index)


def test_scaler_is_fitted_only_on_train(trained):
    models, X_train, _, X_val, _, _, _, _ = trained
    assert models["scaler"].mean_ == pytest.approx(X_train.mean().to_numpy())
    combined_mean = pd.concat([X_train, X_val.assign(momentum_1m=1_000)]).mean().to_numpy()
    assert not np.allclose(models["scaler"].mean_, combined_mean)


def test_model_parameters_are_constrained(trained):
    models = trained[0]
    assert models["logistic"].C == 1.0
    assert models["logistic"].max_iter == 1000
    assert models["random_forest"].n_estimators == 100
    assert models["random_forest"].max_depth == 3


def test_evaluate_models_returns_expected_metrics(trained):
    models, _, _, X_val, y_val, X_test, y_test, _ = trained
    result = evaluate_models(models, X_val, y_val, X_test, y_test)
    for model_name in ("logistic", "random_forest"):
        for split in ("validation", "test"):
            metrics = result[model_name][split]
            assert {"accuracy", "risk_off", "risk_on", "confusion_matrix", "roc_auc"}.issubset(metrics)
            assert {"precision", "recall", "f1"}.issubset(metrics["risk_on"])


def test_baseline_majority_is_exposed(trained):
    models, _, y_train, X_val, y_val, X_test, y_test, _ = trained
    result = evaluate_models(models, X_val, y_val, X_test, y_test)
    assert result["baseline"]["majority_class"] == int(y_train.value_counts().idxmax())
    assert 0 <= result["baseline"]["test"]["accuracy"] <= 1


def test_backtest_ml_strategy_returns_financial_metrics(trained, synthetic_prices):
    models, _, _, _, _, X_test, y_test, _ = trained
    result = backtest_ml_strategy(models, X_test, y_test, synthetic_prices[1])
    for strategy in ("logistic", "random_forest", "buy_and_hold"):
        assert {"cagr", "sharpe", "max_drawdown"}.issubset(result[strategy])
        assert result[strategy]["max_drawdown"] <= 0


def test_generate_regime_report_is_non_empty_and_idempotent(tmp_path, trained, synthetic_prices, dataset):
    models, X_train, _, X_val, y_val, X_test, y_test, _ = trained
    evaluation = evaluate_models(models, X_val, y_val, X_test, y_test)
    evaluation["dataset"] = {
        "start": dataset.index.min().date().isoformat(),
        "end": dataset.index.max().date().isoformat(),
        "n_observations": len(dataset),
        "features": FEATURE_COLUMNS,
        "train_size": len(X_train),
        "validation_size": len(X_val),
        "test_size": len(X_test),
        "risk_off": int((dataset["target"] == 0).sum()),
        "risk_on": int((dataset["target"] == 1).sum()),
    }
    backtest = backtest_ml_strategy(models, X_test, y_test, synthetic_prices[1])
    output = tmp_path / "market_regime_report.md"
    generate_regime_report(evaluation, backtest, output)
    first = output.read_text(encoding="utf-8")
    generate_regime_report(evaluation, backtest, output)
    assert output.stat().st_size > 0
    assert output.read_text(encoding="utf-8") == first
    assert "Limites" in first and "baseline" in first


# --------------------------------------------------------------------------- #
# Walk-forward, paliers d'exposition, comparaison avec frais
# --------------------------------------------------------------------------- #
from src.market_regime import (  # noqa: E402
    build_feature_frame,
    compare_regime_strategies,
    current_regime,
    evaluate_walk_forward,
    probability_to_exposure,
    run_regime_study,
    walk_forward_probabilities,
)
from src.monthly_pipeline import MonthlyPipelineConfig  # noqa: E402


@pytest.mark.parametrize(
    "probability, expected",
    [(0.95, 1.0), (0.61, 1.0), (0.60, 0.6), (0.51, 0.6), (0.50, 0.3), (0.41, 0.3), (0.40, 0.0), (0.0, 0.0)],
)
def test_probability_to_exposure_uses_fixed_bands(probability, expected):
    assert probability_to_exposure(probability) == expected


def test_probability_to_exposure_handles_nan_and_rejects_invalid():
    assert np.isnan(probability_to_exposure(float("nan")))
    with pytest.raises(ValueError):
        probability_to_exposure(1.5)


def test_feature_frame_keeps_recent_rows_without_target(synthetic_prices, dataset):
    frame = build_feature_frame(*synthetic_prices)
    assert frame.index.max() > dataset.index.max()
    assert frame["target"].isna().sum() == 3
    pd.testing.assert_frame_equal(frame.dropna().astype({"target": int}), dataset)


@pytest.fixture(scope="module")
def wf_probabilities(synthetic_prices):
    return walk_forward_probabilities(build_feature_frame(*synthetic_prices), min_train_size=80)


@pytest.mark.slow
def test_walk_forward_trains_only_on_targets_known_at_decision(synthetic_prices, wf_probabilities):
    frame = build_feature_frame(*synthetic_prices)
    labelled = frame.dropna(subset=["target"])
    for date, row in wf_probabilities.iterrows():
        assert row["train_size"] == int((labelled[TARGET_END_COLUMN] <= date).sum())
    assert wf_probabilities["train_size"].min() >= 80
    assert wf_probabilities[["logistic", "random_forest"]].stack().between(0, 1).all()


@pytest.mark.slow
def test_walk_forward_is_unchanged_by_future_prices(synthetic_prices, wf_probabilities):
    daily, monthly = synthetic_prices
    cutoff = pd.Timestamp("2025-06-30")
    truncated = walk_forward_probabilities(
        build_feature_frame(daily.loc[:cutoff], monthly.loc[:cutoff]), min_train_size=80
    )
    common = truncated.index
    assert common.max() == cutoff
    pd.testing.assert_frame_equal(
        truncated[["logistic", "random_forest", "train_size"]],
        wf_probabilities.loc[common, ["logistic", "random_forest", "train_size"]],
    )


@pytest.mark.slow
def test_evaluate_walk_forward_and_current_regime(wf_probabilities):
    result = evaluate_walk_forward(wf_probabilities)
    assert result["n_observations"] == int(wf_probabilities["target"].notna().sum())
    assert 0 <= result["logistic"]["accuracy"] <= 1
    current = current_regime(wf_probabilities)
    assert current["signal_date"] == wf_probabilities.index.max().date().isoformat()
    assert current["exposure_logistic"] in {0.0, 0.3, 0.6, 1.0}


def _universe_monthly(synthetic_prices):
    _, monthly = synthetic_prices
    other = monthly["CW8.PA"].rename("ESE.PA") * np.linspace(1.0, 1.4, len(monthly))
    return pd.concat([monthly["CW8.PA"], other], axis=1)


@pytest.mark.slow
def test_compare_regime_strategies_full_exposure_matches_buy_and_hold(synthetic_prices, wf_probabilities):
    probabilities = wf_probabilities.assign(logistic=1.0)
    result = compare_regime_strategies(_universe_monthly(synthetic_prices), probabilities, "CW8.PA",
                                       MonthlyPipelineConfig())
    pd.testing.assert_series_equal(result["returns"]["ml_benchmark"], result["returns"]["buy_and_hold"],
                                   check_names=False)
    assert set(result["strategies"]) == {"buy_and_hold", "ml_benchmark", "ml_momentum", "momentum", "momentum_vt"}
    assert all(len(r) == result["n_months"] for r in result["returns"].values())


@pytest.mark.slow
def test_compare_regime_strategies_zero_exposure_stays_in_cash(synthetic_prices, wf_probabilities):
    probabilities = wf_probabilities.assign(logistic=0.1)
    result = compare_regime_strategies(_universe_monthly(synthetic_prices), probabilities, "CW8.PA",
                                       MonthlyPipelineConfig())
    assert result["strategies"]["ml_benchmark"]["avg_exposure"] == 0.0
    assert result["strategies"]["ml_momentum"]["avg_exposure"] == 0.0
    assert set(result["verdict"]) == {"ml_benchmark", "ml_momentum"}


@pytest.mark.slow
def test_run_regime_study_and_report_with_walk_forward(tmp_path, synthetic_prices):
    daily, _ = synthetic_prices
    study = run_regime_study(daily, _universe_monthly(synthetic_prices), MonthlyPipelineConfig(),
                             min_train_size=80)
    output = tmp_path / "report.md"
    generate_regime_report(study["evaluation"], study["backtest"], output, study["walk_forward"])
    text = output.read_text(encoding="utf-8")
    assert "Walk-forward" in text and "Verdict" in text and "Régime courant" in text

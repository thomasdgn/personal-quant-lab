"""Scénarios de rendement explicites, absence de surperformance, crypto en espérance,
contrôle modèle / vrai passé et sensibilité (hors-ligne, déterministe)."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.costs import FeeModel
from src.investor_profile import assess_profile, profile_from_dict
from src.plans import (
    HISTORICAL,
    Hypotheses,
    PlanDef,
    Pocket,
    Scenario,
    build_inputs,
    load_scenarios,
    model_check,
    recenter,
    remove_alpha,
    run_plans,
    shift_prices,
)
from src.taxes import TaxConfig

ROOT = Path(__file__).resolve().parents[1]
HYP = Hypotheses(simulations=200)


def _prices(n=240, seed=4):
    index = pd.date_range("2005-01-31", periods=n, freq="ME")
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"CW8.PA": 100 * np.cumprod(1 + rng.normal(0.008, 0.045, n)),
                         "PAEEM.PA": 50 * np.cumprod(1 + rng.normal(0.005, 0.06, n)),
                         "OBLI.PA": 10 * np.cumprod(1 + rng.normal(0.003, 0.01, n))}, index=index)


def _geo(series: pd.Series) -> float:
    r = series.pct_change(fill_method=None).dropna()
    return float((1 + r).prod() ** (12 / len(r)) - 1)


def test_committed_scenarios():
    scenarios, default = load_scenarios(ROOT / "config" / "plans.yaml")
    assert default == "central" and {"historique", "central", "defavorable"} <= set(scenarios)
    assert scenarios["historique"].is_historical and not scenarios["central"].is_historical
    assert scenarios["central"].surperformance == "nulle"
    assert scenarios["defavorable"].actions_pct < scenarios["central"].actions_pct


@pytest.mark.parametrize("content, message", [
    ({"scenarios": {"x": {"actions_pct": 50}}}, "entre -10 et 20"),
    ({"scenarios": {"x": {"inconnu": 1}}}, "invalide"),
    ({"scenarios": {"x": {"surperformance": "magique"}}}, "surperformance"),
    ({"scenario_defaut": "absent"}, "inconnu"),
])
def test_invalid_scenarios(tmp_path, content, message):
    path = tmp_path / "plans.yaml"
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_scenarios(path)


def test_shift_prices_hits_targets_and_keeps_shocks():
    prices = _prices()
    roles = {"CW8.PA": "candidate", "PAEEM.PA": "candidate", "OBLI.PA": "defensive"}
    scenario = Scenario("c", "Central", actions_pct=6.0, obligations_pct=2.0)
    shifted = shift_prices(prices, roles, benchmark="CW8.PA", scenario=scenario)
    assert _geo(shifted["CW8.PA"]) == pytest.approx(0.06, abs=1e-9)
    assert _geo(shifted["OBLI.PA"]) == pytest.approx(0.02, abs=1e-9)
    # Même décalage pour toutes les actions : écart entre zones et volatilité conservés.
    log = lambda df: np.log1p(df.pct_change(fill_method=None)).dropna()  # noqa: E731
    before, after = log(prices), log(shifted)
    assert (after["PAEEM.PA"] - after["CW8.PA"]).to_numpy() == pytest.approx(
        (before["PAEEM.PA"] - before["CW8.PA"]).to_numpy())
    assert after.std().to_numpy() == pytest.approx(before.std().to_numpy())
    assert shift_prices(prices, roles, benchmark="CW8.PA", scenario=HISTORICAL) is prices


def test_remove_alpha_equalizes_sharpe_and_crypto_expectation():
    rng = np.random.default_rng(9)
    index = pd.date_range("2005-01-31", periods=200, freq="ME")
    bench = pd.Series(rng.normal(0.006, 0.045, 200), index=index)
    strategy = pd.Series(rng.normal(0.009, 0.03, 200), index=index)
    neutral = np.log1p(remove_alpha(strategy, bench))
    logs_b = np.log1p(bench)
    assert neutral.mean() / neutral.std() == pytest.approx(logs_b.mean() / logs_b.std())
    crypto = pd.Series(rng.normal(0.04, 0.2, 120))
    arithmetic = recenter(crypto, 0.05, "esperance")
    assert (1 + arithmetic).mean() == pytest.approx(1.05 ** (1 / 12))
    geometric = recenter(crypto, 0.05, "geometrique")
    assert (1 + geometric).prod() ** (12 / 120) == pytest.approx(1.05)
    assert (1 + arithmetic).prod() < (1 + geometric).prod()  # espérance fixée = médiane bien plus basse
    with pytest.raises(ValueError, match="Mode"):
        recenter(crypto, 0.05, "autre")


def test_model_check_rules():
    sim = {"final": {"net_real": {"p5": 10, "p10": 20, "p25": 30, "p50": 40, "p75": 50, "p90": 60, "p95": 70}}}
    hist = {"available": True, "net_real": {"median": 40}}
    assert model_check(sim, hist, 15, 260)["status"] == "cohérent"
    low = model_check(sim, {"available": True, "net_real": {"median": 22}}, 15, 260)
    assert low["status"] == "divergent" and low["percentile"] < 0.25 and "divergent" in low["text"]
    assert model_check(sim, {"available": True, "net_real": {"median": 5}}, 15, 260)["percentile"] == 0.0
    missing = model_check(sim, {"available": False}, 15, 260)
    assert missing["status"] == "indisponible" and missing["independent_periods"] == pytest.approx(260 / 180)


def test_run_plans_with_scenarios_sensitivity_and_check():
    plan = PlanDef(id="p", nom="P", resume="", pour_qui="", temps="5min", complexite=1, horizon_min_ans=1,
                   zones=("monde",), poches=(Pocket("M", "pea", 1.0, "etf", {"CW8.PA": 1.0}),), routine=())
    prices = _prices()
    roles = {"CW8.PA": "candidate"}
    hist = build_inputs([plan], prices, strategy_returns={}, crypto_monthly=None, hyp=HYP)
    central = build_inputs([plan], shift_prices(prices, roles, benchmark="CW8.PA",
                                                scenario=Scenario("central", "Central", 4.0, None)),
                           strategy_returns={}, crypto_monthly=None, hyp=HYP)
    central.scenario = Scenario("central", "Central", 4.0, None)
    raw = yaml.safe_load((ROOT / "config" / "profil.example.yaml").read_text(encoding="utf-8"))
    profile = replace(profile_from_dict(raw), horizon_ans=8)
    study = run_plans([plan], central, profile, assess_profile(profile), hyp=HYP, taxes=TaxConfig(),
                      fee_model=FeeModel(proportional=0.0), n_sims=100, reference_inputs=hist,
                      scenario_inputs={"historique": hist, "central": central})
    item = study["results"]["p"]
    assert item["model_check"]["status"] in ("cohérent", "divergent")
    sens = study["sensitivity"]["p"]
    assert set(sens) == {"historique", "central"} and sens["central"]["p50"] < sens["historique"]["p50"]
    assert study["scenario"].label == "Central"
    assert item["simulation"]["final"]["net_real"]["p50"] < sens["historique"]["p50"]

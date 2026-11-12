"""Plans d'investissement : validation, moteur de simulation, relecture historique,
adéquation au profil, rapport et CLI (hors-ligne, déterministe)."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

import main
from src.costs import FeeModel
from src.investor_profile import assess_profile, load_profile, profile_from_dict
from src.plans import (
    PEA_CEILING,
    Hypotheses,
    PlanDef,
    Pocket,
    _engine,
    build_inputs,
    evaluate_fit,
    historical_windows,
    implied_annual_return,
    load_plans,
    recenter,
    replay,
    run_plans,
    simulate_plan,
)
from src.plans_report import generate_plans_report, save_plans_json
from src.taxes import TaxConfig

ROOT = Path(__file__).resolve().parents[1]
HYP = Hypotheses(simulations=200)
NO_FEES = FeeModel(proportional=0.0)


def _plan(*pockets, **kw):
    base = {"id": "p", "nom": "P", "resume": "", "pour_qui": "", "temps": "5min", "complexite": 1,
            "horizon_min_ans": 1, "zones": ("monde",), "poches": tuple(pockets), "routine": ()}
    base.update(kw)
    return PlanDef(**base)


def _world(n=240, seed=0):
    index = pd.date_range("2005-01-31", periods=n, freq="ME")
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"CW8.PA": 100 * np.cumprod(1 + rng.normal(0.007, 0.045, n)),
                         "PAEEM.PA": 50 * np.cumprod(1 + rng.normal(0.005, 0.06, n))}, index=index)


def _profile(**changes):
    raw = yaml.safe_load((ROOT / "config" / "profil.example.yaml").read_text(encoding="utf-8"))
    raw.update(changes)
    return profile_from_dict(raw)


# --------------------------------------------------------------------------- #
def test_committed_plans_are_valid():
    hyp, plans = load_plans(ROOT / "config" / "plans.yaml")
    assert hyp.simulations >= 1000 and len(plans) >= 6
    assert {"monde_passif", "prudent_fonds_euros", "monde_emergents_crypto"} <= {p.id for p in plans}
    assert all(p.routine and p.resume for p in plans)


@pytest.mark.parametrize("pocket, message", [
    ({"nom": "x", "enveloppe": "pea", "part": 1.0, "type": "crypto", "allocation": {"BTC-EUR": 1.0}}, "jamais dans le PEA"),
    ({"nom": "x", "enveloppe": "pea", "part": 1.0, "type": "fonds_euros"}, "assurance-vie"),
    ({"nom": "x", "enveloppe": "pea", "part": 1.0, "type": "strategie", "strategie": "magie"}, "stratégie inconnue"),
    ({"nom": "x", "enveloppe": "pea", "part": 1.0, "type": "etf", "allocation": {"CW8.PA": 0.5}}, "sommant à 1"),
    ({"nom": "x", "enveloppe": "livret", "part": 1.0, "type": "etf", "allocation": {"CW8.PA": 1}}, "enveloppe"),
    ({"nom": "x", "enveloppe": "pea", "part": 0.5, "type": "etf", "allocation": {"CW8.PA": 1}}, "sommer à 1"),
])
def test_invalid_plans_have_explicit_errors(tmp_path, pocket, message):
    path = tmp_path / "plans.yaml"
    path.write_text(yaml.safe_dump({"plans": [{"id": "a", "temps": "5min", "zones": ["monde"], "poches": [pocket]}]},
                                   allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_plans(path)
    with pytest.raises(FileNotFoundError):
        load_plans(tmp_path / "absent.yaml")


def test_recenter_hits_target_geometric_mean():
    returns = pd.Series(np.random.default_rng(1).normal(0.05, 0.2, 120))
    adjusted = recenter(returns, 0.05)
    assert (1 + adjusted).prod() ** (12 / len(adjusted)) - 1 == pytest.approx(0.05)
    assert np.log1p(adjusted).std() == pytest.approx(np.log1p(returns).std())


def test_engine_matches_closed_form_annuity():
    plan = _plan(Pocket("Monde", "pea", 1.0, "etf", {"CW8.PA": 1.0}))
    r, horizon, capital, monthly = 0.005, 60, 1000.0, 100.0
    out = _engine(plan, [np.full((2, horizon), r)], capital=capital, monthly=monthly, hyp=HYP, taxes=TaxConfig(),
                  fee_model=NO_FEES)
    expected = capital * (1 + r) ** horizon + monthly * sum((1 + r) ** (horizon - t) for t in range(horizon))
    assert out["gross"]["pea"] == pytest.approx([expected, expected])
    assert out["invested"]["pea"] == pytest.approx(capital + monthly * horizon)
    gain = expected - (capital + monthly * horizon)
    assert out["net"]["pea"][0] == pytest.approx(expected - gain * 0.186)  # PEA > 5 ans, taux 2026
    assert out["max_drawdown"].min() == 0.0
    assert implied_annual_return(expected, capital, monthly, horizon) == pytest.approx((1 + r) ** 12 - 1, abs=1e-6)


def test_engine_pea_ceiling_overflows_to_cto_and_fees():
    plan = _plan(Pocket("Monde", "pea", 1.0, "etf", {"CW8.PA": 1.0}))
    out = _engine(plan, [np.zeros((1, 24))], capital=0.0, monthly=10_000.0, hyp=HYP, taxes=TaxConfig(),
                  fee_model=FeeModel(proportional=0.001))
    assert out["invested"]["pea"] == pytest.approx(PEA_CEILING)
    assert out["invested"]["cto_surplus"] == pytest.approx(240_000 - PEA_CEILING)
    assert out["fees_total"] == pytest.approx(240_000 * 0.001)
    assert out["gross"]["pea"][0] + out["gross"]["cto_surplus"][0] == pytest.approx(240_000 * 0.999)


def test_fonds_euros_assurance_vie_and_crypto_fees():
    plan = _plan(Pocket("FE", "assurance_vie", 0.5, "fonds_euros"),
                 Pocket("BTC", "crypto", 0.5, "crypto", {"BTC-EUR": 1.0}))
    months = 120
    fe = np.full((1, months), (1.025) ** (1 / 12) - 1)
    out = _engine(plan, [fe, np.zeros((1, months))], capital=0.0, monthly=100.0, hyp=HYP, taxes=TaxConfig(),
                  fee_model=NO_FEES)
    assert out["gross"]["crypto"][0] == pytest.approx(50 * months * (1 - HYP.crypto_frais_achat_pct / 100))
    assert out["net"]["crypto"][0] == pytest.approx(out["gross"]["crypto"][0])  # moins-value : pas d'impôt
    gain = out["gross"]["assurance_vie"][0] - 50 * months
    assert out["net"]["assurance_vie"][0] == pytest.approx(out["gross"]["assurance_vie"][0] - gain * 0.172)


def _inputs(plans, monthly_prices=None, crypto=None):
    return build_inputs(plans, monthly_prices if monthly_prices is not None else _world(),
                        strategy_returns={}, crypto_monthly=crypto, hyp=HYP)


def test_simulation_is_deterministic_ordered_and_prudent_is_lower():
    plan = _plan(Pocket("Monde", "pea", 1.0, "etf", {"CW8.PA": 0.85, "PAEEM.PA": 0.15}))
    inputs = _inputs([plan])
    kwargs = {"capital": 500.0, "monthly": 150.0, "horizon_years": 10, "hyp": HYP, "taxes": TaxConfig(),
              "fee_model": NO_FEES, "goal_real": 25_000.0, "drawdown_tolerance": 0.3}
    a, b = simulate_plan(plan, inputs, **kwargs), simulate_plan(plan, inputs, **kwargs)
    assert a["final"] == b["final"]
    net = a["final"]["net_real"]
    assert net["p5"] <= net["p10"] <= net["p50"] <= net["p90"] <= net["p95"]
    assert 0 <= a["prob_goal"] <= 1 and len(a["goal_curve"]) == len(a["fan"]["months"]) == 11
    assert a["contributed"] == 500 + 150 * 120 and a["contributed_real"] < a["contributed"]
    assert 0 <= a["drawdown"]["prob_beyond_tolerance"] <= 1
    prudent = simulate_plan(plan, inputs, **kwargs, prudent=True)
    assert prudent["final"]["net_real"]["p50"] < net["p50"]


def test_historical_windows_and_replay():
    plan = _plan(Pocket("Monde", "pea", 1.0, "etf", {"CW8.PA": 1.0}))
    inputs = _inputs([plan])
    kwargs = {"capital": 0.0, "monthly": 100.0, "hyp": HYP, "taxes": TaxConfig(), "fee_model": NO_FEES}
    hist = historical_windows(plan, inputs, horizon_years=10, **kwargs)
    assert hist["available"] and hist["n_windows"] == len(inputs.main) - 120 + 1
    assert hist["net_real"]["min"] <= hist["net_real"]["median"] <= hist["net_real"]["max"]
    assert not historical_windows(plan, inputs, horizon_years=40, **kwargs)["available"]
    path = replay(plan, inputs, horizon_years=5, **kwargs)
    assert len(path) == 60 and path["versé"].iloc[-1] == 6000
    # La relecture utilise les vrais rendements, dans l'ordre.
    expected = 0.0
    for r in inputs.main.iloc[:60, 0]:
        expected = (expected + 100) * (1 + r)
    assert path["valeur"].iloc[-1] == pytest.approx(expected)


def test_crypto_inputs_are_recentered_but_history_is_real():
    plan = _plan(Pocket("Monde", "pea", 0.95, "etf", {"CW8.PA": 1.0}),
                 Pocket("BTC", "crypto", 0.05, "crypto", {"BTC-EUR": 1.0}))
    index = pd.date_range("2015-01-31", periods=100, freq="ME")
    btc = pd.DataFrame({"BTC-EUR": 100 * 1.06 ** np.arange(100)}, index=index)
    inputs = _inputs([plan], crypto=btc)
    assert (1 + inputs.crypto.iloc[:, 0]).prod() ** (12 / 99) - 1 == pytest.approx(HYP.crypto_rendement_annuel_pct / 100)
    assert inputs.crypto_raw.iloc[:, 0].to_numpy() == pytest.approx(0.06)
    hist = historical_windows(plan, inputs, capital=0.0, monthly=100.0, horizon_years=5, hyp=HYP, taxes=TaxConfig(),
                              fee_model=NO_FEES)
    assert hist["available"] and hist["first_start"][:7] == "2015-02"
    with pytest.raises(ValueError, match="crypto"):
        _inputs([plan], crypto=None)
    with pytest.raises(ValueError, match="introuvables"):
        _inputs([_plan(Pocket("X", "pea", 1.0, "etf", {"ZZZ.PA": 1.0}))])


def test_fit_rules():
    crypto_plan = _plan(Pocket("Monde", "pea", 0.95, "etf", {"CW8.PA": 1.0}),
                        Pocket("BTC", "crypto", 0.05, "crypto", {"BTC-EUR": 1.0}), necessite=("crypto",),
                        zones=("monde", "emergents"))
    sim = {"drawdown": {"prob_beyond_tolerance": 0.2, "p50": -0.3}}
    no_crypto = _profile(zones=["monde"])
    fit = evaluate_fit(crypto_plan, sim, no_crypto, assess_profile(no_crypto), HYP)
    assert fit["status"] == "peu adapté" and any("crypto" in c["message"] for c in fit["checks"])
    small = _profile(options={"crypto": True}, versement_mensuel_eur=150, zones=["monde", "emergents"])
    fit = evaluate_fit(crypto_plan, sim, small, assess_profile(small), HYP)
    assert fit["status"] == "adapté avec réserves"
    assert any("tous les 4 mois" in c["message"] for c in fit["checks"])
    active = _plan(Pocket("VT", "pea", 1.0, "strategie", strategie="momentum_vt"), complexite=4, horizon_min_ans=5)
    busy = _profile(temps_mensuel="5min", horizon_ans=3)
    fit = evaluate_fit(active, sim, busy, assess_profile(busy), HYP)
    messages = " ".join(c["message"] for c in fit["checks"])
    assert fit["status"] == "peu adapté" and "trop élevée" in messages and "Horizon" in messages
    risky = {"drawdown": {"prob_beyond_tolerance": 0.9, "p50": -0.5}}
    fit = evaluate_fit(_plan(Pocket("M", "pea", 1.0, "etf", {"CW8.PA": 1.0})), risky, _profile(),
                       assess_profile(_profile()), HYP)
    assert fit["status"] == "peu adapté"


def test_run_plans_report_and_json(tmp_path):
    plans = [_plan(Pocket("Monde", "pea", 1.0, "etf", {"CW8.PA": 1.0}), id="a", nom="A"),
             _plan(Pocket("Monde", "pea", 0.6, "etf", {"CW8.PA": 1.0}), Pocket("FE", "assurance_vie", 0.4, "fonds_euros"),
                   id="b", nom="B", necessite=("assurance_vie",))]
    profile = replace(_profile(), horizon_ans=10, objectif_capital_eur=20_000.0)
    study = run_plans(plans, _inputs(plans), profile, assess_profile(profile), hyp=HYP, taxes=TaxConfig(),
                      fee_model=NO_FEES, n_sims=100)
    assert set(study["ranking"]) == {"a", "b"}
    assert study["results"]["b"]["simulation"]["by_envelope"]["assurance_vie"]["invested"] > 0
    report = generate_plans_report(study, tmp_path / "plans" / "plans_report.md").read_text(encoding="utf-8")
    assert "Comparaison des plans" in report and "objectif" in report and "Les enveloppes en bref" in report
    assert (tmp_path / "plans" / "figures" / "plan_a.png").exists()
    payload = json.loads(save_plans_json(study, tmp_path / "plans" / "p.json").read_text(encoding="utf-8"))
    assert payload["results"]["a"]["replay"]["dates"] and payload["profile"]["horizon_ans"] == 10


@pytest.mark.slow
def test_plans_cli_on_synthetic_files(tmp_path, capsys):
    long_prices = _world(n=260)
    long_prices["OBLI.PA"] = 100 * np.cumprod(1 + np.random.default_rng(3).normal(0.002, 0.01, len(long_prices)))
    data = tmp_path / "long_history.csv"
    long_prices.rename_axis("Date").to_csv(data)
    pd.DataFrame({c: c for c in long_prices.columns}, index=long_prices.index).rename_axis("Date").to_csv(
        tmp_path / "long_history_sources.csv")
    long_cfg = tmp_path / "long.yaml"
    long_cfg.write_text("chains:\n" + "".join(f"  {c}:\n    - {{ticker: P{i}, currency: EUR}}\n"
                                              for i, c in enumerate(long_prices)), encoding="utf-8")
    assets = tmp_path / "assets.yaml"
    assets.write_text("universe:\n" + "".join(
        f"  - {{ticker: {c}, name: {c}, category: x, universe_active: true, notes: ''"
        + (", role: defensive" if c == "OBLI.PA" else "") + "}\n" for c in long_prices), encoding="utf-8")
    crypto = pd.DataFrame({"BTC-EUR": 100 * np.cumprod(1 + np.random.default_rng(5).normal(0.002, 0.04, 3000))},
                          index=pd.date_range("2015-01-01", periods=3000, freq="D"))
    crypto.rename_axis("Date").to_csv(tmp_path / "crypto.csv")
    profile = tmp_path / "profil.yaml"
    profile.write_text((ROOT / "config" / "profil.example.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    out = tmp_path / "plans" / "plans_report.md"
    args = ["plans", "--profile", str(profile), "--assets", str(assets), "--long-config", str(long_cfg),
            "--long-data", str(data), "--crypto", str(tmp_path / "crypto.csv"), "--output", str(out), "--sims", "100",
            "--years", "12", "--monthly", "300", "--patrimoine", str(tmp_path / "absent.yaml")]
    assert main.main(args) == 0
    printed = capsys.readouterr().out
    assert "SYNTHÉTIQUE" in printed and "Passif Monde" in printed and "EUR" in printed
    assert out.exists() and out.with_suffix(".json").exists()
    assert main.main([*args, "--only", "monde_passif,inconnu"]) == 1
    assert main.main([*args, "--only", "monde_passif", "--scenario", "defavorable"]) == 0
    printed = capsys.readouterr().out
    assert "DÉFAVORABLE" in printed and "Sensibilité" in printed
    assert main.main([*args, "--only", "monde_passif", "--scenario", "inconnu"]) == 1
    assert load_profile(profile).versement_mensuel_eur == 200  # le profil n'est jamais modifié par --monthly

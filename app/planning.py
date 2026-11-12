"""Données des pages Profil, Plans, Stratégies et Robustesse (mises en cache).

Les simulations de plans sont recalculées en direct (quelques dixièmes de
seconde) pour permettre de tester d'autres montants sans modifier le profil.
Seule la page Profil écrit un fichier : ``config/profil.yaml`` (personnel).
Aucun ordre n'est passé.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.cache import project_cache

from app.data import PROJECT_ROOT

PROFILE = PROJECT_ROOT / "config" / "profil.yaml"
PROFILE_EXAMPLE = PROJECT_ROOT / "config" / "profil.example.yaml"
PLANS = PROJECT_ROOT / "config" / "plans.yaml"
ROBUSTNESS_JSON = PROJECT_ROOT / "reports" / "research" / "robustness_report.json"
STRESS_JSON = PROJECT_ROOT / "reports" / "research" / "stress_report.json"
LONG_PRICES = PROJECT_ROOT / "data" / "processed" / "long_history.csv"
CRYPTO = PROJECT_ROOT / "data" / "processed" / "crypto_prices.csv"


def load_profile_or_example():
    """Profil personnel, sinon le modèle (``is_example`` = True)."""
    from src.investor_profile import load_profile

    profile = load_profile(PROFILE)
    return (profile, False) if profile is not None else (load_profile(PROFILE_EXAMPLE), True)


@project_cache(show_spinner="Préparation des rendements historiques…", max_entries=2)
def plan_context() -> dict:
    """Plans, hypothèses et rendements des poches (historique long, crypto)."""
    from src.cli.common import DEFAULT_ASSETS, DEFAULT_CONFIG, DEFAULT_LONG_CONFIG, DEFAULT_PATRIMOINE, DEFAULT_POLICY
    from src.cli.common import _load_asset_roles
    from src.costs import load_fee_model
    from src.data_loader import load_prices
    from src.long_history import load_long_config, load_long_history
    from src.monthly_pipeline import load_config
    from src.patrimoine import load_patrimoine_config
    from src.plans import load_plans, load_scenarios, prepare_inputs
    from src.policy import load_policy
    from src.taxes import tax_config_from

    if not LONG_PRICES.exists():
        raise FileNotFoundError("Historique long absent.")
    hyp, plans = load_plans(PLANS)
    crypto = load_prices(CRYPTO) if CRYPTO.exists() else None
    if crypto is None:
        plans = [p for p in plans if not p.has_crypto]
    long_prices, _ = load_long_history(LONG_PRICES, LONG_PRICES.with_name("long_history_sources.csv"))
    config = load_config(DEFAULT_CONFIG)
    scenarios, default = load_scenarios(PLANS)
    common = {"long_prices": long_prices, "roles": _load_asset_roles(DEFAULT_ASSETS),
              "long_config": load_long_config(DEFAULT_LONG_CONFIG), "config": config,
              "policy": load_policy(DEFAULT_POLICY), "crypto_daily": crypto}
    by_scenario = {key: prepare_inputs(plans, hyp, scenario=scenario, **common) for key, scenario in scenarios.items()}
    patrimoine = load_patrimoine_config(DEFAULT_PATRIMOINE) if Path(DEFAULT_PATRIMOINE).exists() else {}
    from dataclasses import replace

    hyp = replace(hyp, frequence_achat_mois=int((patrimoine.get("profil") or {}).get("frequence_achat_mois", 1)))
    return {"hyp": hyp, "plans": plans, "inputs": by_scenario, "scenarios": scenarios, "default_scenario": default,
            "taxes": tax_config_from(patrimoine), "fee_model": load_fee_model(DEFAULT_CONFIG)}


@project_cache(show_spinner="Simulation des plans…", max_entries=32)
def plan_study(profile_data: dict, *, scenario: str | None = None, n_sims: int = 1000) -> dict:
    """Simulation de tous les plans pour un profil et un scénario de rendement (défaut : plans.yaml)."""
    from src.investor_profile import assess_profile, profile_from_dict
    from src.plans import run_plans

    ctx = plan_context()
    key = scenario or ctx["default_scenario"]
    profile = profile_from_dict(profile_data, "profil")
    return run_plans(ctx["plans"], ctx["inputs"][key], profile, assess_profile(profile), hyp=ctx["hyp"],
                     taxes=ctx["taxes"], fee_model=ctx["fee_model"], n_sims=n_sims,
                     reference_inputs=ctx["inputs"].get("historique"), scenario_inputs=ctx["inputs"])


def scenario_options() -> tuple[dict, str]:
    """Scénarios disponibles ``{clé: Scenario}`` et scénario par défaut."""
    ctx = plan_context()
    return ctx["scenarios"], ctx["default_scenario"]


def _load_json(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@project_cache(ttl=300, show_spinner=False)
def load_robustness() -> dict | None:
    return _load_json(ROBUSTNESS_JSON)


@project_cache(ttl=300, show_spinner=False)
def load_stress_study() -> dict | None:
    return _load_json(STRESS_JSON)


@project_cache(ttl=600, show_spinner="Audit des frais…")
def fee_audit_view() -> dict:
    from src.cli.common import DEFAULT_ASSETS, DEFAULT_CONFIG, DEFAULT_DATA, DEFAULT_PATRIMOINE, DEFAULT_POLICY
    from src.optimization import fee_audit_from_project

    return fee_audit_from_project(profile_path=PROFILE if PROFILE.exists() else PROFILE_EXAMPLE,
                                  policy_path=DEFAULT_POLICY, config_path=DEFAULT_CONFIG, plans_path=PLANS,
                                  patrimoine_path=DEFAULT_PATRIMOINE, data_path=DEFAULT_DATA,
                                  assets_path=DEFAULT_ASSETS)


@project_cache(ttl=600, show_spinner="Simulation des options plus risquées…")
def max_return_view() -> dict:
    from src.cli.common import DEFAULT_ASSETS, DEFAULT_CONFIG, DEFAULT_LONG_CONFIG, DEFAULT_PATRIMOINE, DEFAULT_POLICY
    from src.optimization import max_return_from_project

    if not LONG_PRICES.exists():
        raise FileNotFoundError("Historique long absent.")
    return max_return_from_project(profile_path=PROFILE if PROFILE.exists() else PROFILE_EXAMPLE,
                                   policy_path=DEFAULT_POLICY, config_path=DEFAULT_CONFIG, plans_path=PLANS,
                                   patrimoine_path=DEFAULT_PATRIMOINE, assets_path=DEFAULT_ASSETS,
                                   long_config_path=DEFAULT_LONG_CONFIG, long_data_path=LONG_PRICES)

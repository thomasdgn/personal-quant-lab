"""Calculs de l'audit des frais et de l'étude « rendement maximal » à partir des
fichiers du projet (partagés par la CLI et le tableau de bord). Aucun ordre."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path


def fee_audit_from_project(*, profile_path, policy_path, config_path, plans_path, patrimoine_path, data_path,
                           assets_path) -> dict:
    from src.cli.common import _load_prices
    from src.costs import FeeModel, load_fee_model
    from src.fee_audit import fee_audit
    from src.investor_profile import load_profile
    from src.patrimoine import load_patrimoine_config
    from src.plans import load_scenarios
    from src.policy import load_policy
    from src.positions import last_prices
    from src.taxes import tax_config_from
    from src.universe import load_universe
    from src.vehicles import map_target_to_vehicles

    profile = load_profile(profile_path)
    if profile is None:
        raise FileNotFoundError(f"Profil absent : {profile_path}. Lance `python main.py profile --questionnaire`.")
    policy = load_policy(policy_path)
    allocation = dict(policy.allocation_fixe) or {"CW8.PA": 1.0}
    assets = load_universe(assets_path)
    quotes = last_prices(_load_prices(Path(data_path), Path(assets_path), False))["prix"].to_dict()
    monthly = profile.versement_mensuel_eur
    weights, _ = map_target_to_vehicles(allocation, {}, quotes, assets, monthly)
    weights = {t: w for t, w in weights.items() if t != "CASH" and w > 0}
    ter = {a["ticker"]: (a.get("fiche") or {}).get("ter_pct") for a in assets}
    alternatives = {}
    if "WPEA.PA" in weights:
        alternatives["Avec CW8.PA au lieu de WPEA.PA"] = {("CW8.PA" if t == "WPEA.PA" else t): w
                                                            for t, w in weights.items()}
    scenarios, default = load_scenarios(plans_path)
    annual_return = (scenarios[default].actions_pct or 6.0) / 100
    patrimoine = load_patrimoine_config(patrimoine_path) if Path(patrimoine_path).exists() else {}
    models = {"Ton courtier": load_fee_model(config_path),
              "Forfait 0,99 €": FeeModel(proportional=0.0, fixed_per_order=0.99),
              "0,1 % sans minimum": FeeModel(proportional=0.001),
              "Achats programmés sans frais": FeeModel(proportional=0.0)}
    tickers = set(weights) | {k for a in alternatives.values() for k in a}
    return fee_audit(weights, {t: quotes[t] for t in tickers}, monthly=monthly, capital=profile.capital_initial_eur,
                     horizon_years=profile.horizon_ans, annual_return=annual_return, fee_models=models,
                     current="Ton courtier", ter_pct=ter, ter_alternatives=alternatives,
                     taxes=tax_config_from(patrimoine))


def max_return_from_project(*, profile_path, policy_path, config_path, plans_path, patrimoine_path, assets_path,
                            long_config_path, long_data_path, n_sims: int = 1000) -> dict:
    from src.cli.common import _load_asset_roles, _long_universe, _strategy_context
    from src.costs import load_fee_model
    from src.investor_profile import load_profile
    from src.long_history import load_long_config, load_long_history
    from src.max_return import default_options, run_max_return_study
    from src.monthly_pipeline import load_config
    from src.patrimoine import load_patrimoine_config
    from src.plans import load_plans, load_scenarios
    from src.policy import load_policy
    from src.taxes import tax_config_from

    profile = load_profile(profile_path)
    if profile is None:
        raise FileNotFoundError(f"Profil absent : {profile_path}. Lance `python main.py profile --questionnaire`.")
    config = load_config(config_path)
    policy = load_policy(policy_path)
    roles = _load_asset_roles(Path(assets_path))
    long_prices, _ = load_long_history(long_data_path, Path(long_data_path).with_name("long_history_sources.csv"))
    monthly = _long_universe(long_prices, roles, load_long_config(long_config_path))
    hyp, _ = load_plans(plans_path)
    patrimoine = load_patrimoine_config(patrimoine_path) if Path(patrimoine_path).exists() else {}
    hyp = replace(hyp, frequence_achat_mois=int((patrimoine.get("profil") or {}).get("frequence_achat_mois", 1)))
    scenarios, _ = load_scenarios(plans_path)
    return run_max_return_study(default_options(policy.allocation_fixe), monthly, roles=roles,
                                ctx=_strategy_context(config, roles, monthly.columns, policy),
                                transaction_cost=config.backtest.transaction_cost, scenarios=scenarios,
                                profile=profile, hyp=hyp, taxes=tax_config_from(patrimoine),
                                fee_model=load_fee_model(config_path), n_sims=n_sims)

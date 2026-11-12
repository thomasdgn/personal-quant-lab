"""Commandes du profil investisseur et des plans d'investissement (aucun ordre)."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from src.cli.common import PROJECT_ROOT

DEFAULT_PROFILE = PROJECT_ROOT / "config" / "profil.yaml"
PROFILE_EXAMPLE = PROJECT_ROOT / "config" / "profil.example.yaml"


def _cmd_profile(args: argparse.Namespace) -> int:
    from src.investor_profile import assess_profile, load_profile, profile_lines, run_questionnaire, save_profile

    path = Path(args.profile)
    if args.init:
        if path.exists():
            print(f"{path} existe déjà : rien n'est écrasé.")
        else:
            shutil.copyfile(PROFILE_EXAMPLE, path)
            print(f"Profil créé à partir du modèle : {path} (personnel, ignoré par Git).")
    if args.questionnaire:
        print("Questionnaire du profil investisseur (Entrée = garder la valeur entre crochets).")
        save_profile(run_questionnaire(input, base=load_profile(path)), path)
        print(f"\nProfil enregistré : {path} (personnel, ignoré par Git).")
    profile = load_profile(path)
    if profile is None:
        print(f"Aucun profil : {path} absent. Lance `python main.py profile --questionnaire` "
              "(ou --init pour partir du modèle).")
        return 1
    assessment = assess_profile(profile)
    print("=== Profil investisseur (déclaratif, aucun conseil) ===")
    for line in profile_lines(profile, assessment):
        print(f"  {line}")
    if assessment.notes:
        print("\nRemarques :")
        for note in assessment.notes:
            print(f"  - {note}")
    print("\nÉtape suivante : `python main.py plans` pour simuler les plans d'investissement sur ce profil.")
    return 0


DEFAULT_PLANS = PROJECT_ROOT / "config" / "plans.yaml"
DEFAULT_CRYPTO = PROJECT_ROOT / "data" / "processed" / "crypto_prices.csv"
DEFAULT_PLANS_REPORT = PROJECT_ROOT / "reports" / "plans" / "plans_report.md"


def load_plan_study(args: argparse.Namespace):
    """Profil (avec surcharges éventuelles), plans et rendements des poches."""
    from dataclasses import replace

    from src.cli.common import _load_asset_roles
    from src.costs import load_fee_model
    from src.data_loader import load_prices
    from src.investor_profile import assess_profile, load_profile
    from src.long_history import load_long_config, load_long_history
    from src.monthly_pipeline import load_config
    from src.patrimoine import load_patrimoine_config
    from src.plans import load_plans, load_scenarios, prepare_inputs
    from src.policy import load_policy
    from src.taxes import tax_config_from

    profile = load_profile(args.profile)
    if profile is None:
        raise FileNotFoundError(f"Profil absent : {args.profile}. Lance `python main.py profile --questionnaire`.")
    overrides = {k: v for k, v in (("versement_mensuel_eur", args.monthly), ("capital_initial_eur", args.capital),
                                   ("horizon_ans", args.years), ("objectif_capital_eur", args.goal)) if v is not None}
    if overrides:
        profile = replace(profile, **overrides)
    hyp, plans = load_plans(args.plans)
    if args.only:
        wanted = set(args.only.split(","))
        unknown = wanted - {p.id for p in plans}
        if unknown:
            raise ValueError(f"Plans inconnus : {', '.join(sorted(unknown))}.")
        plans = [p for p in plans if p.id in wanted]
    config = load_config(args.config)
    long_prices, _ = load_long_history(args.long_data, Path(args.long_data).with_name("long_history_sources.csv"))
    crypto = load_prices(args.crypto) if Path(args.crypto).exists() else None
    if crypto is None and any(p.has_crypto for p in plans):
        print(f"Prix crypto absents ({args.crypto}) : plans avec crypto ignorés.")
        plans = [p for p in plans if not p.has_crypto]
    scenarios, default = load_scenarios(args.plans)
    chosen = "defavorable" if args.prudent and "defavorable" in scenarios else (args.scenario or default)
    if chosen not in scenarios:
        raise ValueError(f"Scénario inconnu : {chosen} (disponibles : {', '.join(scenarios)}).")
    common = {"long_prices": long_prices, "roles": _load_asset_roles(Path(args.assets)),
              "long_config": load_long_config(args.long_config), "config": config, "policy": load_policy(args.policy),
              "crypto_daily": crypto}
    by_scenario = {key: prepare_inputs(plans, hyp, scenario=scenario, **common) for key, scenario in scenarios.items()}
    inputs = by_scenario[chosen]
    patrimoine = load_patrimoine_config(args.patrimoine) if Path(args.patrimoine).exists() else {}
    frequency = int((patrimoine.get("profil") or {}).get("frequence_achat_mois", 1))
    if frequency != hyp.frequence_achat_mois:
        hyp = replace(hyp, frequence_achat_mois=frequency)
    return {"profile": profile, "assessment": assess_profile(profile), "hyp": hyp, "plans": plans, "inputs": inputs,
            "reference_inputs": by_scenario.get("historique"), "scenario_inputs": by_scenario,
            "taxes": tax_config_from(patrimoine), "fee_model": load_fee_model(args.config)}


def _cmd_plans(args: argparse.Namespace) -> int:
    from src.plans import run_plans
    from src.plans_report import eur, generate_plans_report, pct, save_plans_json

    ctx = load_plan_study(args)
    study = run_plans(ctx["plans"], ctx["inputs"], ctx["profile"], ctx["assessment"], hyp=ctx["hyp"],
                      taxes=ctx["taxes"], fee_model=ctx["fee_model"], n_sims=args.sims,
                      reference_inputs=ctx["reference_inputs"], scenario_inputs=ctx["scenario_inputs"])
    output = Path(args.output)
    path = generate_plans_report(study, output)
    save_plans_json(study, output.with_suffix(".json"))
    profile = ctx["profile"]
    print(f"Plans d'investissement : {profile.versement_mensuel_eur:,.0f} EUR/mois pendant {profile.horizon_ans} ans "
          f"(départ {profile.capital_initial_eur:,.0f} EUR), historique {study['window'][0]} -> {study['window'][1]} "
          f"partiellement SYNTHÉTIQUE, scénario {study['scenario'].label.upper()}.")
    print("Valeur nette à l'horizon en euros d'aujourd'hui (p10 / médiane / p90). Ordres de grandeur, pas des conseils.")
    for pid in study["ranking"]:
        item = study["results"][pid]
        final = item["simulation"]["final"]["net_real"]
        print(f"  {item['plan'].nom[:34]:34} {item['fit']['status']:21} {eur(final['p10']):>10} / "
              f"{eur(final['p50']):>10} / {eur(final['p90']):>10}  baisse médiane "
              f"{pct(item['simulation']['drawdown']['p50'])}".replace("\u20ac", "EUR"))
    sensitivity = study.get("sensitivity") or {}
    if sensitivity:
        keys = list(next(iter(sensitivity.values())))
        print("\nSensibilité : médiane nette (EUR d'aujourd'hui) selon le scénario de rendement")
        print("  " + " " * 34 + "".join(f"{sensitivity[study['ranking'][0]][k]['label'][:14]:>16}" for k in keys))
        for pid in study["ranking"]:
            print(f"  {study['results'][pid]['plan'].nom[:34]:34}"
                  + "".join(f"{eur(sensitivity[pid][k]['p50']).replace('€', 'EUR'):>16}" for k in keys))
        divergent = [study["results"][p]["plan"].nom for p in study["ranking"]
                     if (study["results"][p]["model_check"] or {}).get("status") == "divergent"]
        if divergent:
            print("Modèle et vrai passé divergent pour : " + ", ".join(divergent) + ".")
    print(f"Rapport (personnel, ignoré par Git) : {path}")
    print("Aucun ordre passé ; la stratégie suivie (config/policy.yaml) n'est pas modifiée.")
    return 0


DEFAULT_FEES_REPORT = PROJECT_ROOT / "reports" / "plans" / "frais_report.md"
DEFAULT_MAX_RETURN_REPORT = PROJECT_ROOT / "reports" / "plans" / "rendement_max_report.md"


def _cmd_fees(args: argparse.Namespace) -> int:
    from src.fee_audit import fee_audit_lines, generate_fee_report
    from src.optimization import fee_audit_from_project

    audit = fee_audit_from_project(profile_path=args.profile, policy_path=args.policy, config_path=args.config,
                                   plans_path=args.plans, patrimoine_path=args.patrimoine, data_path=args.data,
                                   assets_path=args.assets)
    path = generate_fee_report(audit, Path(args.output))
    print(f"Audit des frais : {audit['monthly']:,.0f} EUR/mois pendant {audit['horizon_years']} ans, rendement "
          f"supposé {audit['annual_return']:.1%}/an (aucun ordre passé).")
    for line in fee_audit_lines(audit):
        print("  " + line.replace("€", "EUR"))
    print(f"Rapport (personnel, ignoré par Git) : {path}")
    return 0


def _cmd_max_return(args: argparse.Namespace) -> int:
    from src.max_return import conclusion_lines, generate_max_return_report
    from src.optimization import max_return_from_project

    study = max_return_from_project(profile_path=args.profile, policy_path=args.policy, config_path=args.config,
                                    plans_path=args.plans, patrimoine_path=args.patrimoine, assets_path=args.assets,
                                    long_config_path=args.long_config, long_data_path=args.long_data,
                                    n_sims=args.sims or 1000)
    path = generate_max_return_report(study, Path(args.output))
    print("Rendement maximal : gains et pertes possibles (pédagogique, aucune recommandation, aucun ordre).")
    key = "central" if "central" in study["scenarios"] else next(iter(study["scenarios"]))
    rows = study["scenarios"][key]["rows"]
    for option in study["options"]:
        r = rows[option.key]
        print(f"  {option.label[:44]:44} médiane {r['p50']:>9,.0f} EUR  [1/10 : {r['p10']:>8,.0f} ; "
              f"{r['p90']:>9,.0f}]  P(perdre > 50 %) {r['prob_ruin']:.0%}")
    for line in conclusion_lines(study, key):
        print("  - " + line.replace("€", "EUR").replace("« ", '"').replace(" »", '"'))
    print(f"Rapport (personnel, ignoré par Git) : {path}")
    return 0

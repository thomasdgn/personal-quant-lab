"""Parseur argparse et point d'entrée ``main``."""

from __future__ import annotations

import argparse
import sys

from src.cli.common import (
    DEFAULT_ASSETS,
    DEFAULT_CONFIG,
    DEFAULT_DATA,
    DEFAULT_HOLDINGS,
    DEFAULT_LOG_DIR,
    DEFAULT_LONG_CONFIG,
    DEFAULT_LONG_PRICES,
    DEFAULT_NOTIFY,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PAPER_DIR,
    DEFAULT_PATRIMOINE,
    DEFAULT_PENDING,
    DEFAULT_POLICY,
    DEFAULT_POSITIONS,
    DEFAULT_REPORTS_DIR,
    DEFAULT_TRANSACTIONS,
)
from src.cli.plan_cmds import (
    DEFAULT_CRYPTO,
    DEFAULT_PLANS,
    DEFAULT_PLANS_REPORT,
    DEFAULT_FEES_REPORT,
    DEFAULT_MAX_RETURN_REPORT,
    DEFAULT_PROFILE,
    _cmd_fees,
    _cmd_max_return,
    _cmd_plans,
    _cmd_profile,
)
from src.cli.paper_cmds import (
    _cmd_compare_reports,
    _cmd_paper_decision,
    _cmd_paper_init,
    _cmd_paper_list,
    _cmd_paper_performance,
)
from src.cli.report_cmds import _cmd_monthly_report, _cmd_refresh_data, _cmd_run_month, _cmd_status, _cmd_validate
from src.cli.research_cmds import _cmd_costs, _cmd_policy, _cmd_regime, _cmd_research, _cmd_robustness, _cmd_strategies, _cmd_stress
from src.cli.wealth_cmds import (
    _cmd_dca,
    _cmd_patrimoine,
    _cmd_plan_contribution,
    _cmd_portfolio,
    _cmd_universe,
    _cmd_vehicles,
)
from src.monthly_pipeline import PipelineValidationError
from src.paper_trading import (
    PAPER_STATUSES,
    PaperTradingError,
)
from src.strategies import strategy_names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="main.py", description="personal-quant-lab CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("monthly-report", help="Génère le rapport mensuel (Markdown + JSON).")
    report.add_argument("--report-date", default=None, help="Date d'arrêté YYYY-MM-DD (défaut : dernière dispo).")
    report.add_argument("--refresh-data", action="store_true", help="Télécharge les données (sinon local).")
    report.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Dossier de sortie.")
    report.add_argument("--config", default=str(DEFAULT_CONFIG), help="Fichier de configuration.")
    report.add_argument("--assets", default=str(DEFAULT_ASSETS), help="Fichier d'univers (rôles des actifs).")
    report.add_argument("--data", default=str(DEFAULT_DATA), help="Fichier de prix local.")
    report.add_argument("--html", action="store_true", help="Exporte aussi un HTML autonome (images intégrées).")
    report.add_argument("--policy", default=str(DEFAULT_POLICY), help="Politique d'investissement.")
    report.set_defaults(func=_cmd_monthly_report)

    run_month = sub.add_parser("run-month", help="Routine mensuelle : rapport + journal + comparaison.")
    run_month.add_argument("--report-date", default=None, help="Date d'arrêté YYYY-MM-DD (défaut : dernière dispo).")
    run_month.add_argument("--refresh-data", action="store_true", help="Télécharge les données avant le rapport.")
    run_month.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Dossier des rapports mensuels.")
    run_month.add_argument("--paper-dir", default=str(DEFAULT_PAPER_DIR), help="Dossier du journal.")
    run_month.add_argument("--config", default=str(DEFAULT_CONFIG), help="Fichier de configuration.")
    run_month.add_argument("--assets", default=str(DEFAULT_ASSETS), help="Fichier d'univers.")
    run_month.add_argument("--data", default=str(DEFAULT_DATA), help="Fichier de prix local.")
    run_month.add_argument("--html", action="store_true",
                           help="Exporte aussi le rapport et un résumé du mois en HTML autonome (téléphone).")
    run_month.add_argument("--transactions", default=str(DEFAULT_TRANSACTIONS),
                           help="Journal de transactions (résumé du portefeuille réel).")
    run_month.add_argument("--notify", action="store_true",
                           help="Envoie les notifications ntfy si config/notify.yaml les active.")
    run_month.add_argument("--notify-config", default=str(DEFAULT_NOTIFY), help="Configuration ntfy.")
    run_month.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR), help="Dossier du journal des notifications.")
    run_month.add_argument("--policy", default=str(DEFAULT_POLICY), help="Politique d'investissement.")
    run_month.set_defaults(func=_cmd_run_month)

    status = sub.add_parser("status", help="État du lab (données, rapports, journal) et prochaines actions.")
    status.add_argument("--data", default=str(DEFAULT_DATA), help="Fichier de prix local.")
    status.add_argument("--assets", default=str(DEFAULT_ASSETS), help="Fichier d'univers.")
    status.add_argument("--monthly-dir", default=str(DEFAULT_OUTPUT_DIR), help="Dossier des rapports mensuels.")
    status.add_argument("--paper-dir", default=str(DEFAULT_PAPER_DIR), help="Dossier du journal.")
    status.set_defaults(func=_cmd_status)

    patrimoine = sub.add_parser("patrimoine", help="Rapport patrimonial (enveloppes, dérive, projections).")
    patrimoine.add_argument("--config", default=str(DEFAULT_PATRIMOINE), help="Configuration patrimoniale.")
    patrimoine.add_argument("--holdings", default=str(DEFAULT_HOLDINGS), help="Valeurs personnelles (non versionnées).")
    patrimoine.add_argument("--output", default=str(DEFAULT_REPORTS_DIR / "patrimoine_report.md"))
    patrimoine.add_argument("--positions", default=str(DEFAULT_POSITIONS), help="Positions réelles (non versionnées).")
    patrimoine.add_argument("--transactions", default=str(DEFAULT_TRANSACTIONS), help="Journal de transactions.")
    patrimoine.add_argument("--data", default=str(DEFAULT_DATA), help="Fichier de prix local.")

    plan = sub.add_parser("plan-contribution", help="Proposition d'achats du versement mensuel (aucun ordre).")
    plan.add_argument("--amount", type=float, default=None, help="Versement en € (défaut : patrimoine.yaml).")
    plan.add_argument("--envelope", default="pea", help="Enveloppe concernée (défaut : pea).")
    plan.add_argument("--strategy", default=None, choices=strategy_names(),
                      help="Forcer la stratégie cible (défaut : dernière décision approuvée).")
    plan.add_argument("--positions", default=str(DEFAULT_POSITIONS), help="Positions réelles (non versionnées).")
    plan.add_argument("--transactions", default=str(DEFAULT_TRANSACTIONS), help="Journal de transactions (prioritaire).")
    plan.add_argument("--paper-dir", default=str(DEFAULT_PAPER_DIR), help="Dossier du journal.")
    plan.add_argument("--data", default=str(DEFAULT_DATA), help="Fichier de prix local.")
    plan.add_argument("--config", default=str(DEFAULT_CONFIG), help="Fichier de configuration (frais).")
    plan.add_argument("--output-dir", default=str(DEFAULT_REPORTS_DIR / "contributions"), help="Dossier des plans.")
    plan.add_argument("--record", action="store_true",
                      help="Ajoute les achats proposés à config/pending_orders.csv (statut PROPOSE, jamais exécutés).")
    plan.add_argument("--pending", default=str(DEFAULT_PENDING), help="Fichier des ordres proposés.")
    plan.add_argument("--no-vehicle-switch", action="store_true",
                      help="Ne pas basculer vers un véhicule de même exposition moins cher.")
    plan.add_argument("--policy", default=str(DEFAULT_POLICY),
                      help="Politique : une allocation fixe y est utilisée directement comme cible.")
    plan.add_argument("--frequency", type=int, default=None,
                      help="Achat tous les N mois (défaut : patrimoine.yaml > profil > frequence_achat_mois, sinon 1).")
    plan.add_argument("--month", default=None, help="Mois du plan AAAA-MM (défaut : mois courant).")
    plan.add_argument("--simulation", action="store_true", help="Proposition hypothétique sans validation du compte réel.")
    plan.add_argument("--credited", action="store_true", help="Versement déjà inclus dans le cash du journal : ne pas le rajouter.")
    plan.add_argument("--as-of", default=None, help="Date de simulation historique, requiert --simulation.")
    plan.add_argument("--reconciliation", default=str(DEFAULT_CONFIG.parent / "reconciliation.json"))
    plan.set_defaults(func=_cmd_plan_contribution)

    port = sub.add_parser("portfolio", help="Portefeuille réel : performance, frais, règles du PEA (personnel).")
    port.add_argument("--transactions", default=str(DEFAULT_TRANSACTIONS), help="Journal de transactions.")
    port.add_argument("--positions", default=str(DEFAULT_POSITIONS), help="Positions (repli).")
    port.add_argument("--envelope", default="pea", help="Enveloppe analysée.")
    port.add_argument("--data", default=str(DEFAULT_DATA), help="Fichier de prix local.")
    port.add_argument("--config", default=str(DEFAULT_CONFIG), help="Fichier de configuration.")
    port.add_argument("--paper-dir", default=str(DEFAULT_PAPER_DIR), help="Dossier du journal paper.")
    port.add_argument("--output", default=str(DEFAULT_REPORTS_DIR / "portfolio_report.md"), help="Rapport (personnel).")
    port.set_defaults(func=_cmd_portfolio)

    uni = sub.add_parser("universe", help="Identité des ETF de l'univers (ISIN, frais, PEA) et points d'attention.")
    uni.add_argument("--assets", default=str(DEFAULT_ASSETS), help="Fichier d'univers.")
    uni.set_defaults(func=_cmd_universe)

    veh = sub.add_parser("vehicles", help="Expositions, véhicules achetables et écart de suivi des proxys.")
    veh.add_argument("--assets", default=str(DEFAULT_ASSETS), help="Fichier d'univers.")
    veh.add_argument("--data", default=str(DEFAULT_DATA), help="Fichier de prix local.")
    veh.set_defaults(func=_cmd_vehicles)
    patrimoine.set_defaults(func=_cmd_patrimoine)

    for name, func, output, help_text in (
        ("dca", _cmd_dca, "dca_report.md", "Simulation des versements mensuels (Projet 1B)."),
        ("regime", _cmd_regime, "market_regime_report.md", "Étude ML des régimes de marché (Projet 5)."),
        ("costs", _cmd_costs, "costs_report.md", "Sensibilité des stratégies aux frais de transaction."),
        ("stress", _cmd_stress, "research/stress_report.md",
         "Stress tests de crise et distribution des versements sur historique long."),
        ("robustness", _cmd_robustness, "research/robustness_report.md",
         "Robustesse des stratégies sur historique long : verdicts, plateaux, walk-forward, tests multiples."),
        ("research", _cmd_research, "research/strategy_research_report.md",
         "Robustesse des stratégies : grille walk-forward, alternatives, intervalles de confiance."),
    ):
        research = sub.add_parser(name, help=help_text)
        research.add_argument("--config", default=str(DEFAULT_CONFIG), help="Fichier de configuration.")
        research.add_argument("--assets", default=str(DEFAULT_ASSETS), help="Fichier d'univers.")
        research.add_argument("--data", default=str(DEFAULT_DATA), help="Fichier de prix local.")
        research.add_argument("--output", default=str(DEFAULT_REPORTS_DIR / output), help="Rapport Markdown.")
        if name == "research":
            research.add_argument("--portfolio", type=float, default=10_000.0,
                                  help="Taille de portefeuille pour convertir le barème réel en taux (défaut 10 000 €).")
            research.add_argument("--long", action="store_true",
                                  help="Utilise l'historique long (partiellement synthétique) au lieu des données réelles.")
            research.add_argument("--long-config", default=str(DEFAULT_LONG_CONFIG), help="Chaînes de proxys.")
            research.add_argument("--long-data", default=str(DEFAULT_LONG_PRICES), help="Fichier de l'historique long.")
        if name == "robustness":
            research.add_argument("--long-config", default=str(DEFAULT_LONG_CONFIG), help="Chaînes de proxys.")
            research.add_argument("--long-data", default=str(DEFAULT_LONG_PRICES), help="Fichier de l'historique long.")
        if name == "stress":
            research.add_argument("--long-config", default=str(DEFAULT_LONG_CONFIG), help="Chaînes de proxys.")
            research.add_argument("--long-data", default=str(DEFAULT_LONG_PRICES), help="Fichier de l'historique long.")
            research.add_argument("--monthly", type=float, default=None, help="Versement mensuel (défaut : patrimoine).")
            research.add_argument("--years", type=int, default=None, help="Horizon en années (défaut : politique).")
            research.add_argument("--sims", type=int, default=2000, help="Nombre de trajectoires simulées.")
        if name == "dca":
            research.add_argument("--monthly", type=float, default=None,
                                  help="Versement mensuel en € (défaut : patrimoine.yaml).")
            research.add_argument("--start", default=None, help="Premier mois YYYY-MM-DD (défaut : historique commun).")
        research.add_argument("--policy", default=str(DEFAULT_POLICY), help="Politique d'investissement.")
        research.set_defaults(func=func)

    plans = sub.add_parser("plans", help="Plans d'investissement simulés pour le profil (projections, passé, adéquation).")
    plans.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Profil personnel (config/profil.yaml).")
    plans.add_argument("--plans", default=str(DEFAULT_PLANS), help="Définition des plans.")
    plans.add_argument("--only", default=None, help="Identifiants de plans séparés par des virgules.")
    plans.add_argument("--monthly", type=float, default=None, help="Versement mensuel (remplace le profil).")
    plans.add_argument("--capital", type=float, default=None, help="Capital de départ (remplace le profil).")
    plans.add_argument("--years", type=int, default=None, help="Horizon en années (remplace le profil).")
    plans.add_argument("--goal", type=float, default=None, help="Capital visé en euros d'aujourd'hui.")
    plans.add_argument("--sims", type=int, default=None, help="Nombre de trajectoires (défaut : plans.yaml).")
    plans.add_argument("--scenario", default=None,
                       help="Scénario de rendement : historique, central, defavorable (défaut : plans.yaml).")
    plans.add_argument("--prudent", action="store_true", help="Raccourci de --scenario defavorable.")
    plans.add_argument("--config", default=str(DEFAULT_CONFIG), help="Fichier de configuration.")
    plans.add_argument("--assets", default=str(DEFAULT_ASSETS), help="Fichier d'univers.")
    plans.add_argument("--policy", default=str(DEFAULT_POLICY), help="Politique d'investissement.")
    plans.add_argument("--patrimoine", default=str(DEFAULT_PATRIMOINE), help="Fiscalité (patrimoine.yaml).")
    plans.add_argument("--long-config", default=str(DEFAULT_LONG_CONFIG), help="Chaînes de proxys.")
    plans.add_argument("--long-data", default=str(DEFAULT_LONG_PRICES), help="Fichier de l'historique long.")
    plans.add_argument("--crypto", default=str(DEFAULT_CRYPTO), help="Prix crypto quotidiens (EUR).")
    plans.add_argument("--output", default=str(DEFAULT_PLANS_REPORT), help="Rapport Markdown (personnel).")
    plans.set_defaults(func=_cmd_plans)

    fees = sub.add_parser("frais", help="Audit des frais : ordres, frais des ETF, fiscalité (personnel).")
    fees.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Profil personnel.")
    fees.add_argument("--policy", default=str(DEFAULT_POLICY), help="Politique (allocation suivie).")
    fees.add_argument("--config", default=str(DEFAULT_CONFIG), help="Barème du courtier (costs).")
    fees.add_argument("--plans", default=str(DEFAULT_PLANS), help="Scénarios (rendement supposé).")
    fees.add_argument("--patrimoine", default=str(DEFAULT_PATRIMOINE), help="Fiscalité.")
    fees.add_argument("--data", default=str(DEFAULT_DATA), help="Fichier de prix local (prix actuels).")
    fees.add_argument("--assets", default=str(DEFAULT_ASSETS), help="Fichier d'univers (frais des ETF, véhicules).")
    fees.add_argument("--output", default=str(DEFAULT_FEES_REPORT), help="Rapport Markdown (personnel).")
    fees.set_defaults(func=_cmd_fees)

    maxr = sub.add_parser("rendement-max", help="Gains et pertes possibles d'options plus risquées (pédagogique).")
    maxr.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Profil personnel (versement, horizon).")
    maxr.add_argument("--policy", default=str(DEFAULT_POLICY), help="Politique (ton plan de référence).")
    maxr.add_argument("--config", default=str(DEFAULT_CONFIG), help="Configuration et frais.")
    maxr.add_argument("--plans", default=str(DEFAULT_PLANS), help="Hypothèses et scénarios.")
    maxr.add_argument("--patrimoine", default=str(DEFAULT_PATRIMOINE), help="Fiscalité.")
    maxr.add_argument("--assets", default=str(DEFAULT_ASSETS), help="Fichier d'univers.")
    maxr.add_argument("--long-config", default=str(DEFAULT_LONG_CONFIG), help="Chaînes de proxys.")
    maxr.add_argument("--long-data", default=str(DEFAULT_LONG_PRICES), help="Fichier de l'historique long.")
    maxr.add_argument("--sims", type=int, default=None, help="Nombre de trajectoires (défaut 1000).")
    maxr.add_argument("--output", default=str(DEFAULT_MAX_RETURN_REPORT), help="Rapport Markdown (personnel).")
    maxr.set_defaults(func=_cmd_max_return)

    cards = sub.add_parser("strategies", help="Fiches détaillées des stratégies (mécanismes, mesures, crises).")
    cards.add_argument("--robustness", default=str(DEFAULT_REPORTS_DIR / "research" / "robustness_report.json"),
                       help="Résultats de main.py robustness.")
    cards.add_argument("--stress", default=str(DEFAULT_REPORTS_DIR / "research" / "stress_report.json"),
                       help="Résultats de main.py stress.")
    cards.add_argument("--output", default=str(DEFAULT_REPORTS_DIR / "research" / "strategy_cards.md"),
                       help="Rapport Markdown.")
    cards.set_defaults(func=_cmd_strategies)

    prof = sub.add_parser("profile", help="Profil investisseur : questionnaire et repères (personnel, aucun conseil).")
    prof.add_argument("--profile", default=str(DEFAULT_PROFILE), help="Profil personnel (config/profil.yaml).")
    prof.add_argument("--questionnaire", action="store_true", help="Répondre au questionnaire interactif.")
    prof.add_argument("--init", action="store_true", help="Créer le profil à partir du modèle versionné.")
    prof.set_defaults(func=_cmd_profile)

    pol = sub.add_parser("policy", help="Affiche la politique d'investissement et ses contrôles informatifs.")
    pol.add_argument("--policy", default=str(DEFAULT_POLICY), help="Politique d'investissement.")
    pol.add_argument("--research", default=str(DEFAULT_REPORTS_DIR / "research" / "strategy_research_report.json"),
                     help="Résumé JSON de l'étude de recherche.")
    pol.add_argument("--monthly-dir", default=str(DEFAULT_OUTPUT_DIR), help="Dossier des rapports mensuels.")
    pol.set_defaults(func=_cmd_policy)

    refresh = sub.add_parser("refresh-data", help="Télécharge, valide et sauvegarde les prix de l'univers.")
    refresh.add_argument("--assets", default=str(DEFAULT_ASSETS), help="Fichier d'univers.")
    refresh.add_argument("--data", default=str(DEFAULT_DATA), help="Fichier de prix de sortie.")
    refresh.add_argument("--full", action="store_true", help="Retélécharge tout l'historique (sinon incrémental).")
    refresh.add_argument("--long", action="store_true",
                         help="Construit aussi l'historique long par proxys (recherche, données synthétiques).")
    refresh.add_argument("--long-config", default=str(DEFAULT_LONG_CONFIG), help="Chaînes de proxys.")
    refresh.add_argument("--long-data", default=str(DEFAULT_LONG_PRICES), help="Fichier de l'historique long.")
    refresh.set_defaults(func=_cmd_refresh_data)

    validate = sub.add_parser("validate", help="Valide la configuration.")
    validate.add_argument("--config", default=str(DEFAULT_CONFIG))
    validate.set_defaults(func=_cmd_validate)

    # --- Paper trading (Projet 4B) ---
    p_init = sub.add_parser("paper-init", help="Crée une entrée de paper trading (statut PENDING).")
    p_init.add_argument("--snapshot", required=True, help="Snapshot JSON mensuel source.")
    p_init.add_argument("--output-dir", default=str(DEFAULT_PAPER_DIR), help="Dossier du journal.")
    p_init.add_argument("--force", action="store_true", help="Écrase une entrée existante approuvée.")
    p_init.set_defaults(func=_cmd_paper_init)

    p_list = sub.add_parser("paper-list", help="Liste les entrées du journal de paper trading.")
    p_list.add_argument("--paper-dir", default=str(DEFAULT_PAPER_DIR), help="Dossier du journal.")
    p_list.set_defaults(func=_cmd_paper_list)

    p_cmp = sub.add_parser("compare-reports", help="Compare deux rapports mensuels.")
    p_cmp.add_argument("--from", dest="from_month", default=None, help="Mois source YYYY-MM.")
    p_cmp.add_argument("--to", dest="to_month", default=None, help="Mois cible YYYY-MM.")
    p_cmp.add_argument("--previous", default=None, help="Snapshot JSON précédent (alternative à --from).")
    p_cmp.add_argument("--current", default=None, help="Snapshot JSON courant (alternative à --to).")
    p_cmp.add_argument("--monthly-dir", default=str(DEFAULT_OUTPUT_DIR), help="Dossier des rapports mensuels.")
    p_cmp.add_argument("--output", default=None, help="Sauvegarde la comparaison en JSON.")
    p_cmp.set_defaults(func=_cmd_compare_reports)

    p_dec = sub.add_parser("paper-decision", help="Enregistre une décision humaine (paper trading uniquement).")
    p_dec.add_argument("--month", required=True, help="Mois de l'entrée YYYY-MM.")
    p_dec.add_argument("--status", required=True, choices=PAPER_STATUSES, help="Statut de décision.")
    p_dec.add_argument("--strategy", default=None, help="Stratégie suivie (pour APPROVED_PAPER).")
    p_dec.add_argument("--comment", default=None, help="Commentaire libre.")
    p_dec.add_argument("--paper-dir", default=str(DEFAULT_PAPER_DIR), help="Dossier du journal.")
    p_dec.add_argument("--confidence", type=int, choices=range(1, 6), default=None,
                       help="Niveau de confiance de 1 (faible) à 5 (fort).")
    p_dec.add_argument("--pros", default=None, help="Arguments pour agir.")
    p_dec.add_argument("--cons", default=None, help="Arguments contre agir.")
    p_dec.add_argument("--next-check", dest="next_check", default=None,
                       help="Ce que je vérifierai le mois prochain.")
    p_dec.set_defaults(func=_cmd_paper_decision)

    p_perf = sub.add_parser("paper-performance", help="Performance fictive de mes décisions vs système et benchmark.")
    p_perf.add_argument("--paper-dir", default=str(DEFAULT_PAPER_DIR), help="Dossier du journal.")
    p_perf.add_argument("--data", default=str(DEFAULT_DATA), help="Fichier de prix local.")
    p_perf.add_argument("--config", default=str(DEFAULT_CONFIG), help="Fichier de configuration.")
    p_perf.add_argument("--assets", default=str(DEFAULT_ASSETS), help="Fichier d'univers.")
    p_perf.add_argument("--output", default=str(DEFAULT_PAPER_DIR / "performance.md"), help="Rapport Markdown.")
    p_perf.set_defaults(func=_cmd_paper_performance)
    from src.cli.pea_cmds import register

    register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Évite un plantage d'encodage quand la sortie est redirigée (journal, tâche planifiée).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse sort en 2 sur erreur d'usage : on réserve 2 au statut CRITICAL.
        return 1 if exc.code not in (0, None) else 0
    try:
        return args.func(args)
    except PipelineValidationError as exc:
        print(f"ERREUR CRITIQUE : {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError, PaperTradingError) as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1

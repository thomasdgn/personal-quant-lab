"""Commandes de recherche : frais, robustesse, régimes ML."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.cli.common import (
    DEFAULT_PATRIMOINE,
    _load_asset_roles,
    _load_prices,
    _long_universe,
    _pipeline_for_research,
    _strategy_context,
)
from src.costs import load_fee_model
from src.monthly_pipeline import load_config


def _cmd_costs(args: argparse.Namespace) -> int:
    from src.cost_sensitivity import generate_cost_report, run_cost_sensitivity

    config = load_config(args.config)
    prices = _load_prices(Path(args.data), Path(args.assets), False)
    fee_model = load_fee_model(args.config)
    table = run_cost_sensitivity(prices, config, asset_roles=_load_asset_roles(Path(args.assets)),
                                 fee_model=fee_model)
    path = generate_cost_report(table, fee_model, Path(args.output))
    print("Sensibilité aux frais (backtests complets, aucun ordre)")
    for _, row in table.iterrows():
        cagr = "n/a" if row["CAGR"] is None else f"{row['CAGR']:.2%}"
        print(f"  {row['scénario'][:42]:42} {row['stratégie'][:32]:32} CAGR {cagr}")
    print(f"Rapport : {path}")
    return 0


def _cmd_research(args: argparse.Namespace) -> int:
    from src.features import to_monthly_prices
    from src.research import conclusion_lines, generate_research_report, run_research, save_heatmap

    roles = _load_asset_roles(Path(args.assets))
    realistic = load_fee_model(args.config).effective_rate(args.portfolio)
    output = Path(args.output)
    data_note = None
    if args.long:
        from src.long_history import load_long_config, load_long_history

        config = load_config(args.config)
        long_prices, _ = load_long_history(args.long_data, Path(args.long_data).with_name("long_history_sources.csv"))
        monthly = _long_universe(long_prices, roles, load_long_config(args.long_config))
        cash_return: float | pd.Series = config.backtest.cash_return
        if output.name == "strategy_research_report.md":
            output = output.with_name("strategy_research_report_long.md")
        data_note = ("historique long partiellement SYNTHÉTIQUE (proxys de même exposition avant la cotation des "
                     "ETF PEA, voir config/long_history.yaml) ; cash non rémunéré.")
    else:
        config, prices, result = _pipeline_for_research(args)
        monthly = result.monthly_prices
        cash_return = config.backtest.cash_return
        proxy = next((t for t, r in roles.items() if r == "cash_proxy"), None)
        if config.universe.use_cash_proxy_return and proxy in prices.columns:
            cash_return = (to_monthly_prices(prices[proxy]).reindex(monthly.index).pct_change(fill_method=None)
                           .fillna(config.backtest.cash_return))
    study = run_research(monthly, config, roles=roles, cash_return=cash_return, realistic_cost=realistic)
    heatmap = save_heatmap(study, output.parent / "figures" / f"grid_sharpe{'_long' if args.long else ''}.png")
    generate_research_report(study, output, heatmap=heatmap, data_note=data_note)
    from src.research import save_research_json

    study["data_note"] = data_note
    save_research_json(study, output.with_suffix(".json"))
    print(f"Recherche de robustesse : {study['start']} -> {study['end']} ({study['n_months']} mois, "
          f"{study['n_strategies_tested']} variantes testées). Aucun ordre, aucune stratégie modifiée.")
    for name, item in study["results"].items():
        stats, vs = item["stats"], item["vs_benchmark"]
        gap = "" if vs is None else f" | écart Sharpe {vs['diff']:+.2f} [{vs['low']:+.2f} ; {vs['high']:+.2f}]"
        sharpe = "n/a" if stats["sharpe"] is None else f"{stats['sharpe']:.2f}"
        print(f"  {name:22} CAGR {stats['cagr']:7.2%}  Sharpe {sharpe}{gap}")
    for line in conclusion_lines(study):
        print(line.replace("« ", '"').replace(" »", '"'))
    print(f"Rapport : {output}")
    return 0


def _cmd_stress(args: argparse.Namespace) -> int:
    import json

    from src.long_history import load_long_config, load_long_history
    from src.patrimoine import load_patrimoine_config
    from src.policy import load_policy
    from src.stress import generate_stress_report, run_stress, save_stress_json
    from src.taxes import tax_config_from

    config = load_config(args.config)
    policy = load_policy(args.policy)
    roles = _load_asset_roles(Path(args.assets))
    long_prices, sources = load_long_history(args.long_data, Path(args.long_data).with_name("long_history_sources.csv"))
    monthly = _long_universe(long_prices, roles, load_long_config(args.long_config))
    patrimoine = load_patrimoine_config(DEFAULT_PATRIMOINE)
    contribution = args.monthly or float(patrimoine["profil"]["versement_mensuel_eur"])
    horizon = int(args.years or policy.horizon_ans) * 12
    study = run_stress(monthly, sources, _strategy_context(config, roles, monthly.columns, policy),
                       transaction_cost=config.backtest.transaction_cost, monthly_contribution=contribution,
                       horizon_months=horizon, fee_model=load_fee_model(args.config),
                       taxes=tax_config_from(patrimoine), drawdown_limit=policy.drawdown_max_accepte,
                       followed=policy.strategie_suivie, n_sims=args.sims)
    research_dir = Path(args.output).parent
    load = lambda name: json.loads((research_dir / name).read_text(encoding="utf-8")) \
        if (research_dir / name).exists() else None  # noqa: E731
    path = generate_stress_report(study, Path(args.output), research_short=load("strategy_research_report.json"),
                                  research_long=load("strategy_research_report_long.json"),
                                  proxy_chains=load_long_config(args.long_config)["chains"])
    save_stress_json(study, Path(args.output).with_suffix(".json"))
    print(f"Stress tests sur historique long {study['start']} -> {study['end']} (partiellement SYNTHÉTIQUE).")
    print(f"Versements : {contribution:,.0f} EUR/mois sur {horizon // 12} ans, {args.sims} trajectoires simulées.")
    for name, item in study["outcomes"].items():
        mark = " (suivie)" if name == policy.strategie_suivie else ""
        print(f"  {name:15}{mark:9} valeur nette médiane {item['final_net']['p50']:>12,.0f} EUR "
              f"[p5 {item['final_net']['p5']:,.0f} ; p95 {item['final_net']['p95']:,.0f}] "
              f"P(DD > {policy.drawdown_max_accepte:.0%}) {item['prob_drawdown_beyond_limit']:.0%}")
    print(f"Rapport : {path}")
    return 0


def _cmd_regime(args: argparse.Namespace) -> int:
    from src.market_regime import generate_regime_report, run_regime_study

    config, prices, result = _pipeline_for_research(args)
    study = run_regime_study(prices, result.monthly_prices, config)
    generate_regime_report(study["evaluation"], study["backtest"], Path(args.output), study["walk_forward"])
    current = study["walk_forward"]["current"]
    verdicts = study["walk_forward"]["financial"]["verdict"]
    print("Étude ML des régimes de marché (expérimental, aucun ordre exécuté)")
    print(f"Régime au {current['signal_date']} : probabilité favorable {current['probability_logistic']:.1%} "
          f"(exposition indicative {current['exposure_logistic']:.0%})")
    for overlay, verdict in verdicts.items():
        print(f"  {overlay:13}: {'utile' if verdict['useful'] else 'non retenu'} ({verdict['reason']})")
    print(f"Rapport : {args.output}")
    return 0


def _cmd_policy(args: argparse.Namespace) -> int:
    """Affiche la politique et des contrôles informatifs (aucune modification)."""
    import json

    from src.paper_trading import list_monthly_snapshots, load_monthly_snapshot
    from src.policy import load_policy, policy_checks

    policy = load_policy(args.policy)
    research_path = Path(args.research)
    research = json.loads(research_path.read_text(encoding="utf-8")) if research_path.exists() else None
    snapshots = list_monthly_snapshots(args.monthly_dir)
    snapshot = load_monthly_snapshot(snapshots[-1]) if snapshots else None
    print(f"Politique d'investissement ({args.policy})")
    print(f"  Objectif            : {policy.objectif}")
    print(f"  Horizon             : {policy.horizon_ans} ans")
    print(f"  Stratégie suivie    : {policy.strategie_suivie}")
    if policy.strategie_suivie == "core_satellite":
        print(f"  Cœur / satellite    : {policy.part_coeur:.0%} benchmark + {1 - policy.part_coeur:.0%} {policy.satellite}")
    print(f"  Drawdown max accepté: {policy.drawdown_max_accepte:.0%}")
    print(f"  Rééquilibrage       : {policy.reequilibrage} (bande {policy.bande_tolerance_pct:g} pts) ; revue {policy.revue}")
    if policy.allocation_fixe:
        print("  Allocation fixe     : " + ", ".join(f"{t} {w:.0%}" for t, w in policy.allocation_fixe.items())
              + (f" (plan {policy.plan_suivi})" if policy.plan_suivi else ""))
    if policy.regle_krach:
        print(f"  Règle de krach      : seuil {policy.seuil_krach:.0%} ; \"{policy.regle_krach}\"")
    followed = ((snapshot or {}).get("strategies") or {}).get(policy.strategie_suivie)
    if followed:
        weights = ", ".join(f"{k} {v:.0%}" for k, v in followed["target_weights"].items() if v and v > 1e-9)
        month = ((snapshot or {}).get("metadata") or {}).get("report_month")
        print(f"  Allocation cible ({month}) : {weights or 'cash'}")
    print("Contrôles (informatifs, la politique n'est jamais modifiée automatiquement)")
    for check in policy_checks(policy, research, snapshot):
        print(f"  [{check['level']}] {check['message']}")
    return 0


def _cmd_robustness(args: argparse.Namespace) -> int:
    from src.long_history import load_long_config, load_long_history
    from src.policy import load_policy
    from src.robustness import conclusion_lines, generate_robustness_report, run_robustness, save_robustness_json
    from src.stress import synthetic_share_by_month

    config = load_config(args.config)
    policy = load_policy(args.policy)
    roles = _load_asset_roles(Path(args.assets))
    long_prices, sources = load_long_history(args.long_data, Path(args.long_data).with_name("long_history_sources.csv"))
    monthly = _long_universe(long_prices, roles, load_long_config(args.long_config))
    study = run_robustness(monthly, _strategy_context(config, roles, monthly.columns, policy),
                           transaction_cost=config.backtest.transaction_cost,
                           synthetic=synthetic_share_by_month(sources, list(monthly.columns)),
                           followed=policy.strategie_suivie)
    path = generate_robustness_report(study, Path(args.output))
    save_robustness_json(study, Path(args.output).with_suffix(".json"))
    print(f"Robustesse sur historique long {study['start']} -> {study['end']} ({study['n_months']} mois, "
          f"{study['n_trials']} variantes, partiellement SYNTHÉTIQUE). Aucun ordre, aucune stratégie modifiée.")
    for name, item in study["strategies"].items():
        edge = (item["edge"] or {}).get("verdict", "référence")
        protection = (item["protection"] or {}).get("verdict", "référence")
        sharpe = "n/a" if item["stats"]["sharpe"] is None else f"{item['stats']['sharpe']:.2f}"
        print(f"  {name:15} fiabilité {item['verdict']:10} ({item['score']:4.0%})  Sharpe {sharpe}  "
              f"surperformance {edge:13}  protection {protection}")
    for line in conclusion_lines(study):
        print(line.replace("« ", '"').replace(" »", '"'))
    print(f"Rapport : {path}")
    return 0


def _cmd_strategies(args: argparse.Namespace) -> int:
    from src.strategy_cards import CARDS, generate_cards_report

    path = generate_cards_report(Path(args.output), Path(args.robustness), Path(args.stress))
    print("Fiches des stratégies (mécanismes et mesures ; aucune recommandation, aucun ordre)")
    for name, card in CARDS.items():
        print(f"  {name:15} {card['temps']:14} complexité {card['complexite']}/4  {card['resume']}")
    if not Path(args.robustness).exists():
        print("Mesures absentes : lancer `python main.py robustness` puis `python main.py stress`.")
    print(f"Rapport : {path}")
    return 0

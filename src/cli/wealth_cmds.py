"""Commandes patrimoine, plan de versement (proposition) et DCA."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from src.cli.common import (
    DEFAULT_ASSETS,
    DEFAULT_PATRIMOINE,
    _current_positions,
    _load_prices,
    _pipeline_for_research,
)
from src.contribution_plan import generate_plan_report, plan_contribution, plan_lines, resolve_target
from src.costs import load_fee_model
from src.dca import generate_dca_report, run_dca_comparison
from src.paper_trading import (
    load_paper_entries,
)
from src.patrimoine import generate_patrimoine_report, load_holdings, load_patrimoine_config
from src.positions import value_positions
from src.taxes import tax_config_from


def _cmd_patrimoine(args: argparse.Namespace) -> int:
    config = load_patrimoine_config(args.config)
    values, as_of = load_holdings(args.holdings)
    positions, position_notes = _current_positions(args.positions, args.transactions)
    for note in position_notes:
        print(f"Note : {note}")
    if positions is not None:
        valuation = value_positions(positions, _load_prices(Path(args.data), DEFAULT_ASSETS, False))
        known = {e["id"] for e in config["enveloppes"]}
        for envelope, totals in valuation["enveloppes"].items():
            if envelope in known:
                values[envelope] = totals["total"]
                print(f"Valeur {envelope} issue des positions (prix de marché) : {totals['total']:,.2f} €")
        as_of = positions["date"] or as_of
    if not values:
        print(f"Note : {args.holdings} absent ou vide — copie config/holdings.example.yaml et renseigne tes valeurs.")
    result = generate_patrimoine_report(config, values, Path(args.output), values_date=as_of)
    allocation = result["allocation"]
    print("Rapport patrimonial généré (aucun ordre exécuté)")
    print(f"Total suivi      : {allocation['total_eur']:,.2f} €")
    for kind, pct in allocation["current_pct"].items():
        print(f"  {kind:11}    : {pct:6.2f} % (cible {allocation['target_pct'][kind]:.0f} %)")
    print(f"Recommandation   : {result['recommendation']}")
    print(f"Rapport          : {result['report_path']}")
    return 0


def _cmd_plan_contribution(args: argparse.Namespace) -> int:
    patrimoine = load_patrimoine_config(DEFAULT_PATRIMOINE)
    amount = args.amount if args.amount is not None else float(patrimoine["profil"]["versement_mensuel_eur"])
    if getattr(args, "credited", False):
        amount = 0.0
    if getattr(args, "as_of", None) and not getattr(args, "simulation", False):
        raise ValueError("--as-of requiert --simulation : une date historique ne valide pas une proposition actuelle.")
    from src.policy import load_policy

    policy = load_policy(args.policy)
    if policy.strategie_suivie == "allocation_fixe" and not args.strategy:
        # Allocation fixe de la politique : pas besoin du journal (poids connus, sans cash).
        target: dict[str, Any] = {"strategy": "allocation_fixe", "weights": dict(policy.allocation_fixe),
                                  "report_month": None, "source": "politique",
                  "signal_date": None, "from_decision": False}
        print("Cible : allocation fixe de la politique (config/policy.yaml) : "
              + ", ".join(f"{t} {w:.0%}" for t, w in policy.allocation_fixe.items()) + ".")
    else:
        target = resolve_target(load_paper_entries(Path(args.paper_dir)))
    if args.strategy:
        weights = (sorted(load_paper_entries(Path(args.paper_dir)), key=lambda e: e["report_month"])[-1]
                   .get("target_weights") or {}).get(args.strategy)
        # (stratégies du registre disponibles dans les entrées de schéma 1.3)
        if not weights:
            raise ValueError(f"Stratégie {args.strategy} absente de la dernière entrée du journal.")
        target = {**target, "strategy": args.strategy, "weights": {k: float(v) for k, v in weights.items() if v},
                  "from_decision": True}
    current, position_notes = _current_positions(args.positions, args.transactions)
    positions = current or {"date": None, "lignes": [], "liquidites_eur": {}}
    for note in position_notes:
        print(f"Note : {note}")
    if not positions["lignes"] and not positions["liquidites_eur"]:
        print(f"Note : {args.positions} absent — plan calculé pour un portefeuille vide "
              "(modèle : config/positions.example.yaml).")
    prices = _load_prices(Path(args.data), DEFAULT_ASSETS, False)
    if getattr(args, "as_of", None):
        prices = prices.loc[:args.as_of]
    valuation = value_positions(positions, prices)
    quotes = valuation["lignes"].set_index("ticker")["prix"].to_dict() if not valuation["lignes"].empty else {}
    from src.positions import last_prices

    latest = last_prices(prices)["prix"].to_dict()
    for ticker, price in latest.items():
        quotes.setdefault(ticker, price)
    holdings = {row["ticker"]: row["parts"] for _, row in valuation["lignes"].iterrows()
                if row["enveloppe"] == args.envelope}
    cash = valuation["enveloppes"].get(args.envelope, {}).get("liquidites", 0.0)
    plan_weights: dict[str, float] = dict(target["weights"])
    vehicle_notes: list[str] = []
    if not args.no_vehicle_switch:
        from src.universe import load_universe
        from src.vehicles import map_target_to_vehicles

        holdings_value = {t: parts * quotes.get(t, 0.0) for t, parts in holdings.items()}
        plan_weights, vehicle_notes = map_target_to_vehicles(target["weights"], holdings_value, quotes,
                                                        load_universe(DEFAULT_ASSETS), amount + cash)
        target = {**target, "weights": plan_weights}
    quotes = {t: q for t, q in quotes.items() if t in plan_weights or t in holdings}
    fees = load_fee_model(args.config)
    if fees.tariff != "generic" and not getattr(args, "simulation", False):
        import yaml
        from src.broker import load_broker_profile
        from src.pea_account import readiness
        from src.universe import load_universe

        raw = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
        broker = load_broker_profile(Path(args.config).parent / raw["costs"]["broker_profile"])
        state = readiness(prices, quotes, transactions_path=args.transactions, receipt_path=args.reconciliation)
        issues = state["issues"]
        for ticker in quotes:
            issues.extend(broker.check_product(ticker, load_universe(DEFAULT_ASSETS)))
        if issues:
            raise ValueError("Proposition réelle bloquée : " + " ; ".join(issues) + " Utiliser --simulation pour une étude hypothétique.")
    from datetime import date as _date

    from src.contribution_plan import purchase_calendar

    month = args.month or f"{_date.today():%Y-%m}"
    frequency = args.frequency or int(patrimoine["profil"].get("frequence_achat_mois", 1))
    calendar = purchase_calendar(month, frequency, patrimoine["profil"].get("premier_mois_achat"))
    plan = plan_contribution(holdings, quotes, plan_weights, contribution=amount, cash_available=cash,
                             fee_model=fees,
                             tolerance_pct=float(patrimoine["profil"]["tolerance_derivation_pct"]),
                             buy=calendar["buy"])
    plan["notes"] = vehicle_notes + plan["notes"]
    if getattr(args, "simulation", False):
        plan["notes"].insert(0, "SIMULATION HYPOTHÉTIQUE : état bancaire et disponibilité des produits non validés.")
        if args.record:
            raise ValueError("--record interdit en --simulation.")
    if frequency > 1:
        if calendar["buy"]:
            plan["notes"].insert(0, f"Mois d'achat (tous les {frequency} mois) : le budget comprend les versements "
                                    "accumulés depuis le dernier achat (liquidités du journal de transactions).")
        else:
            plan["notes"].insert(0, f"Achat tous les {frequency} mois : prochain achat en {calendar['next_buy']} "
                                    f"(~{amount * calendar['months_to_next'] + plan['budget']:,.0f} € avec les "
                                    "versements d'ici là). Verse quand même ce mois-ci et note le VERSEMENT dans "
                                    "config/transactions.csv.")
    if args.record:
        from src.ledger import record_pending_orders

        count = record_pending_orders(plan["table"], args.pending, envelope=args.envelope)
        plan["notes"].append(f"{count} ordre(s) proposé(s) ajouté(s) à {Path(args.pending).name} (statut PROPOSE) : "
                             "à reporter dans transactions.csv uniquement après exécution réelle.")
    for line in plan_lines(plan, target):
        print(line)
    path = generate_plan_report(plan, target, Path(args.output_dir) / f"{month}-plan.md",
                                positions_date=positions["date"])
    print(f"Rapport : {path}")
    return 0


def _cmd_dca(args: argparse.Namespace) -> int:
    config, _, result = _pipeline_for_research(args)
    monthly = args.monthly
    if monthly is None:
        monthly = float(load_patrimoine_config(DEFAULT_PATRIMOINE)["profil"]["versement_mensuel_eur"])
    strategy_returns = {
        "buy_and_hold": result.benchmark_backtest["Returns"],
        "momentum": result.momentum_backtest["Net Return"],
    }
    exposures = {"momentum": result.momentum_backtest["Invested Exposure"]}
    if result.vt_backtest is not None:
        strategy_returns["momentum_vt"] = result.vt_backtest["Net Return"]
        exposures["momentum_vt"] = result.vt_backtest["Invested Exposure"]
    def _order_count(backtest):
        return backtest["Selected Assets"].map(lambda s: max(1, len([a for a in s.split(", ") if a != "CASH"])))

    orders = {"momentum": _order_count(result.momentum_backtest)}
    if result.vt_backtest is not None:
        orders["momentum_vt"] = _order_count(result.vt_backtest)
    comparison = run_dca_comparison(strategy_returns, monthly, exposures=exposures,
                                    transaction_cost=config.backtest.transaction_cost, start=args.start,
                                    fee_model=load_fee_model(args.config), orders=orders,
                                    taxes=tax_config_from(load_patrimoine_config(DEFAULT_PATRIMOINE)))
    path = generate_dca_report(comparison, Path(args.output), benchmark=config.benchmark_ticker)
    print(f"Simulation DCA : {monthly:,.0f} €/mois, {comparison['start']} -> {comparison['end']} "
          f"({comparison['n_months']} versements)")
    for name, summary in comparison["strategies"].items():
        mwr = summary["money_weighted_return"]
        print(f"  {name:13}: versé {summary['total_contributed_eur']:>10,.0f} € -> "
              f"{summary['final_value_eur']:>10,.0f} € brut, {summary['final_value_net_eur']:>10,.0f} € net "
              f"(TRI {'n/a' if mwr is None else f'{mwr:.2%}'}, frais versements "
              f"{summary['contribution_fees_eur']:,.0f} €)")
    print(f"Rapport : {path}")
    return 0


def _cmd_vehicles(args: argparse.Namespace) -> int:
    """Expositions, véhicules (préférence, dernier prix) et écart de suivi des proxys."""
    from src.positions import last_prices
    from src.universe import load_universe
    from src.vehicles import splice_history, tracking_stats, vehicles_by_exposure

    assets = load_universe(args.assets)
    prices = _load_prices(Path(args.data), Path(args.assets), False)
    quotes = last_prices(prices)["prix"].to_dict()
    proxies = {a["ticker"]: a["proxy"] for a in assets if a.get("proxy")}
    print("Expositions et véhicules (1 = préféré ; aucun ordre n'est passé)")
    for exposure, tickers in vehicles_by_exposure(assets).items():
        listing = ", ".join(f"{i}. {t} ({quotes[t]:,.2f} €)" if t in quotes else f"{i}. {t} (sans prix)"
                            for i, t in enumerate(tickers, start=1))
        print(f"  {exposure:24} {listing}")
    for vehicle, proxy in proxies.items():
        if vehicle not in prices.columns or proxy not in prices.columns:
            print(f"Proxy {proxy} -> {vehicle} : prix manquants.")
            continue
        # Mesure mensuelle (même fréquence que les stratégies ; évite le bruit des heures de clôture).
        stats = tracking_stats(prices[vehicle].resample("ME").last(), prices[proxy].resample("ME").last(),
                               periods_per_year=12)
        spliced, flag = splice_history(prices[vehicle], prices[proxy])
        print(f"Proxy {proxy} -> {vehicle} : historique prolongé de {int(flag.sum())} séances synthétiques "
              f"(avant {prices[vehicle].first_valid_index().date()}).")
        if stats["tracking_difference"] is None:
            print("  Période commune trop courte pour mesurer l'écart de suivi.")
        else:
            print(f"  Écart de suivi mensuel {stats['start']} -> {stats['end']} : différence annuelle "
                  f"{stats['tracking_difference']:+.2%}, tracking error {stats['tracking_error']:.2%}, "
                  f"corrélation {stats['correlation']:.3f}")
    return 0


def _cmd_portfolio(args: argparse.Namespace) -> int:
    """Portefeuille réel : performance, frais, règles du PEA (rapport personnel)."""
    from src.ledger import generate_portfolio_report, load_transactions, pea_status, portfolio_performance
    from src.monthly_pipeline import load_config

    config = load_config(args.config)
    patrimoine = load_patrimoine_config(DEFAULT_PATRIMOINE)
    pea_cfg = patrimoine.get("pea") or {}
    transactions = load_transactions(args.transactions)
    perf, notes = None, []
    if transactions is None:
        print(f"Aucun journal ({args.transactions}) : copie config/transactions.example.csv en transactions.csv.")
    elif transactions.empty:
        print(f"Journal vide ({args.transactions}) : ajoute ton premier VERSEMENT puis tes ACHAT réels "
              "(format : voir config/transactions.example.csv).")
        transactions = None
    else:
        prices = _load_prices(Path(args.data), DEFAULT_ASSETS, False)
        paper_monthly = None
        try:
            from src.cli.paper_cmds import _paper_ledger

            ledger, _ = _paper_ledger(Path(args.paper_dir), Path(args.data), Path(args.config), DEFAULT_ASSETS)
            paper_monthly = ledger["monthly"]
        except (ValueError, FileNotFoundError) as exc:
            notes.append(f"Comparaison avec le paper trading indisponible : {exc}")
        perf = portfolio_performance(transactions, prices, envelope=args.envelope,
                                     benchmark=config.benchmark_ticker, paper_monthly=paper_monthly)
        _, position_notes = _current_positions(args.positions, args.transactions)
        notes += position_notes
    pea = pea_status(transactions, pea_cfg.get("date_ouverture"),
                     ceiling=float(pea_cfg.get("plafond_versements_eur", 150_000)))
    path = generate_portfolio_report(perf, pea, Path(args.output), notes=notes, benchmark=config.benchmark_ticker)
    print("Portefeuille réel (données personnelles ; aucun ordre exécuté)")
    if perf is not None:
        mwr = perf["mwr"]
        print(f"  Valeur {perf['final_value']:,.2f} EUR pour {perf['net_contributions']:,.2f} EUR versés ; "
              f"TRI {'n/a' if mwr is None else f'{mwr:+.2%}'} ; frais {perf['fees_total']:,.2f} EUR")
        twr = perf["comparison"].get("real_twr")
        print(f"  TWR réel {'n/a' if twr is None else f'{twr:+.2%}'} ; Buy & Hold mêmes versements "
              f"{perf['benchmark_same_flows_value']:,.2f} EUR")
    if transactions is not None:
        from src.ledger import contribution_regularity

        benchmark = _load_prices(Path(args.data), DEFAULT_ASSETS, False).get(config.benchmark_ticker)
        regularity = contribution_regularity(transactions, benchmark=benchmark)
        if regularity:
            print(f"  Régularité : {regularity['months_paid']}/{regularity['months']} mois versés "
                  f"(série en cours : {regularity['current_streak']}) ; mois de baisse > "
                  f"{regularity['stress_threshold']:.0%} : {regularity['stress_months_paid']}/"
                  f"{regularity['stress_months']} versés")
    print(f"  PEA : versements {pea['contributions']:,.0f} / {pea['ceiling']:,.0f} EUR ; "
          f"5 ans le {pea.get('five_year_date', 'n/a')}")
    for alert in pea["alerts"]:
        print(f"  Alerte : {alert}")
    for note in notes:
        print(f"  Note : {note}")
    print(f"Rapport : {path}")
    return 0


def _cmd_universe(args: argparse.Namespace) -> int:
    from src.universe import fiche_warnings, load_universe

    assets = load_universe(Path(args.assets), include_inactive=True)
    print("Univers : identité des produits (fiches vérifiées, aucune donnée de marché)")
    print(f"  {'ticker':9} {'actif':5} {'ISIN':12} {'TER':>6} {'PEA':4} {'vérifié':10} nom officiel")
    for asset in assets:
        fiche = asset.get("fiche") or {}
        ter = "" if fiche.get("ter_pct") is None else f"{fiche['ter_pct']:.2f}%"
        pea = {True: "oui", False: "non", None: "?"}[fiche.get("pea")] if fiche else "?"
        print(f"  {asset['ticker']:9} {'oui' if asset['universe_active'] else 'non':5} {fiche.get('isin', '-'):12} "
              f"{ter:>6} {pea:4} {fiche.get('verifie_le', '-'):10} {fiche.get('nom_officiel', asset['name'])}")
    warnings = fiche_warnings(assets)
    if warnings:
        print("\nPoints d'attention :")
        for warning in warnings:
            print(f"  - {warning}")
    print("\nSource : fiches produits (justETF / émetteurs) ; à revérifier au moins une fois par an.")
    return 0

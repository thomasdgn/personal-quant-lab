"""Commandes PEA rapproché, recherche tactique et veille locale sans envoi."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.cli.common import PROJECT_ROOT


def _run(args):
    from src.pea_account import import_transactions, readiness, reconcile

    root = PROJECT_ROOT
    if args.command == "import-transactions":
        mapping = yaml.safe_load(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else None
        result = import_transactions(args.input, args.transactions, mapping, apply=args.apply)
    elif args.command == "reconcile":
        result = reconcile(args.transactions, args.snapshot, receipt_path=args.output)
    elif args.command == "pea-check":
        from src.data_loader import load_prices
        from src.broker import load_broker_profile
        from src.universe import load_universe
        from src.policy import load_policy
        from src.vehicles import map_target_to_vehicles
        from src.positions import last_prices
        from src.patrimoine import load_patrimoine_config

        prices = load_prices(args.data)
        assets = load_universe(root / "config/assets.yaml")
        policy = load_policy(root / "config/policy.yaml")
        quotes = last_prices(prices)["prix"].to_dict()
        monthly = load_patrimoine_config(root / "config/patrimoine.yaml")["profil"]["versement_mensuel_eur"]
        weights, _ = map_target_to_vehicles(policy.allocation_fixe, {}, quotes, assets, monthly)
        tickers = [t for t in weights if t != "CASH"]
        result = readiness(prices, tickers, transactions_path=args.transactions, receipt_path=args.reconciliation)
        broker = load_broker_profile(args.broker)
        for ticker in tickers:
            result["issues"].extend(broker.check_product(ticker, assets))
        result["ready"] = not result["issues"]
        result["monthly_eur"] = monthly
        result["broker_offer"] = broker.offer
    elif args.command == "tactical-research":
        from src.tactical_research import run_campaign

        result = run_campaign(root, output_dir=args.output_dir, limit=args.limit)
    elif args.command == "macro":
        from src.macro import macro_context, load_observations

        result = macro_context(load_observations(args.input), args.as_of)
    else:
        from src.watch import run_watch

        result = run_watch(root, output_dir=args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 2 if result.get("ready") is False or result.get("ok") is False else 0


def register(sub):
    root = PROJECT_ROOT
    for name, help_text in (("pea-check", "Vérifie le compte, les cours et les produits sans ordre."),
                            ("import-transactions", "Prévisualise un import CSV normalisé (mapping explicite)."),
                            ("reconcile", "Rapproche le journal et un relevé daté."),
                            ("tactical-research", "Campagne reproductible en parts entières, tarifs actuels."),
                            ("macro", "Contexte macro à la date de disponibilité."),
                            ("watch", "Veille locale en simulation, sans notification externe.")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.set_defaults(func=_run)
        if name in ("pea-check", "import-transactions", "reconcile"):
            cmd.add_argument("--transactions", default=str(root / "config/transactions.csv"))
        if name == "import-transactions":
            cmd.add_argument("--input", required=True)
            cmd.add_argument("--mapping", default=None)
            cmd.add_argument("--apply", action="store_true", help="Écrit le journal validé ; défaut = prévisualisation.")
        elif name == "reconcile":
            cmd.add_argument("--snapshot", required=True)
            cmd.add_argument("--output", default=str(root / "config/reconciliation.json"))
        elif name == "pea-check":
            cmd.add_argument("--data", default=str(root / "data/processed/universe_prices.csv"))
            cmd.add_argument("--broker", default=str(root / "config/broker.yaml"))
            cmd.add_argument("--reconciliation", default=str(root / "config/reconciliation.json"))
        elif name == "tactical-research":
            cmd.add_argument("--output-dir", default=str(root / "reports/tactical"))
            cmd.add_argument("--limit", type=int, default=80, help="Nombre maximal de configurations, hors sensibilités.")
        elif name == "macro":
            cmd.add_argument("--input", default=str(root / "data/macro/observations.csv"))
            cmd.add_argument("--as-of", required=True)
        elif name == "watch":
            cmd.add_argument("--output-dir", default=str(root / "reports/watch"))

"""Commandes rapport mensuel, routine, état, données et validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.cli.common import (
    DEFAULT_PATRIMOINE,
    _fmt_weights,
    _load_asset_roles,
    _load_prices,
    _refresh_prices,
    _resolve_data_path,
)
from src.cli.paper_cmds import _paper_ledger, _print_comparison
from src.data_loader import validate_prices
from src.monthly_pipeline import PipelineValidationError, load_config, run_monthly_pipeline
from src.paper_ledger import generate_performance_report, ledger_summary_lines
from src.paper_trading import (
    PAPER_STATUSES,
    PaperTradingError,
    compare_monthly_reports,
    create_paper_entry_from_snapshot,
    load_monthly_snapshot,
    load_paper_entry,
    save_paper_entry,
)
from src.policy import load_policy
from src.reporting import generate_markdown_report, load_previous_snapshot, save_report_snapshot
from src.routine import collect_status, decision_command, previous_snapshot_path


def _cmd_refresh_data(args: argparse.Namespace) -> int:
    prices = _refresh_prices(Path(args.data), Path(args.assets), full=args.full, verbose=True)
    print("Données téléchargées et validées (yfinance, prix ajustés)")
    print(f"Fichier : {args.data}")
    print(f"Période : {prices.index.min().date()} -> {prices.index.max().date()} ({len(prices)} séances)")
    print(f"{'Ticker':10} {'Début':11} {'Fin':11} Observations")
    for ticker in prices.columns:
        series = prices[ticker].dropna()
        print(f"{ticker:10} {series.index.min().date()!s:11} {series.index.max().date()!s:11} {len(series)}")
    missing = sorted(set(_load_asset_roles(Path(args.assets))) - set(prices.columns))
    if missing:
        print(f"ATTENTION : aucun prix pour {', '.join(missing)}")
    if getattr(args, "long", False):
        from src.cli import common
        from src.long_history import load_long_config, refresh_long_history, synthetic_share

        long_config = load_long_config(args.long_config)
        built = refresh_long_history(
            prices, lambda tickers, start: validate_prices(common.download_prices(tickers, start=start)),
            long_config, args.long_data, Path(args.long_data).with_name("long_history_sources.csv"),
        )
        print(f"\nHistorique long (recherche uniquement, SYNTHÉTIQUE avant la cotation réelle) : {args.long_data}")
        for ticker, info in synthetic_share(built["sources"]).items():
            if ticker in long_config["chains"]:
                print(f"  {ticker:9} depuis {info['start']} (réel depuis {info['real_start']}, "
                      f"{info['synthetic_share']:.0%} synthétique)")
        for item in built["tracking"]:
            if item["correlation"] is not None:
                print(f"  proxy {item['proxy']:17} -> {item['target']:9} corrélation {item['correlation']:.3f}, "
                      f"écart {item['tracking_difference']:+.2%}/an")
    return 0


def _generate_monthly_report(args: argparse.Namespace):
    """Calcule et écrit le rapport mensuel ; renvoie (result, md_path, json_path)."""
    config = load_config(args.config)
    prices = _load_prices(Path(args.data), Path(args.assets), args.refresh_data)

    roles = _load_asset_roles(Path(args.assets))
    result = run_monthly_pipeline(
        prices,
        config,
        report_date=args.report_date,
        data_refreshed=args.refresh_data,
        asset_roles=roles, policy=load_policy(args.policy),
    )
    report = result.report
    month = report.metadata["report_month"]

    output_dir = Path(args.output_dir)
    previous = load_previous_snapshot(output_dir, month)
    if previous is not None:
        # Reconstruit la comparaison avec le snapshot précédent trouvé sur disque.
        result = run_monthly_pipeline(
            prices, config, report_date=args.report_date,
            data_refreshed=args.refresh_data, previous_snapshot=previous,
            asset_roles=roles, policy=load_policy(args.policy),
        )
        report = result.report

    # Graphiques : utiles mais jamais bloquants pour le rapport.
    try:
        from src.report_figures import save_monthly_figures

        figures = save_monthly_figures(result, output_dir / "figures", month)
    except Exception as exc:  # noqa: BLE001 - un graphique ne doit pas empêcher le rapport
        print(f"Avertissement : graphiques non générés ({exc}).", file=sys.stderr)
        figures = {}

    # On génère toujours Markdown + JSON, même en statut CRITICAL (diagnostic).
    md_path = generate_markdown_report(result, output_dir / f"{month}-report.md", figures)
    json_path = save_report_snapshot(result, output_dir / f"{month}-report.json", figures)
    if getattr(args, "html", False):
        from src.html_report import markdown_to_html

        print(f"HTML autonome     : {markdown_to_html(md_path)}")
    return result, md_path, json_path


def _print_report_summary(result, md_path: Path, json_path: Path) -> str:
    """Affiche le résumé du rapport et renvoie le statut du pipeline."""
    report = result.report
    vt = report.volatility_targeted_strategy
    status = report.metadata["pipeline_status"]
    n_warning = sum(1 for a in report.alerts if a.level == "WARNING")
    n_critical = sum(1 for a in report.alerts if a.level == "CRITICAL")

    print("Rapport généré")
    print(f"Statut            : {status}")
    if status == "CRITICAL":
        print("Validation humaine requise")
    print(f"Date du signal    : {report.metadata['signal_date']}")
    print(f"Stratégie Momentum: {', '.join(report.momentum_strategy.selected_assets) or 'cash'}")
    print(f"Allocation Momentum: {_fmt_weights(report.momentum_strategy.target_weights)}")
    if vt.enabled:
        print(f"Allocation VT     : {_fmt_weights(vt.target_weights)}")
        print(f"Cash VT           : {vt.cash_weight * 100:.0f} %")
    else:
        print("Volatility Targeting : désactivé dans la configuration")
    print(f"Alertes           : {n_warning} WARNING, {n_critical} CRITICAL")
    print(f"Markdown          : {md_path}")
    print(f"JSON              : {json_path}")
    return status


def _cmd_monthly_report(args: argparse.Namespace) -> int:
    result, md_path, json_path = _generate_monthly_report(args)
    status = _print_report_summary(result, md_path, json_path)
    # Convention : 2 = rapport généré mais statut CRITICAL (validation requise).
    return 2 if status == "CRITICAL" else 0


def _notify(args: argparse.Namespace, snapshot: dict | None, previous: dict | None, failure: str | None = None) -> None:
    """Envoie les notifications si --notify et config activée (jamais bloquant)."""
    if not getattr(args, "notify", False):
        return
    from src.notify import build_events, load_notify_config, send_events

    try:
        config = load_notify_config(args.notify_config)
        results = send_events(build_events(snapshot, previous, failure=failure), config,
                              log_path=Path(args.log_dir) / "notifications.jsonl")
    except (ValueError, OSError) as exc:
        print(f"Notifications non envoyées : {exc}")
        return
    sent = sum(r["status"] == "sent" for r in results)
    state = "désactivées (config/notify.yaml)" if not config.enabled else f"{sent}/{len(results)} envoyée(s)"
    print(f"Notifications : {state}")


def _cmd_run_month(args: argparse.Namespace) -> int:
    """Routine complète : (données) -> rapport -> entrée paper -> comparaison."""
    print("=== 1/3 Rapport mensuel ===")
    try:
        result, md_path, json_path = _generate_monthly_report(args)
    except (ValueError, FileNotFoundError, PipelineValidationError) as exc:
        _notify(args, None, None, failure=str(exc))
        raise
    status = _print_report_summary(result, md_path, json_path)
    month = result.report.metadata["report_month"]

    print("\n=== 2/3 Journal de paper trading ===")
    snapshot = load_monthly_snapshot(json_path)
    entry = create_paper_entry_from_snapshot(snapshot, json_path, md_path)
    entry_path = Path(args.paper_dir) / f"{month}-paper-entry.json"
    try:
        save_paper_entry(entry, entry_path, force=False)
        print(f"Entrée {month} créée ou mise à jour (statut PENDING) : {entry_path}")
    except PaperTradingError:
        print(f"Entrée {month} déjà décidée : conservée telle quelle ({entry_path}).")
        entry = load_paper_entry(entry_path)

    print("\n=== 3/3 Comparaison avec le mois précédent ===")
    previous_path = previous_snapshot_path(args.output_dir, month)
    if previous_path is None:
        print("Aucun rapport précédent : comparaison ignorée.")
    else:
        comparison = compare_monthly_reports(load_monthly_snapshot(previous_path), snapshot)
        _print_comparison(comparison)
        out = Path(args.paper_dir) / f"comparison-{comparison['previous_month']}-{comparison['current_month']}.json"
        out.write_text(json.dumps(comparison, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8", newline="\n")
        print(f"Comparaison sauvegardée : {out}")

    _notify(args, snapshot, load_monthly_snapshot(previous_path) if previous_path else None)

    print("\n=== Performance paper (décisions passées) ===")
    paper_lines: list[str] = []
    try:
        ledger, config = _paper_ledger(Path(args.paper_dir), Path(args.data), Path(args.config), Path(args.assets))
        paper_lines = ledger_summary_lines(ledger)
        for line in paper_lines:
            print(line)
        generate_performance_report(ledger, Path(args.paper_dir) / "performance.md",
                                    benchmark=config.benchmark_ticker)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Performance paper indisponible : {exc}")

    if getattr(args, "html", False):
        from src.month_summary import write_month_summary

        portfolio = None
        try:
            from src.ledger import load_transactions, pea_status, portfolio_performance
            from src.patrimoine import load_patrimoine_config

            transactions = load_transactions(args.transactions)
            pea_cfg = load_patrimoine_config(DEFAULT_PATRIMOINE).get("pea") or {}
            perf = None
            if transactions is not None:
                perf = portfolio_performance(transactions, _load_prices(Path(args.data), Path(args.assets), False),
                                             benchmark=load_config(args.config).benchmark_ticker)
            portfolio = {"perf": perf, "pea": pea_status(transactions, pea_cfg.get("date_ouverture"),
                                                         ceiling=float(pea_cfg.get("plafond_versements_eur", 150_000)))}
        except (ValueError, FileNotFoundError) as exc:
            print(f"Portefeuille réel indisponible pour le résumé : {exc}")
        plans = sorted((Path(args.output_dir).parent / "contributions").glob("*-plan.md"))
        summary = write_month_summary(snapshot, Path(args.output_dir) / f"{month}-resume.html",
                                      plan_path=plans[-1] if plans else None, paper_lines=paper_lines,
                                      portfolio=portfolio)
        print(f"Résumé du mois (HTML, personnel) : {summary}")

    print("\n=== Prochaine étape (manuelle) ===")
    if status == "CRITICAL":
        print("Statut CRITICAL : lis les alertes du rapport avant toute décision.")
    if entry.get("manual_decision_status") == "PENDING":
        print("1. Lis le rapport :", md_path)
        print("2. Enregistre ta décision fictive (aucun ordre réel) :")
        print("   " + decision_command(month, entry.get("system_suggested_strategy")))
        print("   (statuts possibles : " + ", ".join(PAPER_STATUSES) + ")")
    else:
        print(f"Décision {month} déjà enregistrée : {entry.get('manual_decision_status')}.")
    return 2 if status == "CRITICAL" else 0


def _cmd_status(args: argparse.Namespace) -> int:
    configured = list(_load_asset_roles(Path(args.assets)))
    status = collect_status(data_path=_resolve_data_path(Path(args.data)), configured_tickers=configured,
                            monthly_dir=args.monthly_dir, paper_dir=args.paper_dir)
    data, report, journal = status["data"], status["last_report"], status["journal"]
    print(f"État du personal-quant-lab — {status['today']}")
    print("\nDonnées")
    if data.get("exists"):
        print(f"  Fichier            : {data['path']}")
        print(f"  Dernière séance    : {data['last_observation']} (il y a {data['age_days']} jours)")
        print(f"  Tickers            : {data['n_tickers']} ; manquants : {', '.join(data['missing_tickers']) or 'aucun'}")
    else:
        print(f"  Aucun fichier de prix ({data['path']})")
    print("\nDernier rapport mensuel")
    if report:
        print(f"  Mois / signal      : {report['report_month']} / {report['signal_date']}")
        print(f"  Statut             : {report['pipeline_status']} "
              f"({report['n_warning']} WARNING, {report['n_critical']} CRITICAL)")
    else:
        print("  Aucun rapport.")
    print("\nJournal de paper trading")
    print(f"  Entrées            : {journal['n_entries']} ; décisions renseignées : {journal['n_decided']}")
    print(f"  En attente         : {', '.join(journal['pending_months']) or 'aucune'}")
    rule = "atteinte" if journal["rule_met"] else "pas encore atteinte"
    print(f"  Règle des {journal['min_months_rule']} mois   : {rule} ({journal['n_decided']}/{journal['min_months_rule']})")
    print("\nProchaines actions")
    for index, step in enumerate(status["next_steps"], start=1):
        print(f"  {index}. {step}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    config.validate()
    print("Configuration valide :", args.config)
    print(f"Benchmark : {config.benchmark_ticker} | cible vol : {config.volatility_targeting.target_volatility}")
    return 0


# --------------------------------------------------------------------------- #
# Paper trading (Projet 4B) — aucun ordre réel n'est jamais exécuté.
# --------------------------------------------------------------------------- #

"""Commandes du journal de paper trading (aucun ordre réel)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.cli.common import (
    _fmt_delta,
    _load_asset_roles,
    _load_prices,
)
from src.monthly_pipeline import MonthlyPipelineConfig, load_config
from src.paper_ledger import build_paper_ledger, generate_performance_report, ledger_summary_lines
from src.paper_trading import (
    PaperTradingError,
    compare_monthly_reports,
    create_paper_entry_from_snapshot,
    load_monthly_snapshot,
    load_paper_entries,
    load_paper_entry,
    save_paper_entry,
    update_manual_decision,
)


def _cmd_paper_init(args: argparse.Namespace) -> int:
    snapshot_path = Path(args.snapshot)
    snapshot = load_monthly_snapshot(snapshot_path)
    markdown_path = snapshot_path.with_name(snapshot_path.name.replace("-report.json", "-report.md"))
    entry = create_paper_entry_from_snapshot(
        snapshot, snapshot_path, markdown_path if markdown_path.exists() else None
    )
    output = Path(args.output_dir) / f"{entry['report_month']}-paper-entry.json"
    try:
        path = save_paper_entry(entry, output, force=args.force)
    except PaperTradingError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    print("Entrée paper trading créée (statut PENDING, aucun ordre exécuté)")
    print(f"Mois     : {entry['report_month']}")
    print(f"Proposée : {entry['system_suggested_strategy']}")
    print(f"Fichier  : {path}")
    return 0


def _cmd_paper_list(args: argparse.Namespace) -> int:
    entries = load_paper_entries(Path(args.paper_dir))
    if not entries:
        print("Aucune entrée de paper trading.")
        return 0
    print(f"{'Mois':8} {'Signal':11} {'Statut':16} {'Proposée':13} {'Alertes':8} Fichier")
    print("-" * 78)
    for entry in entries:
        alerts = entry.get("alerts_summary", {}).get("counts", {})
        alert_str = f"{alerts.get('WARNING', 0)}W/{alerts.get('CRITICAL', 0)}C"
        print(f"{entry.get('report_month', '?'):8} {entry.get('signal_date', '?'):11} "
              f"{entry.get('manual_decision_status', '?'):16} "
              f"{entry.get('system_suggested_strategy', '?'):13} {alert_str:8} "
              f"paper-{entry.get('report_month', '?')}-...json")
    return 0


def _resolve_snapshot(month_or_none: str | None, explicit: str | None, monthly_dir: Path) -> Path:
    if explicit:
        return Path(explicit)
    return monthly_dir / f"{month_or_none}-report.json"


def _cmd_compare_reports(args: argparse.Namespace) -> int:
    monthly_dir = Path(args.monthly_dir)
    prev_path = _resolve_snapshot(args.from_month, args.previous, monthly_dir)
    cur_path = _resolve_snapshot(args.to_month, args.current, monthly_dir)
    previous = load_monthly_snapshot(prev_path)
    current = load_monthly_snapshot(cur_path)
    comparison = compare_monthly_reports(previous, current)
    _print_comparison(comparison)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(comparison, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8", newline="\n")
        print(f"Comparaison sauvegardée : {out}")
    return 0


def _print_comparison(comparison: dict) -> None:
    print(f"Comparaison {comparison['previous_month']} -> {comparison['current_month']}")
    print(f"Momentum sélectionné : {comparison['momentum_selected_from']} -> {comparison['momentum_selected_to']}"
          f" ({'changé' if comparison['momentum_selected_changed'] else 'inchangé'})")
    print(f"Statut pipeline      : {comparison['pipeline_status_from']} -> {comparison['pipeline_status_to']}")
    print(f"Exposition VT (var.) : {_fmt_delta(comparison['vt_exposure_change'])}")
    print(f"Cash VT (var.)       : {_fmt_delta(comparison['vt_cash_change'])}")
    print(f"Nouvelles alertes    : {comparison['new_alert_codes'] or 'aucune'}")
    print(f"Alertes résolues     : {comparison['resolved_alert_codes'] or 'aucune'}")


def _cmd_paper_decision(args: argparse.Namespace) -> int:
    entry_path = Path(args.paper_dir) / f"{args.month}-paper-entry.json"
    if not entry_path.exists():
        print(f"ERREUR : entrée introuvable ({entry_path}). Lance d'abord paper-init.", file=sys.stderr)
        return 1
    try:
        entry = load_paper_entry(entry_path)
        journal = {"confidence": args.confidence, "pros": args.pros, "cons": args.cons,
                   "next_check": args.next_check}
        updated = update_manual_decision(entry, args.status, strategy=args.strategy, comment=args.comment,
                                         journal=journal if any(v is not None for v in journal.values()) else None)
        # paper-decision est l'outil dédié à l'écriture de décisions -> force.
        save_paper_entry(updated, entry_path, force=True)
    except PaperTradingError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    print("Décision paper trading enregistrée (aucun ordre réel exécuté)")
    print(f"Mois      : {args.month}")
    print(f"Statut    : {updated['manual_decision_status']}")
    print(f"Stratégie : {updated['manual_selected_strategy'] or 'aucune'}")
    if updated.get("decision_journal"):
        print(f"Journal   : {', '.join(sorted(updated['decision_journal']))}")
    return 0


def _paper_ledger(paper_dir: Path, data: Path, config_path: Path, assets: Path) -> tuple[dict, MonthlyPipelineConfig]:
    config = load_config(config_path)
    prices = _load_prices(data, assets, False)
    roles = _load_asset_roles(assets)
    cash_proxy = next((t for t, r in roles.items() if r == "cash_proxy"), None)
    use_proxy = config.universe.use_cash_proxy_return
    return build_paper_ledger(
        load_paper_entries(paper_dir), prices, benchmark=config.benchmark_ticker,
        transaction_cost=config.backtest.transaction_cost,
        cash_proxy=cash_proxy if use_proxy else None, fallback_cash_return=config.backtest.cash_return,
    ), config


def _cmd_paper_performance(args: argparse.Namespace) -> int:
    ledger, config = _paper_ledger(Path(args.paper_dir), Path(args.data), Path(args.config), Path(args.assets))
    print("Performance du paper trading (portefeuilles fictifs, aucun ordre réel)")
    for line in ledger_summary_lines(ledger):
        print(line)
    path = generate_performance_report(ledger, Path(args.output), benchmark=config.benchmark_ticker)
    print(f"Rapport : {path}")
    return 0

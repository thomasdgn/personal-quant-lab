"""Routine mensuelle et état du laboratoire (commandes ``run-month`` et ``status``).

Fonctions pures de lecture des fichiers locaux (prix, rapports mensuels,
journal de paper trading) : elles ne calculent aucune stratégie et
n'exécutent aucun ordre.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data_loader import load_prices
from src.paper_trading import list_monthly_snapshots, load_monthly_snapshot, load_paper_entries

# Nombre minimal de mois de journal de décision avant d'envisager l'argent réel
# (règle du guide : « journal de décision pendant au moins 3 mois »).
MIN_JOURNAL_MONTHS = 3
STALE_DATA_DAYS = 7


def previous_snapshot_path(monthly_dir: str | Path, current_month: str) -> Path | None:
    """Snapshot mensuel valide le plus récent **strictement antérieur** à ``current_month``."""
    candidates = [p for p in list_monthly_snapshots(monthly_dir) if p.name[:7] < current_month]
    return candidates[-1] if candidates else None


def decision_command(month: str, suggested_strategy: str | None) -> str:
    """Commande ``paper-decision`` pré-remplie pour la décision humaine du mois."""
    strategy = suggested_strategy or "momentum_vt"
    return (
        f'python main.py paper-decision --month {month} --status APPROVED_PAPER '
        f'--strategy {strategy} --comment "Décision fictive, paper trading uniquement"'
    )


def _data_status(data_path: Path, configured: list[str], today: pd.Timestamp) -> dict:
    if not data_path.exists():
        return {"path": str(data_path), "exists": False}
    prices = load_prices(data_path)
    last = prices.dropna(how="all").index.max()
    tickers = list(prices.columns)
    return {
        "path": str(data_path),
        "exists": True,
        "last_observation": last.date().isoformat(),
        "age_days": int((today.normalize() - last.normalize()).days),
        "n_tickers": len(tickers),
        "missing_tickers": [t for t in configured if t not in tickers],
    }


def collect_status(
    *,
    data_path: str | Path,
    configured_tickers: list[str],
    monthly_dir: str | Path,
    paper_dir: str | Path,
    today: str | pd.Timestamp | None = None,
) -> dict:
    """Rassemble l'état du laboratoire à partir des fichiers locaux."""
    now = pd.Timestamp(today) if today is not None else pd.Timestamp.now()
    data = _data_status(Path(data_path), configured_tickers, now)

    snapshots = list_monthly_snapshots(monthly_dir)
    last_report = None
    if snapshots:
        snapshot = load_monthly_snapshot(snapshots[-1])
        meta = snapshot.get("metadata", {})
        levels = [a.get("level") for a in snapshot.get("alerts", [])]
        last_report = {
            "path": str(snapshots[-1]),
            "report_month": meta.get("report_month"),
            "signal_date": meta.get("signal_date"),
            "pipeline_status": meta.get("pipeline_status"),
            "n_warning": levels.count("WARNING"),
            "n_critical": levels.count("CRITICAL"),
        }

    entries = load_paper_entries(paper_dir)
    pending = [e["report_month"] for e in entries if e.get("manual_decision_status") == "PENDING"]
    decided = [e["report_month"] for e in entries if e.get("manual_decision_status") not in (None, "PENDING")]
    journal = {
        "n_entries": len(entries),
        "pending_months": pending,
        "decided_months": decided,
        "n_decided": len(decided),
        "min_months_rule": MIN_JOURNAL_MONTHS,
        "rule_met": len(decided) >= MIN_JOURNAL_MONTHS,
        "last_entry_month": entries[-1]["report_month"] if entries else None,
    }
    status: dict = {"today": now.date().isoformat(), "data": data, "last_report": last_report, "journal": journal}
    status["next_steps"] = next_steps(status)
    return status


def next_steps(status: dict) -> list[str]:
    """Actions suggérées, dans l'ordre de la routine mensuelle."""
    steps: list[str] = []
    data = status["data"]
    current_month = status["today"][:7]
    data_ok = bool(data.get("exists")) and data["age_days"] <= STALE_DATA_DAYS and not data["missing_tickers"]
    report = status["last_report"]
    if report is None or (report["report_month"] or "") < current_month:
        refresh = "" if data_ok else " --refresh-data"
        steps.append(f"Générer le mois : python main.py run-month{refresh}")
    elif not data_ok:
        steps.append("Rafraîchir les données : python main.py refresh-data")
    elif report["pipeline_status"] == "CRITICAL":
        steps.append(f"Lire les alertes CRITICAL du rapport {report['report_month']} avant toute décision")
    for month in status["journal"]["pending_months"]:
        steps.append(f"Renseigner la décision {month} : {decision_command(month, None)}")
    if not steps:
        steps.append("Rien à faire : routine du mois terminée.")
    return steps

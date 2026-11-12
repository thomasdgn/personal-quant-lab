"""Constantes, chemins par défaut et helpers partagés de la CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.data_loader import (
    download_prices,
    load_prices,
    load_tickers_from_yaml,
    save_prices,
    validate_prices,
)
from src.monthly_pipeline import load_config, run_monthly_pipeline
from src.policy import load_policy
from src.universe import asset_roles, load_universe

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "strategy_params.yaml"
DEFAULT_ASSETS = PROJECT_ROOT / "config" / "assets.yaml"
DEFAULT_DATA = PROJECT_ROOT / "data" / "processed" / "universe_prices.csv"
# Ancien nom du fichier de prix (avant l'univers 4C) : encore lu en secours.
LEGACY_DATA = PROJECT_ROOT / "data" / "processed" / "momentum_universe.csv"
DOWNLOAD_START = "2015-01-01"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "monthly"
DEFAULT_PAPER_DIR = PROJECT_ROOT / "reports" / "paper_trading"
DEFAULT_PATRIMOINE = PROJECT_ROOT / "config" / "patrimoine.yaml"
DEFAULT_HOLDINGS = PROJECT_ROOT / "config" / "holdings.yaml"
DEFAULT_POSITIONS = PROJECT_ROOT / "config" / "positions.yaml"
DEFAULT_NOTIFY = PROJECT_ROOT / "config" / "notify.yaml"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_POLICY = PROJECT_ROOT / "config" / "policy.yaml"
DEFAULT_LONG_CONFIG = PROJECT_ROOT / "config" / "long_history.yaml"
DEFAULT_TRANSACTIONS = PROJECT_ROOT / "config" / "transactions.csv"
DEFAULT_PENDING = PROJECT_ROOT / "config" / "pending_orders.csv"
DEFAULT_LONG_PRICES = PROJECT_ROOT / "data" / "processed" / "long_history.csv"
DEFAULT_LONG_SOURCES = PROJECT_ROOT / "data" / "processed" / "long_history_sources.csv"


def _refresh_prices(data_path: Path, assets_path: Path, full: bool = False,
                    verbose: bool = False) -> pd.DataFrame:
    """Met à jour les prix de l'univers actif (incrémental par défaut), archive le
    téléchargement brut, contrôle la qualité et sauvegarde."""
    from src.data_quality import anomaly_lines, archive_raw, incremental_refresh, quality_checks

    tickers = [t for t in load_tickers_from_yaml(assets_path) if t.endswith(".PA")]
    existing = None
    if not full:
        source = _resolve_data_path(data_path) if data_path == DEFAULT_DATA else data_path
        if source.exists():
            existing = load_prices(source)
    prices, info = incremental_refresh(
        existing, tickers, lambda t, start: validate_prices(download_prices(t, start=start)),
        start=DOWNLOAD_START, full=full,
    )
    prices = validate_prices(prices)
    save_prices(prices, data_path)
    archive_raw(info["raw"], data_path.parent.parent / "raw")
    anomalies = quality_checks(prices)
    if verbose:
        print(f"Mode : {'complet' if info['mode'] == 'full' else 'incrémental'} ; nouvelles séances : "
              f"{info['new_rows']}")
        if info["adjusted_tickers"]:
            print(f"Historique ajusté réécrit par la source (retéléchargé) : {', '.join(info['adjusted_tickers'])}")
        if info["new_tickers"] and info["mode"] == "incremental":
            print(f"Nouveaux tickers téléchargés en entier : {', '.join(info['new_tickers'])}")
        if info["no_new_data"]:
            print(f"ATTENTION : aucun prix récent pour {', '.join(info['no_new_data'])}")
        print("Contrôles qualité (45 derniers jours) : " + ("aucune anomalie" if not anomalies else
                                                          f"{len(anomalies)} anomalie(s)"))
        for line in anomaly_lines(anomalies):
            print("  " + line)
    return prices


def _resolve_data_path(data_path: Path) -> Path:
    """Chemin de prix effectif : repli sur l'ancien fichier si le nouveau manque."""
    if not data_path.exists() and data_path == DEFAULT_DATA and LEGACY_DATA.exists():
        print(f"Note : {DEFAULT_DATA.name} absent, lecture de l'ancien fichier {LEGACY_DATA.name}. "
              "Lance `python main.py refresh-data` pour créer le nouveau.")
        return LEGACY_DATA
    return data_path


def _load_prices(data_path: Path, assets_path: Path, refresh: bool) -> pd.DataFrame:
    """Charge les prix : local par défaut, téléchargement si ``refresh``."""
    if refresh:
        return _refresh_prices(data_path, assets_path)
    data_path = _resolve_data_path(data_path)
    if not data_path.exists():
        raise FileNotFoundError(
            f"Données locales introuvables : {data_path}. "
            "Lance `python main.py refresh-data` pour les télécharger."
        )
    return load_prices(data_path)


def _load_asset_roles(assets_path: Path) -> dict[str, str]:
    return asset_roles(load_universe(assets_path))


def _pipeline_for_research(args: argparse.Namespace):
    """Prix locaux + pipeline mensuel (univers et mois complets du rapport)."""
    config = load_config(args.config)
    prices = _load_prices(Path(args.data), Path(args.assets), False)
    result = run_monthly_pipeline(prices, config, asset_roles=_load_asset_roles(Path(args.assets)),
                                  policy=load_policy(getattr(args, "policy", DEFAULT_POLICY)))
    return config, prices, result


def _fmt_weights(weights: dict[str, float] | None) -> str:
    if not weights:
        return "n/a"
    return ", ".join(f"{k} {v * 100:.0f}%" for k, v in weights.items() if v > 1e-9) or "cash"


def _fmt_delta(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.1f} pts"


def _long_universe(prices: pd.DataFrame, roles: dict[str, str], long_config: dict) -> pd.DataFrame:
    """Historique long restreint aux actifs prolongés (candidats et obligataire)."""
    keep = [c for c in prices.columns if c in long_config["chains"] and roles.get(c) in ("candidate", "defensive")]
    return prices[keep].dropna(how="all")


def _strategy_context(config, roles: dict[str, str], columns, policy):
    from src.strategies import StrategyContext

    defensive = [c for c in columns if roles.get(c) == "defensive"]
    bond = defensive[0] if defensive else None
    return StrategyContext(config=config, bond=bond, core_weight=policy.part_coeur, satellite=policy.satellite,
                           equities=tuple(c for c in columns if c != bond and roles.get(c, "candidate") == "candidate"),
                           fixed_allocation=tuple(getattr(policy, "allocation_fixe", {}).items()))


def _current_positions(positions_path: str | Path, transactions_path: str | Path = DEFAULT_TRANSACTIONS
                       ) -> tuple[dict | None, list[str]]:
    """Positions actuelles : journal de transactions en priorité, sinon positions.yaml.

    Renvoie aussi les écarts éventuels entre les deux sources (avertissements).
    """
    from src.ledger import compare_with_positions_file, load_transactions, state_at, to_positions
    from src.positions import load_positions

    positions_file = load_positions(positions_path)
    transactions = load_transactions(transactions_path)
    if transactions is None or transactions.empty:
        return positions_file, []
    state = state_at(transactions)
    from_ledger = to_positions(state)
    notes = [f"Positions issues du journal {Path(transactions_path).name} ({from_ledger['date']})."] + state["warnings"]
    gaps = compare_with_positions_file(from_ledger, positions_file)
    if gaps:
        notes.append("positions.yaml diffère du journal (le journal fait foi) : " + " ; ".join(gaps))
    return from_ledger, notes

"""Lecture des résultats pour le tableau de bord (lecture seule).

Ce module ne lit que des fichiers déjà produits par le moteur :
snapshots JSON mensuels, entrées de paper trading, configuration et valeurs
patrimoniales. Il ne recalcule aucune stratégie et ne passe aucun ordre.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.paper_trading import list_monthly_snapshots, load_monthly_snapshot, load_paper_entries
from src.patrimoine import compute_allocation, load_holdings, load_patrimoine_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MONTHLY_DIR = PROJECT_ROOT / "reports" / "monthly"
PAPER_DIR = PROJECT_ROOT / "reports" / "paper_trading"
PATRIMOINE_CONFIG = PROJECT_ROOT / "config" / "patrimoine.yaml"
HOLDINGS = PROJECT_ROOT / "config" / "holdings.yaml"


def load_snapshots(monthly_dir: str | Path = MONTHLY_DIR) -> list[tuple[Path, dict]]:
    """Snapshots mensuels valides, du plus ancien au plus récent."""
    return [(path, load_monthly_snapshot(path)) for path in list_monthly_snapshots(monthly_dir)]


def _main_strategy(snapshot: dict) -> dict:
    """Stratégie suivie : celle de la politique (schéma 1.3), sinon VT / Momentum."""
    followed = (snapshot.get("policy") or {}).get("followed")
    strategy = (snapshot.get("strategies") or {}).get(followed) if followed else None
    if strategy:
        return strategy
    vt = snapshot.get("volatility_targeted_strategy") or {}
    return vt if vt.get("enabled", True) and vt.get("target_weights") else snapshot.get("momentum_strategy") or {}


def snapshot_history(snapshots: list[tuple[Path, dict]]) -> pd.DataFrame:
    """Une ligne par rapport mensuel : statut, sélection, exposition, alertes."""
    rows = []
    for _, snapshot in snapshots:
        meta = snapshot.get("metadata", {})
        strategy = _main_strategy(snapshot)
        levels = [a.get("level") for a in snapshot.get("alerts", [])]
        rows.append({
            "mois": meta.get("report_month"),
            "signal": meta.get("signal_date"),
            "statut": meta.get("pipeline_status"),
            "sélection": ", ".join(strategy.get("selected_assets") or []) or "cash",
            "exposition": strategy.get("invested_exposure"),
            "cash": strategy.get("cash_weight"),
            "volatilité réalisée": (snapshot.get("risk") or {}).get("realized_volatility"),
            "WARNING": levels.count("WARNING"),
            "CRITICAL": levels.count("CRITICAL"),
        })
    return pd.DataFrame(rows)


def target_allocation(snapshot: dict) -> pd.DataFrame:
    """Allocation cible de la stratégie suivie (poids non nuls), triée."""
    weights = _main_strategy(snapshot).get("target_weights") or {}
    frame = pd.DataFrame(
        [{"actif": k, "poids": v} for k, v in weights.items() if v is not None and v > 1e-9]
    )
    return frame.sort_values("poids", ascending=False).reset_index(drop=True) if not frame.empty else frame


def alerts_table(snapshot: dict) -> pd.DataFrame:
    order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    alerts = sorted(snapshot.get("alerts", []), key=lambda a: order.get(a.get("level"), 3))
    return pd.DataFrame([{"niveau": a.get("level"), "code": a.get("code"), "message": a.get("message")}
                         for a in alerts])


def figure_paths(snapshot: dict, snapshot_path: Path) -> dict[str, Path]:
    """Chemins absolus des graphiques existants référencés par le snapshot."""
    paths = {}
    for name, rel_path in (snapshot.get("figures") or {}).items():
        path = (Path(snapshot_path).parent / rel_path).resolve()
        if path.exists():
            paths[name] = path
    return paths


def journal_table(paper_dir: str | Path = PAPER_DIR) -> pd.DataFrame:
    """Journal de paper trading : une ligne par mois."""
    rows = [{
        "mois": e.get("report_month"),
        "signal": e.get("signal_date"),
        "proposée": e.get("system_suggested_strategy"),
        "décision": e.get("manual_decision_status"),
        "stratégie retenue": e.get("manual_selected_strategy"),
        "confiance": (e.get("decision_journal") or {}).get("confidence"),
        "commentaire": e.get("manual_comment"),
        "validée le": e.get("manual_validated_at"),
    } for e in load_paper_entries(paper_dir)]
    return pd.DataFrame(rows)


def patrimoine_summary(config_path: str | Path = PATRIMOINE_CONFIG,
                       holdings_path: str | Path = HOLDINGS) -> dict | None:
    """Répartition actuelle vs cible à partir des valeurs personnelles (si présentes)."""
    if not Path(config_path).exists():
        return None
    config = load_patrimoine_config(config_path)
    values, as_of = load_holdings(holdings_path)
    allocation = compute_allocation(values, config)
    labels = {e["id"]: e["label"] for e in config["enveloppes"]}
    return {
        "as_of": as_of,
        "allocation": allocation,
        "values": pd.DataFrame([{"enveloppe": labels.get(k, k), "valeur (€)": v} for k, v in values.items()]),
        "monthly_contribution": config["profil"]["versement_mensuel_eur"],
    }


# --------------------------------------------------------------------------- #
# v3 : séries du snapshot, recherche, plan de versement, paper trading, état
# --------------------------------------------------------------------------- #
RESEARCH_JSON = PROJECT_ROOT / "reports" / "research" / "strategy_research_report.json"
CONTRIBUTIONS_DIR = PROJECT_ROOT / "reports" / "contributions"
PRICES = PROJECT_ROOT / "data" / "processed" / "universe_prices.csv"
ASSETS = PROJECT_ROOT / "config" / "assets.yaml"
STRATEGY_CONFIG = PROJECT_ROOT / "config" / "strategy_params.yaml"
POSITIONS = PROJECT_ROOT / "config" / "positions.yaml"
SERIES_LABELS = {"benchmark": "Buy & Hold", "momentum": "Momentum", "momentum_vt": "Momentum + VT"}


def series_frame(snapshot: dict) -> pd.DataFrame:
    """Séries mensuelles du snapshot (schéma 1.2) ; vide pour un snapshot antérieur."""
    records = snapshot.get("series") or []
    if not records:
        return pd.DataFrame()
    frame = pd.DataFrame(records)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date")


def long_series(frame: pd.DataFrame, suffix: str) -> pd.DataFrame:
    """Format long ``date, stratégie, valeur`` pour les graphiques Altair."""
    columns = {c: SERIES_LABELS.get(c.removesuffix(f"_{suffix}"), c) for c in frame.columns if c.endswith(f"_{suffix}")}
    if not columns:
        return pd.DataFrame(columns=["date", "stratégie", "valeur"])
    data = frame[list(columns)].rename(columns=columns).reset_index()
    return data.melt(id_vars="date", var_name="stratégie", value_name="valeur").dropna()


def load_research(path: str | Path = RESEARCH_JSON) -> dict | None:
    import json

    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def latest_plan(directory: str | Path = CONTRIBUTIONS_DIR) -> Path | None:
    plans = sorted(Path(directory).glob("*-plan.md")) if Path(directory).is_dir() else []
    return plans[-1] if plans else None


def paper_ledger(paper_dir: str | Path = PAPER_DIR, prices_path: str | Path = PRICES,
                 config_path: str | Path = STRATEGY_CONFIG, assets_path: str | Path = ASSETS) -> dict | None:
    """Portefeuille fictif du journal (lecture des fichiers, aucun ordre)."""
    from src.data_loader import load_prices
    from src.monthly_pipeline import load_config
    from src.paper_ledger import build_paper_ledger
    from src.universe import asset_roles, load_universe

    if not Path(prices_path).exists():
        return None
    config = load_config(config_path)
    roles = asset_roles(load_universe(assets_path))
    proxy = next((t for t, r in roles.items() if r == "cash_proxy"), None)
    return build_paper_ledger(load_paper_entries(paper_dir), load_prices(prices_path),
                              benchmark=config.benchmark_ticker, transaction_cost=config.backtest.transaction_cost,
                              cash_proxy=proxy if config.universe.use_cash_proxy_return else None,
                              fallback_cash_return=config.backtest.cash_return)


def lab_status(prices_path: str | Path = PRICES, assets_path: str | Path = ASSETS,
               monthly_dir: str | Path = MONTHLY_DIR, paper_dir: str | Path = PAPER_DIR) -> dict:
    from src.routine import collect_status
    from src.universe import asset_roles, load_universe

    return collect_status(data_path=prices_path, configured_tickers=list(asset_roles(load_universe(assets_path))),
                          monthly_dir=monthly_dir, paper_dir=paper_dir)


def positions_table(positions_path: str | Path = POSITIONS, prices_path: str | Path = PRICES) -> pd.DataFrame | None:
    from src.data_loader import load_prices
    from src.positions import load_positions, value_positions

    positions = load_positions(positions_path)
    if positions is None or not Path(prices_path).exists():
        return None
    return value_positions(positions, load_prices(prices_path))["lignes"]


# --------------------------------------------------------------------------- #
# v4 : politique, portefeuille réel, stress tests
# --------------------------------------------------------------------------- #
POLICY = PROJECT_ROOT / "config" / "policy.yaml"
TRANSACTIONS = PROJECT_ROOT / "config" / "transactions.csv"
STRESS_JSON = PROJECT_ROOT / "reports" / "research" / "stress_report.json"


def policy_view(policy_path: str | Path = POLICY, research_path: str | Path = RESEARCH_JSON,
                monthly_dir: str | Path = MONTHLY_DIR) -> dict:
    """Politique, contrôles informatifs et stratégies du dernier rapport."""
    from src.policy import load_policy, policy_checks

    policy = load_policy(policy_path)
    research = load_research(research_path)
    snapshots = load_snapshots(monthly_dir)
    snapshot = snapshots[-1][1] if snapshots else None
    return {"policy": policy, "checks": policy_checks(policy, research, snapshot), "snapshot": snapshot}


def real_portfolio(transactions_path: str | Path = TRANSACTIONS, prices_path: str | Path = PRICES,
                   config_path: str | Path = STRATEGY_CONFIG, patrimoine_path: str | Path = PATRIMOINE_CONFIG) -> dict:
    """Performance réelle et règles du PEA (lecture des fichiers personnels)."""
    from src.data_loader import load_prices
    from src.ledger import contribution_regularity, load_transactions, pea_status, portfolio_performance
    from src.monthly_pipeline import load_config

    transactions = load_transactions(transactions_path)
    empty = transactions is not None and transactions.empty
    if empty:
        transactions = None  # journal créé mais encore vide : rien à valoriser
    pea_cfg = (load_patrimoine_config(patrimoine_path).get("pea") or {}) if Path(patrimoine_path).exists() else {}
    pea = pea_status(transactions, pea_cfg.get("date_ouverture"),
                     ceiling=float(pea_cfg.get("plafond_versements_eur", 150_000)))
    perf, regularity = None, None
    if transactions is not None and Path(prices_path).exists():
        config = load_config(config_path)
        prices = load_prices(prices_path)
        perf = portfolio_performance(transactions, prices, benchmark=config.benchmark_ticker)
        regularity = contribution_regularity(transactions, benchmark=prices.get(config.benchmark_ticker))
    return {"perf": perf, "pea": pea, "has_transactions": transactions is not None, "regularity": regularity,
            "empty_journal": empty}


def crash_rule_view(policy_path: str | Path | None = None, monthly_dir: str | Path = MONTHLY_DIR) -> dict | None:
    """Règle de krach de la politique et son état dans le dernier rapport (si disponible)."""
    from src.policy import load_policy

    policy = load_policy(policy_path or POLICY)
    if not policy.regle_krach:
        return None
    snapshots = load_snapshots(monthly_dir)
    state = ((snapshots[-1][1].get("policy") or {}).get("crash_rule") or {}) if snapshots else {}
    return {"text": policy.regle_krach, "threshold": policy.seuil_krach,
            "current_drawdown": state.get("current_drawdown"), "triggered": bool(state.get("triggered")),
            "month": snapshots[-1][1]["metadata"]["report_month"] if snapshots and state else None}


def load_stress(path: str | Path = STRESS_JSON) -> dict | None:
    import json

    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

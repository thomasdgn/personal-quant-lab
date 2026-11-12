"""Veille locale en simulation : état persistant, expiration, aucune émission externe."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import pandas as pd

from src.broker import load_broker_profile
from src.contribution_plan import plan_contribution
from src.data_loader import load_prices
from src.ledger import load_transactions, state_at
from src.macro import load_observations, macro_context
from src.pea_account import readiness
from src.policy import load_policy
from src.positions import last_prices
from src.universe import load_universe
from src.vehicles import map_target_to_vehicles


def run_watch(root: Path, *, output_dir) -> dict:
    root, output = Path(root), Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    as_of = pd.Timestamp(now).tz_convert("Europe/Paris").tz_localize(None)
    broker = load_broker_profile(root / "config/broker.yaml")
    prices = load_prices(root / "data/processed/universe_prices.csv")
    policy = load_policy(root / "config/policy.yaml")
    transactions = load_transactions(root / "config/transactions.csv")
    holdings, cash = {}, 0.
    if transactions is not None and not transactions.empty:
        state = state_at(transactions)["enveloppes"].get("pea", {})
        holdings, cash = state.get("parts", {}), state.get("liquidites", 0.)
    quotes = last_prices(prices)["prix"].to_dict()
    assets = load_universe(root / "config/assets.yaml")
    followed = policy.strategie_suivie
    weights = dict(policy.allocation_fixe) if followed == "allocation_fixe" else {}
    # Le mode recherche n'est pas une approbation d'une politique tactique.
    issues = [] if weights else ["Politique tactique : cible courante validée et fraîche requise."]
    mapped, vehicle_notes = map_target_to_vehicles(weights, {t: q * quotes.get(t, 0) for t, q in holdings.items()},
                                                   quotes, assets, cash) if weights else ({"CASH": 1.}, [])
    tickers = {t for t in mapped if t != "CASH"} | set(holdings)
    ready = readiness(prices, tickers, transactions_path=root / "config/transactions.csv",
                      receipt_path=root / "config/reconciliation.json", as_of=as_of)
    issues += ready["issues"]
    for ticker in tickers:
        issues.extend(broker.check_product(ticker, assets))
    events: list[dict] = []
    if issues:
        events.append({"kind": "TECHNICAL", "code": "PEA_NOT_READY", "action": "ATTENDRE",
                       "message": " ; ".join(sorted(set(issues)))})
    else:
        plan = plan_contribution(holdings, {t: quotes[t] for t in tickers}, mapped,
                                 contribution=0., cash_available=cash, fee_model=broker.fee_model())
        buys = plan["table"].query("parts_a_acheter > 0") if not plan["table"].empty else plan["table"]
        if not buys.empty:
            orders = []
            for ticker, row in buys.iterrows():
                asset = next(a for a in assets if a["ticker"] == ticker)
                orders.append({"ticker": ticker, "isin": asset["fiche"]["isin"], "side": "BUY",
                               "quantity": int(row["parts_a_acheter"]), "amount": float(row["montant"]),
                               "estimated_fee_and_spread": float(row["frais"]),
                               "quote_date": str(prices[ticker].last_valid_index().date())})
            events.append({"kind": "INVESTMENT", "code": "CONTRIBUTION_AVAILABLE", "action": "RENFORCER",
                           "strategy": followed, "orders": orders, "cash_after": plan["cash_after"],
                           "invalidation": "Cours, cash, positions, frais ou politique modifiés ; sinon expiration.",
                           "message": "Cash déjà crédité disponible pour la politique actuelle.",
                           "risks": "Baisse possible des marchés ; aucune surperformance tactique validée.",
                           "execution_status": "NON_EXECUTE"})
    newly_detected = []
    with sqlite3.connect(output / "events.sqlite3") as db:
        db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)")
        for event in events:
            serialized = json.dumps(event, sort_keys=True, ensure_ascii=False)
            identity = hashlib.sha256(serialized.encode()).hexdigest()
            event.update({"id": identity, "created_at": now.isoformat(),
                          "expires_at": (now + timedelta(days=1)).isoformat(), "delivery": "DRY_RUN"})
            cursor = db.execute("INSERT OR IGNORE INTO events VALUES (?, ?, ?)",
                                (identity, json.dumps(event, ensure_ascii=False), now.isoformat()))
            if cursor.rowcount:
                newly_detected.append(event)
    macro = macro_context(load_observations(root / "data/macro/observations.csv"), now)
    payload = {"as_of": now.isoformat(), "mode": "DRY_RUN", "followed": followed,
               "ready": not issues, "issues": sorted(set(issues)), "new_events": newly_detected,
               "current_events": events, "macro": macro, "vehicle_notes": vehicle_notes,
               "llm_input": {"role": "Expliquer les données ci-jointes sans modifier les calculs. Citer les sources macro. Présenter les arguments contraires.",
                             "events": events, "macro": macro},
               "external_notifications_sent": 0}
    (output / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ready": not issues, "issues": sorted(set(issues)), "new_events": len(newly_detected),
            "external_notifications_sent": 0, "report": str(output / "latest.json"), "mode": "DRY_RUN"}

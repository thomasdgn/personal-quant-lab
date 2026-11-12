"""Compte en parts entières, apports et frais par côté ; signaux exécutés après publication.

Les séries ajustées sont autorisées pour l'exploration, jamais présentées comme
un rejeu exact du compte. Pour un rejeu réel, fournir des cours non ajustés et
les distributions/splits : ces événements ne sont pas inventés ici.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.costs import FeeModel


def simulate_account(prices: pd.DataFrame, targets: pd.DataFrame, *, fee_model: FeeModel,
                     initial_capital=1000.0, monthly_contribution=100.0, execution_delay=1,
                     mode="target", band=.05, max_trades=4, price_basis="adjusted_research_proxy",
                     rules_by_signal: dict | None = None) -> dict:
    if prices.empty or not prices.index.is_monotonic_increasing or prices.index.has_duplicates:
        raise ValueError("Prix non vides, uniques et triés requis.")
    if np.isinf(prices.to_numpy(dtype=float)).any() or (prices <= 0).any().any():
        raise ValueError("Les cours disponibles doivent être finis et strictement positifs.")
    if not all(math.isfinite(v) and v >= 0 for v in (initial_capital, monthly_contribution)):
        raise ValueError("Capital et versements positifs et finis requis.")
    if execution_delay < 1 or max_trades < 1 or mode not in ("target", "contribution", "bands"):
        raise ValueError("Paramètres d'exécution invalides.")
    targets = targets.sort_index().copy()
    if targets.index.has_duplicates or targets.empty or not np.isfinite(targets.to_numpy()).all() or (targets < 0).any().any():
        raise ValueError("Signaux uniques, finis et positifs requis.")
    if not np.allclose(targets.sum(axis=1), 1):
        raise ValueError("Chaque allocation doit sommer à 1.")
    assets = [t for t in targets if t != "CASH"]
    if any(t not in prices for t in assets):
        raise ValueError("Cours manquants pour une exposition cible.")
    schedule = {}
    for signal_date, target in targets.iterrows():
        # Strictement après la date d'information, même pour un signal de clôture.
        loc = prices.index.searchsorted(signal_date, side="right") + execution_delay - 1
        if loc < len(prices):
            schedule[prices.index[loc]] = (signal_date, target)
    holdings = {t: 0 for t in assets}
    cash = float(initial_capital)
    target = {"CASH": 1.0}
    rows: list[dict] = []
    orders: list[dict] = []
    old_month = None
    month_orders = 0
    contributed = float(initial_capital)
    current_signal = None
    last_known = {}
    for day, quote_row in prices[assets].iterrows():
        month = day.to_period("M")
        new_month = month != old_month
        flow = monthly_contribution if new_month else 0.0
        if new_month:
            cash += flow
            contributed += flow
            month_orders = 0
            old_month = month
        for ticker, value in quote_row.items():
            if pd.notna(value) and np.isfinite(value) and value > 0:
                last_known[ticker] = float(value)
        if any(holdings[t] and (pd.isna(quote_row[t]) or quote_row[t] <= 0) for t in assets):
            raise ValueError(f"Cours de valorisation manquant pour une position détenue le {day}.")
        changed = day in schedule
        if changed:
            current_signal, values = schedule[day]
            target = values.to_dict()
            if rules_by_signal and current_signal in rules_by_signal:
                mode, band = rules_by_signal[current_signal]
        before = cash + sum(holdings[t] * last_known.get(t, 0) for t in assets)
        can_trade = changed or new_month
        if can_trade and before > 0 and current_signal is not None:
            deviation = max(abs(holdings[t] * last_known.get(t, 0) / before - target.get(t, 0)) for t in assets)
            sell_allowed = mode == "target" or (mode == "bands" and deviation > band)
            # Toutes les ventes précèdent les achats, puis budget recalculé net de frais.
            if sell_allowed:
                for t in assets:
                    q = quote_row[t]
                    if month_orders >= max_trades or pd.isna(q) or q <= 0:
                        continue
                    wanted = math.floor(target.get(t, 0) * before / q + 1e-9)
                    qty = max(0, holdings[t] - wanted)
                    if qty:
                        amount = qty * q
                        fee = fee_model.order_cost(amount, t, side="SELL")
                        if fee >= amount:
                            continue
                        cash += amount - fee
                        holdings[t] -= qty
                        month_orders += 1
                        orders.append({"date": day, "signal_date": current_signal, "ticker": t,
                                       "side": "SELL", "quantity": qty, "amount": amount, "fee": fee})
            # Allocation des nouveaux achats par déficit absolu ; pas de fractions.
            available_slots = max_trades - month_orders
            for _ in range(available_slots):
                nav = cash + sum(holdings[t] * last_known.get(t, 0) for t in assets)
                gaps = {t: target.get(t, 0) * nav - holdings[t] * last_known.get(t, 0) for t in assets}
                candidates = sorted(assets, key=lambda t: gaps[t], reverse=True)
                bought = False
                for t in candidates:
                    q = quote_row[t]
                    if pd.isna(q) or q <= 0 or gaps[t] <= 0:
                        continue
                    reserve = target.get("CASH", 0) * nav
                    spendable = max(cash - reserve, 0)
                    qty = math.floor(min(max(gaps[t], fee_model.minimum_order_amount), spendable) / q)
                    while qty > 0 and qty * q + fee_model.order_cost(qty * q, t) > spendable + 1e-9:
                        qty -= 1
                    amount = qty * q
                    # Un lot minimal peut franchir la cible, mais doit réduire l'écart.
                    if not fee_model.admissible(amount) or amount > 2 * gaps[t] + 1e-8:
                        continue
                    fee = fee_model.order_cost(amount, t)
                    cash -= amount + fee
                    holdings[t] += qty
                    month_orders += 1
                    orders.append({"date": day, "signal_date": current_signal, "ticker": t,
                                   "side": "BUY", "quantity": qty, "amount": amount, "fee": fee})
                    bought = True
                    break
                if not bought:
                    break
        nav = cash + sum(holdings[t] * last_known.get(t, 0) for t in assets)
        if cash < -1e-7:
            raise ValueError("Cash négatif dans le simulateur.")
        previous = rows[-1]["nav"] if rows else initial_capital
        ret = nav / (previous + flow) - 1 if previous + flow else 0.0
        rows.append({"date": day, "nav": nav, "cash": cash, "contribution": flow,
                     "contributed": contributed, "return": ret,
                     **{f"shares_{t}": holdings[t] for t in assets}})
    curve = pd.DataFrame(rows).set_index("date")
    return {"curve": curve, "orders": pd.DataFrame(orders), "price_basis": price_basis,
            "execution": f"clôture de la séance +{execution_delay} après le signal ; pas d'exécution intrajournalière",
            "status": "exploratory" if price_basis == "adjusted_research_proxy" else "requires_corporate_action_validation"}

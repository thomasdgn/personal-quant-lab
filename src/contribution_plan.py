"""Planificateur de versement mensuel : **proposition** d'achats en parts entières.

Principe (rééquilibrage par les apports, sans vente) :

1. budget = liquidités disponibles dans l'enveloppe + versement du mois ;
2. valeur totale après versement = titres détenus + budget ;
3. valeur cible de chaque ETF = poids cible × valeur totale ; le poids ``CASH``
   de la cible reste en liquidités ;
4. achats glouton, une part à la fois, sur l'ETF dont l'écart à la cible est le
   plus grand, tant que l'achat réduit l'écart (écart restant ≥ ½ part) et que
   le budget couvre le prix **et** les frais supplémentaires ;
5. un ordre dont les frais dépassent ``max_fee_rate`` de son montant est
   abandonné (l'argent reste en liquidités) ;
5 bis. fréquence d'achat (``profil.frequence_achat_mois``) : les mois d'attente,
   aucun achat n'est proposé et le versement s'accumule en liquidités ; le mois
   d'achat investit les versements cumulés (moins d'ordres, donc moins de frais
   fixes) ;
6. si la dérive après achats dépasse la tolérance, un rééquilibrage
   **optionnel** avec ventes est chiffré (jamais imposé).

**Aucun ordre n'est passé** : ce module produit une proposition à relire et à
saisir soi-même chez son courtier.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from src.costs import FeeModel

CASH = "CASH"


def purchase_calendar(month: str, frequency: int = 1, first_month: str | None = None) -> dict:
    """Mois d'achat ou d'attente pour un achat tous les ``frequency`` mois.

    Les mois d'achat sont ``first_month``, puis tous les ``frequency`` mois
    (défaut : janvier de l'année de ``month``). ``month`` et ``first_month`` au
    format AAAA-MM.
    """
    if isinstance(frequency, bool) or not isinstance(frequency, int) or not 1 <= frequency <= 12:
        raise ValueError("La fréquence d'achat doit être un entier entre 1 et 12 mois.")
    current = pd.Period(month, freq="M")
    if first_month is None and 12 % frequency:
        raise ValueError("Une date premier_mois_achat persistante est requise pour cette fréquence.")
    anchor = pd.Period(first_month, freq="M") if first_month else pd.Period(f"{current.year}-01", freq="M")
    distance = (current - anchor).n
    if distance < 0:
        return {"month": str(current), "frequency": frequency, "buy": False,
                "months_to_next": -distance, "next_buy": str(anchor)}
    offset = distance % frequency
    wait = 0 if offset == 0 else frequency - offset
    return {"month": str(current), "frequency": frequency, "buy": wait == 0, "months_to_next": wait,
            "next_buy": str(current + wait)}


def resolve_target(entries: list[dict]) -> dict:
    """Allocation cible : stratégie de la dernière décision APPROVED_PAPER,
    appliquée aux poids cibles de l'entrée la plus récente ; sinon benchmark."""
    if not entries:
        raise ValueError("Journal vide : lance d'abord `python main.py run-month`.")
    ordered = sorted(entries, key=lambda e: e.get("report_month") or "")
    latest = ordered[-1]
    approved = [e for e in ordered if e.get("manual_decision_status") == "APPROVED_PAPER"]
    strategy = approved[-1].get("manual_selected_strategy") if approved else "benchmark"
    weights = (latest.get("target_weights") or {}).get(strategy)
    if not weights:
        strategy, weights = "benchmark", (latest.get("target_weights") or {}).get("benchmark")
    if not weights:
        raise ValueError(f"Aucun poids cible exploitable dans l'entrée {latest.get('report_month')}.")
    return {"strategy": strategy, "weights": {k: float(v) for k, v in weights.items() if v},
            "report_month": latest.get("report_month"), "signal_date": latest.get("signal_date"),
            "from_decision": bool(approved)}


def plan_contribution(
    holdings: dict[str, float],
    quotes: dict[str, float],
    target_weights: dict[str, float],
    *,
    contribution: float,
    cash_available: float = 0.0,
    fee_model: FeeModel | None = None,
    tolerance_pct: float = 5.0,
    max_fee_rate: float = 0.02,
    buy: bool = True,
) -> dict:
    """Calcule la proposition d'achats (parts entières, sans vente).

    Parameters
    ----------
    holdings:
        ``{ticker: parts détenues}`` dans l'enveloppe.
    quotes:
        ``{ticker: dernier prix}`` pour les tickers détenus et cibles.
    target_weights:
        Poids cibles (somme 1, ``CASH`` compris).
    contribution, cash_available:
        Versement du mois et liquidités déjà présentes (euros, ≥ 0).
    buy:
        ``False`` pour un mois d'attente (fréquence d'achat) : aucun achat, le
        budget reste en liquidités.
    """
    fee_model = fee_model or FeeModel()
    if not all(math.isfinite(v) and v >= 0 for v in (contribution, cash_available)):
        raise ValueError("Versement et liquidités doivent être positifs ou nuls.")
    if abs(sum(target_weights.values()) - 1.0) > 1e-6 or any(not math.isfinite(w) or w < 0 for w in target_weights.values()):
        raise ValueError("Les poids cibles doivent être positifs et sommer à 1.")
    tickers = sorted((set(holdings) | set(target_weights)) - {CASH})
    missing = [t for t in tickers if holdings.get(t, 0) > 0 or target_weights.get(t, 0) > 0]
    missing = [t for t in missing if not quotes.get(t) or not math.isfinite(quotes[t]) or quotes[t] <= 0]
    if missing:
        raise ValueError(f"Prix manquant ou invalide pour : {', '.join(missing)}.")

    budget = float(cash_available) + float(contribution)
    current_value = {t: holdings.get(t, 0.0) * quotes.get(t, 0.0) for t in tickers}
    total = sum(current_value.values()) + budget
    target_value = {t: target_weights.get(t, 0.0) * total for t in tickers}
    shares = {t: 0 for t in tickers}
    spent = {t: 0.0 for t in tickers}  # montant + frais par ordre
    remaining = budget

    def gap(t: str) -> float:
        return target_value[t] - current_value[t] - shares[t] * quotes[t]

    while buy:
        best, best_gap, best_quantity = None, 0.0, 0
        for t in tickers:
            if target_weights.get(t, 0.0) <= 0:
                continue
            price = quotes[t]
            quantity = 1 if shares[t] else max(1, math.ceil((fee_model.minimum_order_amount - 1e-9) / price))
            if gap(t) < quantity * price / 2.0:
                continue
            new_amount = (shares[t] + quantity) * price
            extra = new_amount + fee_model.order_cost(new_amount, t) - spent[t]
            if extra > remaining + 1e-9:
                continue
            if gap(t) / max(target_value[t], 1e-9) > best_gap:
                best, best_gap, best_quantity = t, gap(t) / max(target_value[t], 1e-9), quantity
        if best is None:
            break
        new_amount = (shares[best] + best_quantity) * quotes[best]
        new_spent = new_amount + fee_model.order_cost(new_amount, best)
        remaining -= new_spent - spent[best]
        shares[best] += best_quantity
        spent[best] = new_spent

    notes: list[str] = []
    if fee_model.minimum_order_amount:
        notes.append(f"Minimum d'achat : {fee_model.minimum_order_amount:.2f} € par ordre, hors frais ; "
                     "les liquidités non utilisables sont reportées.")
    for t in tickers:
        if target_weights.get(t, 0.0) > 0 and shares[t] == 0 and quotes[t] > budget:
            notes.append(f"Une part de {t} coûte {quotes[t]:,.2f} €, plus que le budget ({budget:,.2f} €) : "
                         "accumuler les versements sur plusieurs mois ou envisager un ETF équivalent à part "
                         "moins chère (ex. WPEA.PA pour le MSCI World).")
    for t in tickers:
        amount = shares[t] * quotes[t]
        if shares[t] and fee_model.effective_rate(amount, t) > max_fee_rate:
            notes.append(f"Ordre {t} de {amount:,.2f} € abandonné : frais {fee_model.order_cost(amount, t):,.2f} € "
                         f"(> {max_fee_rate:.0%} du montant). Mieux vaut regrouper sur un mois suivant.")
            remaining += spent[t]
            shares[t], spent[t] = 0, 0.0

    orders: list[dict[str, Any]] = []
    for t in tickers:
        amount = shares[t] * quotes[t]
        fee = spent[t] - amount if shares[t] else 0.0
        after_value = current_value[t] + amount
        orders.append({"ticker": t, "prix": quotes.get(t, float("nan")), "parts_actuelles": holdings.get(t, 0.0),
                       "valeur_actuelle": current_value[t], "poids_cible": target_weights.get(t, 0.0),
                       "parts_a_acheter": shares[t], "montant": amount, "frais": fee, "valeur_apres": after_value})
    table = pd.DataFrame(orders).set_index("ticker") if orders else pd.DataFrame()
    total_after = sum(current_value.values()) + sum(o["montant"] for o in orders) + remaining
    cash_after = remaining
    weights_after = {t: row["valeur_apres"] / total_after for t, row in table.iterrows()} if total_after else {}
    weights_after[CASH] = cash_after / total_after if total_after else 0.0
    current_total = sum(current_value.values()) + float(cash_available)
    weights_before = {t: current_value[t] / current_total for t in tickers} if current_total else {}
    if current_total:
        weights_before[CASH] = float(cash_available) / current_total
    drift = {k: (weights_after.get(k, 0.0) - target_weights.get(k, 0.0)) * 100
             for k in set(weights_after) | set(target_weights)}
    max_drift = max((abs(v) for v in drift.values()), default=0.0)

    cash_target_value = target_weights.get(CASH, 0.0) * total
    if not buy:
        notes.insert(0, f"Mois d'attente : aucun achat, {remaining:,.2f} € restent en liquidités jusqu'au prochain "
                        "mois d'achat.")
    elif remaining > 0:
        reasons = []
        if cash_target_value > 0:
            reasons.append(f"{cash_target_value:,.2f} € de liquidités visées par la cible ({target_weights[CASH]:.0%} CASH)")
        leftover_granularity = max(0.0, remaining - cash_target_value)
        if leftover_granularity > 0.005:
            reasons.append(f"{leftover_granularity:,.2f} € non investissables en parts entières sans dépasser la cible "
                           "ou le budget (frais compris)")
        notes.insert(0, f"Liquidités restantes : {remaining:,.2f} € ({'; '.join(reasons) or 'arrondis'}).")

    rebalancing = None
    if max_drift > tolerance_pct:
        trades, cost = [], 0.0
        for t in tickers:
            quote = quotes.get(t)
            if not quote:
                continue
            delta_value = target_weights.get(t, 0.0) * total_after - weights_after.get(t, 0.0) * total_after
            parts = math.trunc(delta_value / quote)
            if parts:
                side = "SELL" if parts < 0 else "BUY"
                if not fee_model.admissible(abs(parts * quote), side=side):
                    continue
                fee = fee_model.order_cost(parts * quote, t, side=side)
                cost += fee
                trades.append({"ticker": t, "parts": parts, "montant": parts * quote, "frais": fee})
        if any(trade["parts"] < 0 for trade in trades):
            rebalancing = {"trades": trades, "total_cost": cost}

    return {
        "budget": budget, "contribution": float(contribution), "cash_available": float(cash_available),
        "table": table, "total_spent": budget - remaining, "total_fees": float(sum(o["frais"] for o in orders)),
        "cash_after": cash_after, "weights_before": weights_before, "weights_after": weights_after,
        "drift_pct": drift, "max_drift_pct": max_drift, "tolerance_pct": tolerance_pct,
        "rebalancing": rebalancing, "notes": notes,
    }


def _target_origin(target: dict) -> str:
    """Provenance de la cible, pour l'affichage."""
    if target.get("source") == "politique":
        return " - allocation fixe de la politique (config/policy.yaml)"
    if target["from_decision"]:
        return f" (rapport {target['report_month']}, signal {target['signal_date']})"
    return (f" (rapport {target['report_month']}, signal {target['signal_date']})"
            " - aucune décision approuvée : benchmark par défaut")


def plan_lines(plan: dict, target: dict) -> list[str]:
    """Résumé console (cp1252) de la proposition."""
    lines = [
        "PROPOSITION de versement - aucun ordre passé, à saisir soi-même chez le courtier",
        f"Cible : {target['strategy']}" + _target_origin(target),
        f"Budget : {plan['budget']:,.2f} € (versement {plan['contribution']:,.2f} € + liquidités "
        f"{plan['cash_available']:,.2f} €)",
    ]
    buys = plan["table"][plan["table"]["parts_a_acheter"] > 0] if not plan["table"].empty else plan["table"]
    if buys.empty:
        lines.append("Aucun achat proposé.")
    for ticker, row in buys.iterrows():
        lines.append(f"  ACHETER {int(row['parts_a_acheter']):>4} x {ticker:9} à ~{row['prix']:,.2f} € "
                     f"= {row['montant']:,.2f} € (frais estimés {row['frais']:,.2f} €)")
    lines.append(f"Total engagé : {plan['total_spent']:,.2f} € dont frais {plan['total_fees']:,.2f} € ; "
                 f"liquidités après : {plan['cash_after']:,.2f} €")
    lines.append(f"Dérive max après achats : {plan['max_drift_pct']:.1f} pts (tolérance {plan['tolerance_pct']:.0f} pts)")
    if plan["rebalancing"]:
        lines.append(f"Rééquilibrage OPTIONNEL avec ventes possible (coût estimé "
                     f"{plan['rebalancing']['total_cost']:,.2f} €) : voir le rapport.")
    lines += [f"Note : {note}" for note in plan["notes"]]
    return lines


def _pct(value: float) -> str:
    return f"{value:.1%}"


def generate_plan_report(plan: dict, target: dict, output_path: str | Path, *, positions_date: str | None = None) -> Path:
    """Rapport Markdown de la proposition de versement."""
    lines = [
        f"# Plan de versement — {date.today():%Y-%m}", "",
        "> **Proposition uniquement, aucun ordre passé.** Vérifier les prix, les frais réels et la "
        "cohérence avec ta situation avant de saisir quoi que ce soit chez ton courtier.", "",
        f"- Cible : **{target['strategy']}**" + _target_origin(target).replace(" - ", " — "),
        f"- Positions au : {positions_date or 'non précisé'}",
        f"- Budget : {plan['budget']:,.2f} € (versement {plan['contribution']:,.2f} € + liquidités "
        f"{plan['cash_available']:,.2f} €)", "",
        "## Achats proposés (parts entières, sans vente)", "",
        "| Ticker | Prix | Parts détenues | Poids actuel | Poids cible | Parts à acheter | Montant | Frais | Poids après |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for ticker, row in plan["table"].iterrows():
        lines.append(
            f"| {ticker} | {row['prix']:,.2f} € | {row['parts_actuelles']:g} | "
            f"{_pct(plan['weights_before'].get(ticker, 0.0))} | {_pct(row['poids_cible'])} | "
            f"{int(row['parts_a_acheter'])} | {row['montant']:,.2f} € | {row['frais']:,.2f} € | "
            f"{_pct(plan['weights_after'].get(ticker, 0.0))} |"
        )
    lines.append(f"| CASH | | | {_pct(plan['weights_before'].get(CASH, 0.0))} | "
                 f"{_pct(target['weights'].get(CASH, 0.0))} | | | | {_pct(plan['weights_after'].get(CASH, 0.0))} |")
    lines += [
        "", f"Total engagé : **{plan['total_spent']:,.2f} €** dont frais {plan['total_fees']:,.2f} € ; "
        f"liquidités après : {plan['cash_after']:,.2f} €.",
        f"Dérive maximale après achats : {plan['max_drift_pct']:.1f} points (tolérance {plan['tolerance_pct']:.0f}).", "",
    ]
    if plan["notes"]:
        lines += ["## Remarques", ""] + [f"- {note}" for note in plan["notes"]] + [""]
    if plan["rebalancing"]:
        lines += ["## Rééquilibrage optionnel avec ventes (non recommandé par défaut)", "",
                  "La dérive reste au-delà de la tolérance. Ordres théoriques pour revenir à la cible :", "",
                  "| Ticker | Parts (+ achat / − vente) | Montant | Frais |", "| --- | ---: | ---: | ---: |"]
        for trade in plan["rebalancing"]["trades"]:
            lines.append(f"| {trade['ticker']} | {trade['parts']:+d} | {trade['montant']:,.2f} € | {trade['frais']:,.2f} € |")
        lines += ["", f"Coût total estimé : {plan['rebalancing']['total_cost']:,.2f} € (hors fiscalité ; dans un PEA "
                  "les arbitrages ne sont pas imposés tant qu'aucun retrait n'est fait).", ""]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path

"""Audit des frais : ce que coûtent vraiment les ordres, les ETF et la fiscalité.

Trois postes, chiffrés sur l'horizon du profil :

1. **Frais d'ordre** : le plan de versement (``plan_contribution``) est rejoué
   mois après mois aux prix actuels (portefeuille qui grossit, liquidités
   reportées, petits ordres regroupés par la règle des 2 %) ; on compte les
   ordres et les frais réels, pour le barème du courtier et pour des barèmes
   de comparaison ;
2. **Frais annuels des ETF** (TER des fiches produits) de l'allocation achetée ;
3. **Fiscalité** : économie du PEA après 5 ans face à un compte-titres.

La « valeur perdue » d'un frais est ce qu'il serait devenu s'il avait été
investi au rendement supposé (scénario central). Aucun ordre n'est passé.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from src.contribution_plan import CASH, plan_contribution
from src.costs import FeeModel
from src.taxes import TaxConfig


def order_schedule(weights: dict[str, float], quotes: dict[str, float], monthly: float, fee_model: FeeModel, *,
                   months: int = 60, max_fee_rate: float = 0.02) -> dict[str, Any]:
    """Rejoue le plan de versement ``months`` mois (prix constants) : ordres et frais."""
    holdings: dict[str, float] = {}
    cash = 0.0
    orders = 0
    fees = 0.0
    orders_by_ticker: dict[str, int] = {}
    target = {**weights, CASH: max(0.0, 1.0 - sum(weights.values()))}
    for _ in range(months):
        plan = plan_contribution(holdings, quotes, target, contribution=monthly, cash_available=cash,
                                 fee_model=fee_model, max_fee_rate=max_fee_rate)
        table = plan["table"]
        bought = table[table["parts_a_acheter"] > 0] if not table.empty else table
        for ticker, row in bought.iterrows():
            holdings[ticker] = holdings.get(ticker, 0.0) + row["parts_a_acheter"]
            orders_by_ticker[ticker] = orders_by_ticker.get(ticker, 0) + 1
        orders += len(bought)
        fees += float(plan["total_fees"])
        cash = float(plan["cash_after"])
    years = months / 12.0
    contributed = monthly * months
    return {"months": months, "orders_per_year": orders / years, "fees_per_year": fees / years,
            "fee_rate": fees / contributed if contributed else 0.0, "orders_by_ticker": orders_by_ticker,
            "cash_left": cash}


def future_value(monthly_flow: float, annual_return: float, months: int) -> float:
    """Valeur finale d'un flux mensuel constant placé au rendement ``annual_return``."""
    m = (1 + annual_return) ** (1 / 12) - 1
    return monthly_flow * months if abs(m) < 1e-12 else monthly_flow * (((1 + m) ** months - 1) / m) * (1 + m)


def fee_audit(weights: dict[str, float], quotes: dict[str, float], *, monthly: float, capital: float,
              horizon_years: int, annual_return: float, fee_models: dict[str, FeeModel], current: str,
              ter_pct: dict[str, float | None], ter_alternatives: dict[str, dict[str, float]] | None = None,
              taxes: TaxConfig | None = None) -> dict:
    """Audit complet (voir la docstring du module)."""
    taxes = taxes or TaxConfig()
    months = horizon_years * 12
    brokers: dict[str, dict[str, Any]] = {}
    for name, model in fee_models.items():
        schedule = order_schedule(weights, quotes, monthly, model)
        lost = future_value(schedule["fees_per_year"] / 12, annual_return, months)
        brokers[name] = {**schedule, "total_fees": schedule["fees_per_year"] * horizon_years, "value_lost": lost}
    base = brokers[current]

    def weighted_ter(allocation: dict[str, float]) -> float | None:
        known = {t: w for t, w in allocation.items() if ter_pct.get(t) is not None}
        if not known:
            return None
        weighted = sum(float(ter_pct[t] or 0.0) * w for t, w in known.items())
        return weighted / sum(known.values())

    gross = capital * (1 + annual_return) ** horizon_years + future_value(monthly, annual_return, months)
    ter_rows: dict[str, dict[str, Any]] = {"Ton allocation": {"allocation": weights, "ter_pct": weighted_ter(weights)}}
    for label, allocation in (ter_alternatives or {}).items():
        ter_rows[label] = {"allocation": allocation, "ter_pct": weighted_ter(allocation)}
    for row in ter_rows.values():
        ter = (row["ter_pct"] or 0.0) / 100
        without = capital * (1 + annual_return + ter) ** horizon_years + future_value(monthly, annual_return + ter,
                                                                                      months)
        row["value_lost"] = without - gross
    contributed = capital + monthly * months
    gain = max(gross - contributed, 0.0)
    pea_tax = gain * taxes.prelevements_sociaux_pct / 100
    cto_tax = gain * taxes.flat_tax_pct / 100
    cheapest = min(brokers, key=lambda k: brokers[k]["fees_per_year"])
    return {"monthly": monthly, "capital": capital, "horizon_years": horizon_years, "annual_return": annual_return,
            "weights": weights, "current": current, "brokers": brokers, "cheapest": cheapest,
            "saving_vs_cheapest": base["value_lost"] - brokers[cheapest]["value_lost"], "ter": ter_rows,
            "projection": {"contributed": contributed, "gross": gross, "gain": gain},
            "taxes": {"pea": pea_tax, "cto": cto_tax, "saving": cto_tax - pea_tax,
                      "pea_rate": taxes.prelevements_sociaux_pct, "cto_rate": taxes.flat_tax_pct}}


def _eur(value: float) -> str:
    return f"{value:,.0f} €".replace(",", " ")


def fee_audit_lines(audit: dict) -> list[str]:
    """Constats clés (texte), du poste le plus coûteux au moins coûteux."""
    base = audit["brokers"][audit["current"]]
    ter = audit["ter"]["Ton allocation"]
    lines = [f"Frais d'ordre ({audit['current']}) : {base['orders_per_year']:.1f} ordres/an, "
             f"{_eur(base['fees_per_year'])}/an ({base['fee_rate']:.2%} des versements) ; valeur perdue en "
             f"{audit['horizon_years']} ans : {_eur(base['value_lost'])}.",
             f"Frais annuels des ETF : {ter['ter_pct']:.3f} %/an en moyenne ; valeur perdue : "
             f"{_eur(ter['value_lost'])}."]
    if audit["cheapest"] != audit["current"]:
        lines.append(f"Barème le moins cher testé ({audit['cheapest']}) : {_eur(audit['saving_vs_cheapest'])} de plus "
                     f"à l'horizon.")
    lines.append(f"Fiscalité : garder le PEA plus de 5 ans évite {_eur(audit['taxes']['saving'])} d'impôt face à un "
                 f"compte-titres (sur un gain projeté de {_eur(audit['projection']['gain'])}).")
    return lines


def generate_fee_report(audit: dict, output_path: str | Path) -> Path:
    lines = ["# Audit des frais", "", f"Date de génération : {date.today().isoformat()}", "",
             f"Versement de {_eur(audit['monthly'])}/mois pendant {audit['horizon_years']} ans (départ "
             f"{_eur(audit['capital'])}), rendement supposé {audit['annual_return']:.1%}/an (scénario central). "
             "Le plan de versement est rejoué aux prix actuels ; les petits ordres sont regroupés tant que leurs frais "
             "dépasseraient 2 % du montant. Aucun ordre n'est passé.", "",
             "## Constats", ""] + [f"- {line}" for line in fee_audit_lines(audit)]
    lines += ["", "## Frais d'ordre selon le barème", "",
              "| Barème | Ordres / an | Frais / an | % des versements | Frais cumulés | Valeur perdue à l'horizon |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, row in sorted(audit["brokers"].items(), key=lambda kv: kv[1]["fees_per_year"]):
        mark = " **(le tien)**" if name == audit["current"] else ""
        lines.append(f"| {name}{mark} | {row['orders_per_year']:.1f} | {_eur(row['fees_per_year'])} | "
                     f"{row['fee_rate']:.2%} | {_eur(row['total_fees'])} | {_eur(row['value_lost'])} |")
    lines += ["", "## Frais annuels des ETF (TER)", "", "| Allocation | TER moyen | Valeur perdue à l'horizon |",
              "| --- | ---: | ---: |"]
    for label, row in audit["ter"].items():
        ter = "n/a" if row["ter_pct"] is None else f"{row['ter_pct']:.3f} %"
        lines.append(f"| {label} ({', '.join(f'{t} {w:.0%}' for t, w in row['allocation'].items())}) | {ter} | "
                     f"{_eur(row['value_lost'])} |")
    t = audit["taxes"]
    lines += ["", "## Fiscalité à la sortie", "",
              f"Gain projeté {_eur(audit['projection']['gain'])} : impôt {_eur(t['pea'])} dans un PEA de plus de 5 ans "
              f"({t['pea_rate']:.1f} %) contre {_eur(t['cto'])} dans un compte-titres ({t['cto_rate']:.1f} %).", "",
              "_Ordres de grandeur, pas des promesses : le rendement réel sera différent. Les tarifs de comparaison "
              "sont des barèmes types, à vérifier chez les courtiers._", ""]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path

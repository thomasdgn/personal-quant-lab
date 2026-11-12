"""Portefeuille réel à partir du journal de transactions (données personnelles).

Fichier ``config/transactions.csv`` (ignoré par Git ; modèle
``config/transactions.example.csv``) ::

    date,enveloppe,type,ticker,parts,prix,montant,frais,commentaire

Types :

- ``VERSEMENT`` / ``RETRAIT`` : flux externes (``montant``) ;
- ``ACHAT`` / ``VENTE`` : ``parts`` × ``prix`` (``montant`` optionnel, recalculé),
  ``frais`` payés en plus ;
- ``FRAIS`` : frais hors ordre (droits de garde…) ;
- ``DIVIDENDE`` : dividende encaissé en liquidités.

Le module dérive positions et liquidités à toute date, la valorisation
mensuelle, la performance réelle (TWR et TRI), les frais payés et les règles du
PEA (ancienneté, 5 ans, plafond de versements). Il n'exécute **aucun** ordre :
les ordres proposés par le planificateur vont dans un fichier séparé
(``pending_orders.csv``) que l'investisseuse reporte elle-même, une fois
exécutés chez son courtier.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

TYPES = ("VERSEMENT", "RETRAIT", "ACHAT", "VENTE", "FRAIS", "DIVIDENDE")
COLUMNS = ["date", "enveloppe", "type", "ticker", "parts", "prix", "montant", "frais", "commentaire"]
PEA_CEILING_EUR = 150_000.0
PEA_YEARS = 5


# --------------------------------------------------------------------------- #
# Chargement et validation
# --------------------------------------------------------------------------- #
def load_transactions(path: str | Path) -> pd.DataFrame | None:
    """Charge et valide le journal ; ``None`` si le fichier est absent."""
    path = Path(path)
    if not path.exists():
        return None
    frame = pd.read_csv(path, dtype={"ticker": str, "enveloppe": str, "type": str, "commentaire": str})
    missing = [c for c in COLUMNS[:8] if c not in frame.columns]
    if missing:
        raise ValueError(f"{path.name} : colonnes manquantes {', '.join(missing)}.")
    frame = frame.reindex(columns=COLUMNS)
    frame["type"] = frame["type"].str.strip().str.upper()
    frame["enveloppe"] = frame["enveloppe"].fillna("pea").str.strip()
    frame["ticker"] = frame["ticker"].fillna("").str.strip()
    try:
        frame["date"] = pd.to_datetime(frame["date"], format="%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{path.name} : date invalide (format AAAA-MM-JJ attendu) : {exc}") from exc
    for column in ("parts", "prix", "montant", "frais"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame["frais"] = frame["frais"].fillna(0.0)
    for position, row in frame.iterrows():
        line = position + 2  # ligne du fichier (en-tête = 1)
        kind = row["type"]
        if kind not in TYPES:
            raise ValueError(f"{path.name} ligne {line} : type {kind!r} inconnu (attendu : {', '.join(TYPES)}).")
        if not np.isfinite(row["frais"]) or row["frais"] < 0:
            raise ValueError(f"{path.name} ligne {line} : frais négatifs.")
        if kind in ("ACHAT", "VENTE"):
            if not row["ticker"] or not np.isfinite(row["parts"]) or not np.isfinite(row["prix"]) or not (row["parts"] > 0) or not (row["prix"] > 0):
                raise ValueError(f"{path.name} ligne {line} : {kind} exige ticker, parts > 0 et prix > 0.")
            frame.at[position, "montant"] = row["parts"] * row["prix"]
        elif not np.isfinite(row["montant"]) or not (row["montant"] > 0):
            raise ValueError(f"{path.name} ligne {line} : {kind} exige un montant > 0.")
    return frame.sort_values("date", kind="stable").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Positions et liquidités
# --------------------------------------------------------------------------- #
def _cash_delta(row: pd.Series) -> float:
    kind = row["type"]
    if kind in ("VERSEMENT", "DIVIDENDE"):
        return row["montant"] - row["frais"]
    if kind in ("RETRAIT", "FRAIS"):
        return -row["montant"] - row["frais"]
    if kind == "ACHAT":
        return -row["montant"] - row["frais"]
    return row["montant"] - row["frais"]  # VENTE


def state_at(transactions: pd.DataFrame, when: str | pd.Timestamp | None = None) -> dict:
    """Positions (parts) et liquidités par enveloppe à la date ``when`` incluse.

    Raises
    ------
    ValueError
        Vente de plus de parts que détenues.
    """
    when = pd.Timestamp(when) if when is not None else transactions["date"].max()
    state: dict[str, dict] = {}
    warnings: list[str] = []
    for _, row in transactions[transactions["date"] <= when].iterrows():
        env = state.setdefault(row["enveloppe"], {"parts": {}, "liquidites": 0.0})
        if row["type"] == "ACHAT":
            env["parts"][row["ticker"]] = env["parts"].get(row["ticker"], 0.0) + row["parts"]
        elif row["type"] == "VENTE":
            held = env["parts"].get(row["ticker"], 0.0)
            if row["parts"] > held + 1e-9:
                raise ValueError(f"Vente de {row['parts']:g} {row['ticker']} le {row['date'].date()} "
                                 f"alors que {held:g} seulement sont détenues.")
            env["parts"][row["ticker"]] = held - row["parts"]
        env["liquidites"] += _cash_delta(row)
        if env["liquidites"] < -0.01:
            warnings.append(f"Liquidités négatives dans {row['enveloppe']} le {row['date'].date()} "
                            f"({env['liquidites']:,.2f} €) : versement manquant dans le journal ?")
    for env in state.values():
        env["parts"] = {t: p for t, p in env["parts"].items() if abs(p) > 1e-9}
    return {"date": when, "enveloppes": state, "warnings": warnings}


def to_positions(state: dict) -> dict:
    """Même format que ``src.positions.load_positions`` (compatibilité)."""
    lignes = [{"enveloppe": env, "ticker": t, "parts": p}
              for env, content in state["enveloppes"].items() for t, p in content["parts"].items()]
    return {"date": state["date"].date().isoformat(), "lignes": lignes,
            "liquidites_eur": {env: max(content["liquidites"], 0.0) for env, content in state["enveloppes"].items()}}


def compare_with_positions_file(from_ledger: dict, positions_file: dict | None) -> list[str]:
    """Écarts entre positions déduites du journal et ``positions.yaml``."""
    if positions_file is None:
        return []
    a = {(line["enveloppe"], line["ticker"]): line["parts"] for line in from_ledger["lignes"]}
    b = {(line["enveloppe"], line["ticker"]): line["parts"] for line in positions_file["lignes"] if line["parts"]}
    notes = [f"{env} {ticker} : journal {a.get((env, ticker), 0):g} parts, positions.yaml {b.get((env, ticker), 0):g}"
             for env, ticker in sorted(set(a) | set(b)) if abs(a.get((env, ticker), 0) - b.get((env, ticker), 0)) > 1e-9]
    return notes


# --------------------------------------------------------------------------- #
# Performance réelle
# --------------------------------------------------------------------------- #
def monthly_valuation(transactions: pd.DataFrame, prices: pd.DataFrame, envelope: str | None = None) -> pd.DataFrame:
    """Valeur de fin de mois, flux externes du mois et frais payés.

    Les flux (versements - retraits) sont supposés intervenir en **début** de
    mois (convention du TWR ci-dessous). Les mois sans prix pour une ligne
    détenue lèvent une erreur explicite.
    """
    tx = transactions if envelope is None else transactions[transactions["enveloppe"] == envelope]
    if tx.empty:
        raise ValueError("Aucune transaction pour cette enveloppe.")
    monthly_prices = prices.sort_index().resample("ME").last()
    months = pd.date_range(tx["date"].min() + pd.offsets.MonthEnd(0),
                           min(monthly_prices.index.max(), pd.Timestamp.today() + pd.offsets.MonthEnd(0)), freq="ME")
    rows = []
    for month in months:
        state = state_at(tx, month)
        value = 0.0
        for env in state["enveloppes"].values():
            value += env["liquidites"]
            for ticker, parts in env["parts"].items():
                if ticker not in monthly_prices.columns or pd.isna(monthly_prices.at[month, ticker]):
                    raise ValueError(f"Pas de prix de fin de mois pour {ticker} en {month:%Y-%m}.")
                value += parts * monthly_prices.at[month, ticker]
        in_month = tx[(tx["date"] > month - pd.offsets.MonthEnd(1)) & (tx["date"] <= month)]
        flows = in_month.loc[in_month["type"] == "VERSEMENT", "montant"].sum() \
            - in_month.loc[in_month["type"] == "RETRAIT", "montant"].sum()
        fees = in_month["frais"].sum() + in_month.loc[in_month["type"] == "FRAIS", "montant"].sum()
        rows.append({"date": month, "valeur": value, "flux": flows, "frais": fees})
    return pd.DataFrame(rows).set_index("date")


def time_weighted_returns(valuation: pd.DataFrame) -> pd.Series:
    """Rendement mensuel pondéré par le temps : V_t / (V_{t-1} + flux_t) - 1."""
    previous = valuation["valeur"].shift(1).fillna(0.0)
    base = previous + valuation["flux"]
    return (valuation["valeur"] / base.where(base > 0) - 1.0).dropna()


def money_weighted_return(valuation: pd.DataFrame) -> float | None:
    """TRI annualisé : flux en début de mois, valeur finale en fin de dernier mois."""
    flows = valuation["flux"].to_numpy(dtype=float)
    final = float(valuation["valeur"].iloc[-1])
    n = len(flows)
    if n == 0 or flows.sum() <= 0:
        return None
    periods = np.arange(n, 0, -1)

    def npv(rate: float) -> float:
        return float(np.sum(flows * (1.0 + rate) ** periods) - final)

    low, high = -0.99, 1.0
    if npv(low) * npv(high) > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2.0
        if npv(low) * npv(mid) <= 0:
            high = mid
        else:
            low = mid
    return float((1.0 + (low + high) / 2.0) ** 12 - 1.0)


def portfolio_performance(transactions: pd.DataFrame, prices: pd.DataFrame, *, envelope: str = "pea",
                          benchmark: str = "CW8.PA", paper_monthly: pd.DataFrame | None = None) -> dict:
    """Performance réelle vs Buy & Hold (mêmes flux) et vs paper trading (mêmes mois)."""
    valuation = monthly_valuation(transactions, prices, envelope)
    twr = time_weighted_returns(valuation)
    monthly_prices = prices.sort_index().resample("ME").last()
    bench_returns = monthly_prices[benchmark].pct_change(fill_method=None).reindex(twr.index)
    # Buy & Hold avec les mêmes flux, investis en début de mois.
    bench_value, bench_path = 0.0, []
    for month, row in valuation.iterrows():
        r = bench_returns.get(month, np.nan)
        bench_value = (bench_value + row["flux"]) * (1.0 + (0.0 if pd.isna(r) else r))
        bench_path.append(bench_value)
    comparison = {"real_twr": float((1 + twr).prod() - 1) if not twr.empty else None,
                  "benchmark_twr": float((1 + bench_returns.dropna()).prod() - 1) if not bench_returns.dropna().empty
                  else None}
    if paper_monthly is not None and not paper_monthly.empty and not twr.empty:
        common = twr.index.intersection(paper_monthly.index)
        if len(common):
            comparison["common_months"] = int(len(common))
            comparison["real_twr_common"] = float((1 + twr.loc[common]).prod() - 1)
            comparison["paper_twr_common"] = float((1 + paper_monthly.loc[common, "paper_return"]).prod() - 1)
            comparison["system_twr_common"] = float((1 + paper_monthly.loc[common, "system_return"]).prod() - 1)
    fees_total = float(valuation["frais"].sum())
    contributions = float(valuation["flux"].sum())
    return {
        "start": valuation.index.min().date().isoformat(), "end": valuation.index.max().date().isoformat(),
        "valuation": valuation, "twr_monthly": twr, "final_value": float(valuation["valeur"].iloc[-1]),
        "net_contributions": contributions, "gain": float(valuation["valeur"].iloc[-1]) - contributions,
        "mwr": money_weighted_return(valuation), "fees_total": fees_total,
        "fees_pct_of_contributions": fees_total / contributions if contributions > 0 else None,
        "benchmark_same_flows_value": float(bench_path[-1]) if bench_path else None,
        "comparison": comparison,
    }


# --------------------------------------------------------------------------- #
# Règles du PEA
# --------------------------------------------------------------------------- #
def contribution_regularity(transactions: pd.DataFrame | None, *, benchmark: pd.Series | None = None,
                            as_of: str | pd.Timestamp | None = None, stress_drawdown: float = 0.10) -> dict | None:
    """Le seul indicateur de discipline : as-tu versé chaque mois, y compris quand ça baissait ?

    Mois comptés du premier versement au mois ``as_of`` inclus (défaut : aujourd'hui).
    Un mois « de baisse » est un mois où le benchmark est à plus de ``stress_drawdown``
    sous son plus haut.
    """
    if transactions is None:
        return None
    deposits = transactions.loc[transactions["type"] == "VERSEMENT", "date"]
    if deposits.empty:
        return None
    start = deposits.min().to_period("M")
    end = pd.Timestamp(as_of or date.today()).to_period("M")
    months = pd.period_range(start, max(start, end), freq="M")
    paid = set(deposits.dt.to_period("M"))
    flags = [m in paid for m in months]
    streak = 0
    for flag in reversed(flags):
        if not flag:
            break
        streak += 1
    stress_months = []
    if benchmark is not None and not benchmark.dropna().empty:
        monthly = benchmark.dropna().resample("ME").last()
        drawdown = monthly / monthly.cummax() - 1.0
        stress_months = [m for m in months if m in set(drawdown[drawdown <= -stress_drawdown].index.to_period("M"))]
    return {"months": len(months), "months_paid": int(sum(flags)), "current_streak": streak,
            "missed": [str(m) for m, f in zip(months, flags, strict=True) if not f],
            "stress_months": len(stress_months), "stress_months_paid": sum(1 for m in stress_months if m in paid),
            "stress_threshold": stress_drawdown}


def pea_status(transactions: pd.DataFrame | None, opening_date: str | None, *, ceiling: float = PEA_CEILING_EUR,
               today: str | pd.Timestamp | None = None, envelope: str = "pea") -> dict:
    """Ancienneté, jalon des 5 ans, versements cumulés et capacité restante."""
    today_ts = pd.Timestamp(today) if today is not None else pd.Timestamp(date.today())
    contributions = 0.0
    if transactions is not None:
        pea = transactions[transactions["enveloppe"] == envelope]
        contributions = float(pea.loc[pea["type"] == "VERSEMENT", "montant"].sum())
    status: dict = {"ceiling": ceiling, "contributions": contributions,
                    "remaining_capacity": max(ceiling - contributions, 0.0),
                    "ceiling_used": contributions / ceiling if ceiling else None, "alerts": []}
    if opening_date:
        opening = pd.Timestamp(opening_date)
        milestone = opening + pd.DateOffset(years=PEA_YEARS)
        status.update(opening_date=opening.date().isoformat(), five_year_date=milestone.date().isoformat(),
                      years_held=round((today_ts - opening).days / 365.25, 2), five_years_reached=today_ts >= milestone)
        if not status["five_years_reached"]:
            status["alerts"].append(f"PEA de moins de 5 ans (jalon le {milestone.date()}) : tout retrait avant cette "
                                    "date clôture le plan et le gain supporte la flat tax.")
    else:
        status["alerts"].append("Date d'ouverture du PEA non renseignée (patrimoine.yaml > pea > date_ouverture).")
    if contributions >= 0.9 * ceiling:
        status["alerts"].append(f"Versements cumulés {contributions:,.0f} € : plus de 90 % du plafond de "
                                f"{ceiling:,.0f} €.")
    return status


# --------------------------------------------------------------------------- #
# Ordres proposés (jamais comptés comme exécutés)
# --------------------------------------------------------------------------- #
PENDING_COLUMNS = ["date_proposition", "enveloppe", "type", "ticker", "parts", "prix_indicatif", "montant_indicatif",
                   "frais_estimes", "statut", "commentaire"]


def record_pending_orders(plan_table: pd.DataFrame, path: str | Path, *, envelope: str = "pea",
                          when: str | None = None) -> int:
    """Ajoute les achats **proposés** à ``pending_orders.csv`` (statut PROPOSE)."""
    buys = plan_table[plan_table["parts_a_acheter"] > 0] if not plan_table.empty else plan_table
    if buys.empty:
        return 0
    when = when or date.today().isoformat()
    rows = pd.DataFrame([{
        "date_proposition": when, "enveloppe": envelope, "type": "ACHAT", "ticker": ticker,
        "parts": int(row["parts_a_acheter"]), "prix_indicatif": round(float(row["prix"]), 4),
        "montant_indicatif": round(float(row["montant"]), 2), "frais_estimes": round(float(row["frais"]), 2),
        "statut": "PROPOSE",
        "commentaire": "Proposition du planificateur : reporter dans transactions.csv seulement après exécution réelle",
    } for ticker, row in buys.iterrows()], columns=PENDING_COLUMNS)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(path, mode="a", header=not path.exists(), index=False)
    return len(rows)


def generate_portfolio_report(perf: dict | None, pea: dict, output_path: str | Path, *, notes: list[str] | None = None,
                              benchmark: str = "CW8.PA") -> Path:
    """Rapport personnel (non versionné)."""
    pct = lambda v: "n/a" if v is None else f"{v:+.2%}"  # noqa: E731
    eur = lambda v: "n/a" if v is None else f"{v:,.2f} €".replace(",", " ")  # noqa: E731
    lines = ["# Portefeuille réel (données personnelles, non versionnées)", "",
             f"Date de génération : {date.today().isoformat()} — aucun ordre n'est exécuté par le laboratoire.", ""]
    if perf is None:
        lines += ["Aucun journal de transactions : copier `config/transactions.example.csv` en "
                  "`config/transactions.csv`.", ""]
    else:
        comparison = perf["comparison"]
        lines += [
            f"## Performance ({perf['start']} → {perf['end']})", "",
            f"- Valeur actuelle : **{eur(perf['final_value'])}** pour {eur(perf['net_contributions'])} versés nets "
            f"(gain {eur(perf['gain'])}).",
            f"- Rendement pondéré par le temps (TWR, performance de la gestion) : {pct(comparison.get('real_twr'))}.",
            f"- Rendement pondéré par les capitaux (TRI annualisé, ton expérience réelle) : {pct(perf['mwr'])}.",
            f"- Frais payés : {eur(perf['fees_total'])}"
            + ("" if perf["fees_pct_of_contributions"] is None else f" ({perf['fees_pct_of_contributions']:.2%} des versements)."),
            f"- Buy & Hold {benchmark} avec les mêmes versements : {eur(perf['benchmark_same_flows_value'])} "
            f"(TWR {pct(comparison.get('benchmark_twr'))}).",
        ]
        if "common_months" in comparison:
            lines += [f"- Sur les {comparison['common_months']} mois communs avec le paper trading : réel "
                      f"{pct(comparison['real_twr_common'])}, mes décisions paper {pct(comparison['paper_twr_common'])}, "
                      f"proposition du système {pct(comparison['system_twr_common'])}."]
        lines += ["", "| Mois | Valeur | Flux | Frais | Rendement du mois (TWR) |", "| --- | ---: | ---: | ---: | ---: |"]
        twr = perf["twr_monthly"]
        for month, row in perf["valuation"].iterrows():
            lines.append(f"| {month:%Y-%m} | {eur(row['valeur'])} | {eur(row['flux'])} | {eur(row['frais'])} | "
                         f"{pct(twr.get(month))} |")
    lines += ["", "## PEA", "",
              f"- Versements cumulés : {eur(pea['contributions'])} / plafond {eur(pea['ceiling'])} "
              f"(capacité restante {eur(pea['remaining_capacity'])}).",
              f"- Ouverture : {pea.get('opening_date', 'non renseignée')} ; jalon des 5 ans : "
              f"{pea.get('five_year_date', 'n/a')} ; ancienneté : {pea.get('years_held', 'n/a')} ans."]
    lines += [f"- **Alerte** : {alert}" for alert in pea["alerts"]]
    if notes:
        lines += ["", "## Remarques", ""] + [f"- {note}" for note in notes]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path

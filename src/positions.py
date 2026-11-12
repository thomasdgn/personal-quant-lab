"""Positions réelles (nombre de parts) et valorisation aux derniers prix locaux.

Fichier personnel ``config/positions.yaml`` (ignoré par Git), modèle
``config/positions.example.yaml`` ::

    date: 2026-09-23
    lignes:
      - {enveloppe: pea, ticker: CW8.PA, parts: 3}
    liquidites_eur:
      pea: 120.50

Lecture seule : aucune opération n'est passée.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml


def load_positions(path: str | Path) -> dict | None:
    """Charge et valide les positions ; ``None`` si le fichier est absent."""
    path = Path(path)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} doit être un dictionnaire YAML.")
    lines = raw.get("lignes") or []
    cash = raw.get("liquidites_eur") or {}
    if not isinstance(lines, list) or not isinstance(cash, dict):
        raise ValueError(f"{path.name} : 'lignes' doit être une liste et 'liquidites_eur' un dictionnaire.")
    clean, seen = [], set()
    for index, line in enumerate(lines):
        if not isinstance(line, dict) or not {"enveloppe", "ticker", "parts"} <= set(line):
            raise ValueError(f"{path.name} : lignes[{index}] doit contenir enveloppe, ticker et parts.")
        parts = line["parts"]
        if isinstance(parts, bool) or not isinstance(parts, (int, float)) or parts < 0:
            raise ValueError(f"{path.name} : parts invalides pour {line['ticker']} (nombre positif attendu).")
        key = (str(line["enveloppe"]), str(line["ticker"]))
        if key in seen:
            raise ValueError(f"{path.name} : ligne dupliquée {key[1]} dans {key[0]}.")
        seen.add(key)
        clean.append({"enveloppe": key[0], "ticker": key[1], "parts": float(parts)})
    for envelope, amount in cash.items():
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0:
            raise ValueError(f"{path.name} : liquidités invalides pour {envelope}.")
    return {"date": str(raw["date"]) if raw.get("date") is not None else None, "lignes": clean,
            "liquidites_eur": {str(k): float(v) for k, v in cash.items()}}


def last_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Dernier prix disponible et sa date, par ticker."""
    rows = []
    for ticker in prices.columns:
        series = prices[ticker].dropna()
        if not series.empty:
            rows.append({"ticker": ticker, "prix": float(series.iloc[-1]), "date_prix": series.index[-1].date()})
    return pd.DataFrame(rows).set_index("ticker")


def value_positions(positions: dict, prices: pd.DataFrame) -> dict:
    """Valorise chaque ligne ; renvoie lignes, totaux par enveloppe et poids.

    Raises
    ------
    ValueError
        Si une ligne détenue (parts > 0) n'a aucun prix local.
    """
    quotes = last_prices(prices)
    held = [line for line in positions["lignes"] if line["parts"] > 0]
    missing = sorted({line["ticker"] for line in held if line["ticker"] not in quotes.index})
    if missing:
        raise ValueError(f"Pas de prix local pour {', '.join(missing)} : lance `python main.py refresh-data` "
                         "ou ajoute le ticker à config/assets.yaml.")
    rows = []
    for line in held:
        quote = quotes.loc[line["ticker"]]
        rows.append({**line, "prix": quote["prix"], "date_prix": quote["date_prix"],
                     "valeur": line["parts"] * quote["prix"]})
    table = pd.DataFrame(rows, columns=["enveloppe", "ticker", "parts", "prix", "date_prix", "valeur"])
    envelopes = sorted(set(table["enveloppe"]) | set(positions["liquidites_eur"]))
    totals = {}
    for envelope in envelopes:
        invested = float(table.loc[table["enveloppe"] == envelope, "valeur"].sum())
        cash = positions["liquidites_eur"].get(envelope, 0.0)
        totals[envelope] = {"titres": invested, "liquidites": cash, "total": invested + cash}
    return {"lignes": table, "enveloppes": totals}


def envelope_weights(valuation: dict, envelope: str, cash_col: str = "CASH") -> dict[str, float]:
    """Poids actuels d'une enveloppe (titres + liquidités = 100 %)."""
    total = valuation["enveloppes"].get(envelope, {}).get("total", 0.0)
    if total <= 0:
        return {}
    lines = valuation["lignes"][valuation["lignes"]["enveloppe"] == envelope]
    weights = {row["ticker"]: row["valeur"] / total for _, row in lines.iterrows()}
    weights[cash_col] = valuation["enveloppes"][envelope]["liquidites"] / total
    return weights

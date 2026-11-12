"""Observations économiques avec date de disponibilité et version explicites."""
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["series_id", "observation_date", "release_at", "acquired_at", "value", "source", "vintage"]


def load_observations(path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    data = pd.read_csv(path)
    if not set(COLUMNS).issubset(data):
        raise ValueError("Schéma macro incomplet : " + ", ".join(COLUMNS))
    for name in ("release_at", "acquired_at"):
        data[name] = pd.to_datetime(data[name], utc=True, errors="raise")
    data["observation_date"] = pd.to_datetime(data["observation_date"], errors="raise")
    if data[["release_at", "acquired_at", "observation_date"]].isna().any().any():
        raise ValueError("Dates macro complètes requises.")
    data["value"] = pd.to_numeric(data["value"], errors="raise")
    if not np.isfinite(data["value"]).all() or data[["source", "series_id", "vintage"]].isna().any().any():
        raise ValueError("Valeurs macro finies, sources et versions requises.")
    if (data["acquired_at"] < data["release_at"]).any():
        raise ValueError("Une acquisition ne peut pas précéder la publication.")
    if data.duplicated(["series_id", "observation_date", "release_at"]).any():
        raise ValueError("Version macro dupliquée.")
    return data.sort_values(["release_at", "acquired_at"])


def available_observations(data: pd.DataFrame, as_of, *, mode="prospective") -> pd.DataFrame:
    if mode not in ("prospective", "vintage_research"):
        raise ValueError("Mode macro inconnu.")
    if data.empty:
        return data.copy()
    now = pd.Timestamp(as_of)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    known = data[data["release_at"] <= now]
    # Prospective : on ne peut utiliser une valeur avant sa collecte locale.
    # Recherche : la date de publication du millésime archivé fait foi.
    if mode == "prospective":
        known = known[known["acquired_at"] <= now]
    return known.drop_duplicates(["series_id", "observation_date"], keep="last")


def macro_context(data, as_of, *, mode="prospective") -> dict:
    known = available_observations(data, as_of, mode=mode)
    items = []
    for series, rows in known.groupby("series_id"):
        rows = rows.sort_values("observation_date")
        current = rows.iloc[-1]
        items.append({"series_id": series, "value": float(current["value"]),
                      "observation_date": str(current["observation_date"].date()),
                      "release_at": current["release_at"].isoformat(), "source": current["source"],
                      "vintage": str(current["vintage"]),
                      "change": None if len(rows) < 2 else float(current["value"] - rows.iloc[-2]["value"])})
    return {"as_of": str(as_of), "mode": mode, "observations": items,
            "status": "context_only" if items else "no_real_data",
            "note": "Aucun filtre macro validé pour les décisions d'investissement."}


def macro_risk_filter(data, dates, series_id, threshold, *, mode="vintage_research") -> pd.Series:
    """Hypothèse de recherche préenregistrée : valeur <= seuil ; absence => pas d'overlay."""
    result = {}
    for day in dates:
        context = macro_context(data, day, mode=mode)
        row = next((r for r in context["observations"] if r["series_id"] == series_id), None)
        result[day] = np.nan if row is None else float(row["value"] <= threshold)
    return pd.Series(result, name="macro_exposure")

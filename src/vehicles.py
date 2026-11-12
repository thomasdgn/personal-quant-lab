"""Expositions économiques et véhicules achetables (ETF qui les répliquent).

Une **exposition** (ex. ``msci_world``) peut être implémentée par plusieurs
tickers (CW8.PA, WPEA.PA). Ce module :

- regroupe les tickers par exposition et ordre de préférence
  (``vehicle_priority``) ;
- choisit le véhicule préféré **abordable** pour un budget donné ;
- convertit une allocation cible par ticker en allocation par véhicule pour le
  plan de versement, sans compter deux fois une exposition déjà détenue via un
  autre véhicule ;
- prolonge un historique court par un **proxy** de même exposition (données
  synthétiques, toujours signalées) et mesure l'écart de suivi sur la période
  commune.

Aucun ordre n'est passé : il ne s'agit que de propositions et de mesures.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CASH = "CASH"


def exposure_map(assets: list[dict]) -> dict[str, str]:
    """``{ticker: exposition}`` (par défaut, un ticker est sa propre exposition)."""
    return {a["ticker"]: a.get("exposure") or a["ticker"] for a in assets}


def vehicles_by_exposure(assets: list[dict]) -> dict[str, list[str]]:
    """``{exposition: [tickers du plus préféré au moins préféré]}``."""
    groups: dict[str, list[tuple[int, int, str]]] = {}
    for position, asset in enumerate(assets):
        exposure = asset.get("exposure") or asset["ticker"]
        groups.setdefault(exposure, []).append((asset.get("vehicle_priority", 1), position, asset["ticker"]))
    return {exposure: [t for _, _, t in sorted(items)] for exposure, items in groups.items()}


def choose_vehicle(exposure: str, vehicles: dict[str, list[str]], quotes: dict[str, float],
                   budget: float) -> tuple[str | None, str | None]:
    """Véhicule préféré dont **une part** tient dans le budget ; sinon le préféré coté.

    Returns
    -------
    (ticker, note)
        ``note`` explique une bascule vers un véhicule moins préféré.
    """
    candidates = [t for t in vehicles.get(exposure, [exposure]) if quotes.get(t)]
    if not candidates:
        return None, None
    preferred = candidates[0]
    for ticker in candidates:
        if quotes[ticker] <= budget:
            if ticker != preferred:
                return ticker, (f"{exposure} : une part de {preferred} ({quotes[preferred]:,.2f} €) dépasse le budget "
                                f"({budget:,.2f} €) ; achat proposé via {ticker} ({quotes[ticker]:,.2f} €), même exposition.")
            return ticker, None
    return preferred, None


def map_target_to_vehicles(target_weights: dict[str, float], holdings_value: dict[str, float],
                           quotes: dict[str, float], assets: list[dict], budget: float) -> tuple[dict[str, float], list[str]]:
    """Allocation cible par ticker -> par véhicule achetable.

    Pour chaque exposition visée : le poids cible total est porté par le
    véhicule choisi (``choose_vehicle``), **diminué** de la valeur déjà détenue
    dans les autres véhicules de la même exposition (ils gardent leur poids
    actuel : pas de vente, pas de double comptage).
    """
    exposures = exposure_map(assets)
    vehicles = vehicles_by_exposure(assets)
    total_after = sum(holdings_value.values()) + budget
    notes: list[str] = []
    per_exposure: dict[str, float] = {}
    for ticker, weight in target_weights.items():
        if ticker == CASH or not weight:
            continue
        per_exposure[exposures.get(ticker, ticker)] = per_exposure.get(exposures.get(ticker, ticker), 0.0) + weight
    mapped: dict[str, float] = {}
    for exposure, weight in per_exposure.items():
        vehicle, note = choose_vehicle(exposure, vehicles, quotes, budget)
        if vehicle is None:
            # Aucun prix : on garde le ticker d'origine (le planificateur signalera le prix manquant).
            vehicle = next(t for t, w in target_weights.items() if w and exposures.get(t, t) == exposure)
        if note:
            notes.append(note)
        others = [t for t in vehicles.get(exposure, []) if t != vehicle and holdings_value.get(t, 0.0) > 0]
        held_elsewhere = sum(holdings_value[t] / total_after for t in others) if total_after else 0.0
        for other in others:
            mapped[other] = holdings_value[other] / total_after
        mapped[vehicle] = max(weight - held_elsewhere, 0.0)
        if others:
            notes.append(f"{exposure} : {', '.join(others)} déjà détenu(s) comptent dans l'exposition (pas de vente).")
    invested = sum(mapped.values())
    mapped[CASH] = max(1.0 - invested, 0.0)
    scale = sum(mapped.values())
    return {k: v / scale for k, v in mapped.items() if v > 0 or k == CASH}, notes


# --------------------------------------------------------------------------- #
# Historiques prolongés par proxy (données synthétiques)
# --------------------------------------------------------------------------- #
def splice_history(vehicle: pd.Series, proxy: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Prolonge ``vehicle`` avant sa première cotation avec les **rendements** du proxy.

    Les prix synthétiques sont chaînés pour se raccorder exactement au premier
    prix réel. Returns ``(prix prolongés, masque synthétique)``.
    """
    real = vehicle.dropna()
    if real.empty:
        raise ValueError("Le véhicule n'a aucun prix réel.")
    first = real.index[0]
    before = proxy.loc[proxy.index < first].dropna()
    anchor = proxy.loc[:first].dropna()
    if before.empty or anchor.empty:
        return real, pd.Series(False, index=real.index)
    # Prix synthétique = prix réel initial × (proxy(t) / proxy au raccord).
    synthetic = real.iloc[0] * before / anchor.iloc[-1]
    spliced = pd.concat([synthetic, real]).sort_index()
    flag = pd.Series(spliced.index < first, index=spliced.index)
    return spliced, flag


def tracking_stats(vehicle: pd.Series, proxy: pd.Series, periods_per_year: int = 252) -> dict:
    """Écart de suivi sur la période commune (rendements simultanés)."""
    joined = pd.concat([vehicle, proxy], axis=1, join="inner").dropna()
    if len(joined) < 20:
        return {"n_obs": int(len(joined)), "tracking_difference": None, "tracking_error": None, "correlation": None}
    returns = joined.pct_change().dropna()
    diff = returns.iloc[:, 0] - returns.iloc[:, 1]
    return {
        "start": joined.index[0].date().isoformat(), "end": joined.index[-1].date().isoformat(),
        "n_obs": int(len(returns)),
        "tracking_difference": float(diff.mean() * periods_per_year),
        "tracking_error": float(diff.std() * np.sqrt(periods_per_year)),
        "correlation": float(returns.iloc[:, 0].corr(returns.iloc[:, 1])),
    }

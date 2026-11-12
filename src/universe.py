"""Chargement et validation de l'univers ETF PEA via yfinance.

Ce module documente la disponibilité et la profondeur d'historique des actifs.
Il ne calcule aucun signal et ne déclenche aucune opération de marché.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import yaml
import yfinance as yf

HISTORY_THRESHOLD = pd.Timestamp("2022-01-01")
REQUIRED_ASSET_FIELDS = ("ticker", "name", "category", "universe_active", "notes")

# Rôle d'un actif dans les stratégies (champ optionnel ``role`` d'assets.yaml) :
# - candidate  : classé par le Momentum (actions) ;
# - defensive  : obligataire, classé seulement si la configuration l'autorise ;
# - cash_proxy : monétaire, jamais classé ; son rendement rémunère la poche cash.
ASSET_ROLES = ("candidate", "defensive", "cash_proxy")
DEFAULT_ROLE = "candidate"

logger = logging.getLogger(__name__)


def load_universe(
    config_path: str | Path, *, include_inactive: bool = False
) -> list[dict]:
    """Charge l'univers structuré et renvoie ses actifs actifs par défaut.

    ``include_inactive=True`` est destiné aux audits complets : les actifs
    documentés mais désactivés restent alors visibles dans le rapport.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Fichier d'univers introuvable : {path}")

    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    if not isinstance(config, dict) or not isinstance(config.get("universe"), list):
        raise ValueError("assets.yaml doit contenir une liste structurée 'universe'.")

    assets: list[dict] = []
    seen: set[str] = set()
    for position, raw_asset in enumerate(config["universe"]):
        if not isinstance(raw_asset, dict):
            raise ValueError(f"L'actif universe[{position}] doit être un dictionnaire.")

        missing = [field for field in REQUIRED_ASSET_FIELDS if field not in raw_asset]
        if missing:
            raise ValueError(
                f"Champs manquants pour universe[{position}] : {', '.join(missing)}."
            )

        asset = {field: raw_asset[field] for field in REQUIRED_ASSET_FIELDS}
        ticker = asset["ticker"]
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError(f"Ticker invalide pour universe[{position}].")
        ticker = ticker.strip()
        if ticker in seen:
            raise ValueError(f"Ticker dupliqué dans l'univers : {ticker}.")
        if not isinstance(asset["universe_active"], bool):
            raise ValueError(f"universe_active doit être booléen pour {ticker}.")
        for field in ("name", "category", "notes"):
            if not isinstance(asset[field], str):
                raise ValueError(f"Le champ '{field}' doit être une chaîne pour {ticker}.")

        role = raw_asset.get("role", DEFAULT_ROLE)
        if role not in ASSET_ROLES:
            raise ValueError(
                f"Rôle invalide pour {ticker} : {role!r} (attendu : {', '.join(ASSET_ROLES)})."
            )

        exposure = raw_asset.get("exposure", ticker)
        if not isinstance(exposure, str) or not exposure.strip():
            raise ValueError(f"exposure doit être un texte non vide pour {ticker}.")
        priority = raw_asset.get("vehicle_priority", 1)
        if isinstance(priority, bool) or not isinstance(priority, int) or priority < 1:
            raise ValueError(f"vehicle_priority doit être un entier >= 1 pour {ticker}.")
        proxy = raw_asset.get("proxy")
        if proxy is not None and (not isinstance(proxy, str) or proxy.strip() == ticker):
            raise ValueError(f"proxy invalide pour {ticker} (autre ticker attendu).")

        fiche = raw_asset.get("fiche")
        if fiche is not None:
            fiche = validate_fiche(fiche, ticker)

        seen.add(ticker)
        asset["fiche"] = fiche
        asset["ticker"] = ticker
        asset["role"] = role
        asset["exposure"] = exposure.strip()
        asset["vehicle_priority"] = priority
        asset["proxy"] = proxy.strip() if proxy else None
        if include_inactive or asset["universe_active"]:
            assets.append(asset)

    return assets


FICHE_FIELDS = ("isin", "nom_officiel", "indice", "ter_pct", "pea", "replication", "verifie_le", "source", "alertes")


def isin_is_valid(isin: str) -> bool:
    """Format (2 lettres pays + 9 alphanumériques + chiffre de contrôle) et clé de Luhn."""
    if not isinstance(isin, str) or len(isin) != 12 or not isin[:2].isalpha() or not isin[:2].isupper()             or not isin[2:11].isalnum() or not isin[11].isdigit():
        return False
    digits = "".join(str(int(c, 36)) for c in isin[:11].upper())
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:  # en partant de la droite, hors chiffre de contrôle : doubler une position sur deux
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return (10 - total % 10) % 10 == int(isin[11])


def validate_fiche(fiche: object, ticker: str) -> dict:
    """Fiche produit vérifiée (``fiche`` dans assets.yaml) : erreurs explicites."""
    if not isinstance(fiche, dict):
        raise ValueError(f"fiche doit être un dictionnaire pour {ticker}.")
    unknown = set(fiche) - set(FICHE_FIELDS)
    if unknown:
        raise ValueError(f"fiche de {ticker} : clés inconnues {', '.join(sorted(unknown))}.")
    isin = fiche.get("isin")
    if not isin_is_valid(isin):  # type: ignore[arg-type]
        raise ValueError(f"fiche de {ticker} : ISIN invalide {isin!r} (format ou clé de contrôle).")
    ter = fiche.get("ter_pct")
    if ter is not None and (isinstance(ter, bool) or not isinstance(ter, (int, float)) or not 0 <= ter <= 3):
        raise ValueError(f"fiche de {ticker} : ter_pct doit être un pourcentage entre 0 et 3.")
    if fiche.get("pea") not in (True, False, None):
        raise ValueError(f"fiche de {ticker} : pea doit valoir true, false ou null (non confirmé).")
    for key in ("nom_officiel", "indice", "replication", "source"):
        if key in fiche and not isinstance(fiche[key], str):
            raise ValueError(f"fiche de {ticker} : {key} doit être un texte.")
    checked = fiche.get("verifie_le")
    try:
        pd.Timestamp(str(checked))
    except ValueError as exc:
        raise ValueError(f"fiche de {ticker} : verifie_le doit être une date AAAA-MM-JJ.") from exc
    alerts = fiche.get("alertes") or []
    if not isinstance(alerts, list) or not all(isinstance(a, str) for a in alerts):
        raise ValueError(f"fiche de {ticker} : alertes doit être une liste de textes.")
    return {**fiche, "alertes": list(alerts), "verifie_le": str(checked)}


def fiche_warnings(assets: list[dict]) -> list[str]:
    """Points à vérifier : fiche absente, PEA non confirmé, alertes de la fiche."""
    warnings = []
    for asset in assets:
        fiche = asset.get("fiche")
        if fiche is None:
            warnings.append(f"{asset['ticker']} : aucune fiche produit vérifiée (ISIN inconnu).")
            continue
        if fiche.get("pea") is None:
            warnings.append(f"{asset['ticker']} : éligibilité PEA non confirmée.")
        elif fiche.get("pea") is False:
            warnings.append(f"{asset['ticker']} : non éligible au PEA.")
        warnings += [f"{asset['ticker']} : {alert}" for alert in fiche.get("alertes", [])]
    return warnings


def asset_roles(assets: list[dict]) -> dict[str, str]:
    """Associe chaque ticker à son rôle (ordre de configuration conservé)."""
    return {asset["ticker"]: asset.get("role", DEFAULT_ROLE) for asset in assets}


def _history_months(first_date: pd.Timestamp, last_date: pd.Timestamp) -> int:
    """Compte les mois calendaires couverts, bornes incluses."""
    return (last_date.year - first_date.year) * 12 + last_date.month - first_date.month + 1


def _unavailable_result(asset: dict, reason: str) -> dict:
    notes = asset.get("notes", "")
    detail = f"Données indisponibles via yfinance : {reason}"
    if detail not in notes:
        notes = f"{notes} {detail}".strip()
    return {
        "ticker": asset.get("ticker"),
        "name": asset.get("name", ""),
        "category": asset.get("category", ""),
        "universe_active": False,
        "first_date": None,
        "last_date": None,
        "history_months": None,
        "flags": ["UNAVAILABLE"],
        "notes": notes,
    }


def validate_universe(
    assets: list[dict], start_date: str, end_date: str
) -> list[dict]:
    """Valide chaque actif via yfinance sans interrompre l'audit sur erreur."""
    results: list[dict] = []
    for asset in assets:
        ticker = asset.get("ticker")
        try:
            history = yf.download(
                tickers=ticker,
                start=start_date,
                end=end_date,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if not isinstance(history, pd.DataFrame) or history.empty:
                logger.warning("Historique yfinance vide pour %s", ticker)
                results.append(_unavailable_result(asset, "historique vide"))
                continue

            valid_history = history.dropna(how="all")
            if valid_history.empty:
                logger.warning("Historique yfinance sans valeur pour %s", ticker)
                results.append(_unavailable_result(asset, "historique sans valeur"))
                continue

            dates = pd.to_datetime(valid_history.index, errors="coerce").dropna()
            if dates.empty:
                logger.warning("Dates yfinance invalides pour %s", ticker)
                results.append(_unavailable_result(asset, "dates invalides"))
                continue

            first_date = pd.Timestamp(dates.min())
            last_date = pd.Timestamp(dates.max())
            if first_date.tzinfo is not None:
                first_date = first_date.tz_localize(None)
            if last_date.tzinfo is not None:
                last_date = last_date.tz_localize(None)

            flags = ["SHORT_HISTORY"] if first_date > HISTORY_THRESHOLD else []
            results.append(
                {
                    "ticker": ticker,
                    "name": asset.get("name", ""),
                    "category": asset.get("category", ""),
                    "universe_active": True,
                    "first_date": first_date.date().isoformat(),
                    "last_date": last_date.date().isoformat(),
                    "history_months": _history_months(first_date, last_date),
                    "flags": flags,
                    "notes": asset.get("notes", ""),
                }
            )
        except Exception as exc:  # yfinance peut lever des erreurs réseau variées
            logger.warning("Validation yfinance impossible pour %s : %s", ticker, exc)
            results.append(_unavailable_result(asset, f"{type(exc).__name__}: {exc}"))

    return results


def _markdown_cell(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def generate_validation_report(
    validation_results: list[dict], output_path: str | Path
) -> None:
    """Écrit un rapport Markdown stable et rejouable."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Validation de l'univers ETF PEA",
        "",
        "Validation technique des historiques Yahoo Finance. Paper trading uniquement ; aucun ordre réel.",
        "",
        "| Ticker | Nom | Catégorie | Première date | Dernière date | Mois d'historique | Actif | Flags | Notes |",
        "|---|---|---|---:|---:|---:|:---:|---|---|",
    ]
    for result in validation_results:
        flags = ", ".join(result.get("flags", [])) or "—"
        active = "true" if result.get("universe_active") else "false"
        values = (
            result.get("ticker"),
            result.get("name"),
            result.get("category"),
            result.get("first_date"),
            result.get("last_date"),
            result.get("history_months"),
            active,
            flags,
            result.get("notes"),
        )
        lines.append("| " + " | ".join(_markdown_cell(value) for value in values) + " |")

    lines.extend(
        [
            "",
            "Seuil d'historique suffisant : première date au plus tard le 2022-01-01.",
            "Les actifs `UNAVAILABLE` restent documentés mais sont exclus de l'univers actif.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")

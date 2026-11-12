"""Notifications push via ntfy (Projet 9) — **désactivées par défaut**.

Configuration personnelle ``config/notify.yaml`` (ignorée par Git), modèle
``config/notify.example.yaml`` ::

    enabled: false               # rien n'est jamais envoyé tant que false
    server: https://ntfy.sh
    topic: ""                    # sujet secret et difficile à deviner
    min_level: INFO              # INFO, WARNING ou CRITICAL

Événements (discrets, jamais de micro-variation) :

- INFO     : rapport mensuel disponible ;
- WARNING  : changement d'actif sélectionné, passage en cash total ;
- CRITICAL : statut CRITICAL du rapport, échec du téléchargement des données.

Chaque événement (envoyé, filtré, désactivé ou en erreur) est tracé dans
``logs/notifications.jsonl``. Une notification n'est **jamais** un ordre.
"""

from __future__ import annotations

import json
import hashlib
import sqlite3
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

LEVELS = ("INFO", "WARNING", "CRITICAL")
_PRIORITY = {"INFO": "3", "WARNING": "4", "CRITICAL": "5"}
_TAGS = {"INFO": "information_source", "WARNING": "warning", "CRITICAL": "rotating_light"}

HttpPost = Callable[[str, bytes, dict[str, str], float], int]


@dataclass(frozen=True)
class NotifyConfig:
    enabled: bool = False
    server: str = "https://ntfy.sh"
    topic: str = ""
    min_level: str = "INFO"
    timeout: float = 10.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("notify.enabled doit être true ou false.")
        if self.min_level not in LEVELS:
            raise ValueError(f"notify.min_level doit être parmi {', '.join(LEVELS)}.")
        if self.enabled and not self.topic.strip():
            raise ValueError("notify.topic est obligatoire quand enabled vaut true.")
        if not self.server.startswith("https://"):
            raise ValueError("notify.server doit être une URL https://.")

    @property
    def url(self) -> str:
        return f"{self.server.rstrip('/')}/{self.topic.strip()}"


def load_notify_config(path: str | Path) -> NotifyConfig:
    """Fichier absent => notifications désactivées."""
    path = Path(path)
    if not path.exists():
        return NotifyConfig()
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} doit être un dictionnaire YAML.")
    unknown = set(raw) - {"enabled", "server", "topic", "min_level", "timeout"}
    if unknown:
        raise ValueError(f"{path.name} : clés inconnues {', '.join(sorted(unknown))}.")
    return NotifyConfig(**{k: v for k, v in raw.items() if v is not None})


def _event(level: str, code: str, title: str, message: str) -> dict:
    return {"level": level, "code": code, "title": title, "message": message}


def build_events(snapshot: dict | None, previous: dict | None = None, *, failure: str | None = None) -> list[dict]:
    """Événements à notifier pour un rapport (ou un échec de préparation)."""
    if failure:
        return [_event("CRITICAL", "RUN_FAILED", "Quant lab : échec de la routine",
                       f"La routine mensuelle a échoué : {failure}")]
    if not snapshot:
        return []
    meta = snapshot.get("metadata", {})
    month = meta.get("report_month")
    momentum = snapshot.get("momentum_strategy") or {}
    vt = snapshot.get("volatility_targeted_strategy") or {}
    main_strategy = vt if vt.get("enabled", True) and vt.get("target_weights") else momentum
    followed = (snapshot.get("policy") or {}).get("followed")
    if followed and (snapshot.get("strategies") or {}).get(followed):
        main_strategy = snapshot["strategies"][followed]
    selected_assets = main_strategy.get("selected_assets") if followed else momentum.get("selected_assets")
    if selected_assets is None:
        selected_assets = [t for t, w in (main_strategy.get("target_weights") or {}).items() if t != "CASH" and w > 0]
    selected = ", ".join(sorted(selected_assets)) or "cash"
    label = followed or "Momentum"
    exposure = main_strategy.get("invested_exposure")
    events = [_event("INFO", "REPORT_READY", f"Quant lab : rapport {month} disponible",
                     f"Signal {meta.get('signal_date')} - {label} : {selected} - exposition proposée "
                     f"{'n/a' if exposure is None else f'{exposure:.0%}'}. Décision manuelle à renseigner.")]
    if previous:
        previous_main = ((previous.get("strategies") or {}).get(followed) or {}) if followed else previous.get("momentum_strategy") or {}
        previous_selected = previous_main.get("selected_assets")
        if previous_selected is None and followed and previous_main.get("target_weights"):
            previous_selected = [t for t, w in previous_main["target_weights"].items() if t != "CASH" and w > 0]
        if previous_selected is not None and set(previous_selected) != set(selected_assets):
            before = ", ".join(previous_selected) or "cash"
            events.append(_event("WARNING", "SELECTION_CHANGED", "Quant lab : changement d'actif",
                                 f"Actif {label} : {before} -> {selected} ({month})."))
        if followed and previous_main.get("target_weights"):
            before_weights = previous_main["target_weights"]
            after_weights = main_strategy.get("target_weights") or {}
            gap = max((abs(after_weights.get(t, 0) - before_weights.get(t, 0))
                       for t in set(before_weights) | set(after_weights)), default=0)
            if gap >= .05:
                events.append(_event("WARNING", "ALLOCATION_CHANGED", "Quant lab : allocation modifiée",
                                     f"{followed} : variation maximale des poids {gap:.0%}. Relire le rapport {month}."))
    cash = main_strategy.get("cash_weight")
    if cash is not None and cash >= 0.999:
        events.append(_event("WARNING", "FULL_CASH", "Quant lab : passage en cash total",
                             f"L'allocation proposée pour {month} est entièrement en cash."))
    if meta.get("pipeline_status") == "CRITICAL":
        codes = [a.get("code") for a in snapshot.get("alerts", []) if a.get("level") == "CRITICAL"]
        events.append(_event("CRITICAL", "REPORT_CRITICAL", f"Quant lab : rapport {month} CRITICAL",
                             f"Validation humaine requise ({', '.join(codes) or 'voir le rapport'})."))
    return events


def _urllib_post(url: str, data: bytes, headers: dict[str, str], timeout: float) -> int:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL https validée
        return int(response.status)


def send_events(events: list[dict], config: NotifyConfig, *, log_path: str | Path,
                http_post: HttpPost | None = None, now: datetime | None = None, dry_run: bool = False) -> list[dict]:
    """Envoie les événements si activé et au-dessus du niveau minimal ; trace tout.

    Returns
    -------
    list[dict]
        Un résultat par événement : ``status`` ∈ ``sent``, ``disabled``,
        ``filtered``, ``error``.
    """
    http_post = http_post or _urllib_post
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now()).isoformat(timespec="seconds")
    results = []
    for event in events:
        moment = now or datetime.now(timezone.utc)
        moment = moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment
        expiry = datetime.fromisoformat(event["expires_at"]) if event.get("expires_at") else None
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if not config.enabled:
            status, detail = "disabled", "notifications désactivées"
        elif expiry is not None and moment >= expiry:
            status, detail = "expired", "événement expiré ; recalcul requis"
        elif dry_run:
            status, detail = "dry_run", "simulation sans envoi"
        elif LEVELS.index(event["level"]) < LEVELS.index(config.min_level):
            status, detail = "filtered", f"niveau inférieur à {config.min_level}"
        else:
            headers = {"Title": event["title"].encode("ascii", "ignore").decode() or "Quant lab",
                       "Priority": _PRIORITY[event["level"]], "Tags": _TAGS[event["level"]]}
            event_id = event.get("id") or hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
            # Verrou transactionnel pendant l'envoi : deux routines concurrentes
            # ne transmettent pas le même événement. Les erreurs restent réessayables.
            with sqlite3.connect(log_path.with_suffix(".sqlite3"), timeout=30) as db:
                db.execute("CREATE TABLE IF NOT EXISTS deliveries (id TEXT, destination TEXT, PRIMARY KEY(id, destination))")
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT 1 FROM deliveries WHERE id=? AND destination=?", (event_id, config.url)).fetchone():
                    status, detail = "duplicate", "événement déjà envoyé"
                else:
                    try:
                        code = http_post(config.url, event["message"].encode("utf-8"), headers, config.timeout)
                        status, detail = ("sent", f"HTTP {code}") if 200 <= code < 300 else ("error", f"HTTP {code}")
                        if status == "sent":
                            db.execute("INSERT INTO deliveries VALUES (?, ?)", (event_id, config.url))
                    except Exception as exc:  # noqa: BLE001
                        status, detail = "error", str(exc)
        result = {**event, "timestamp": timestamp, "status": status, "detail": detail}
        results.append(result)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    return results

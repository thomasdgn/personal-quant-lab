"""Format commun des résultats JSON des études (recherche, robustesse, stress, plans).

Chaque fichier garde ses clés historiques (changements additifs uniquement) et
reçoit un bloc ``meta`` identique pour toutes les études :

``{"kind", "schema_version", "generated", "data_window": {"start", "end"} | null,
"synthetic_share": float | null, "notes": [...]}``

Les valeurs non sérialisables sont converties de façon uniforme : NaN et
infinis -> ``null``, types numpy -> types Python, dates -> ISO 8601.
Schéma documenté dans ``docs/results_schema.md``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

RESULTS_SCHEMA_VERSION = "1.0"
KINDS = ("research", "robustness", "stress", "plans")


def to_jsonable(value):
    """Conversion récursive vers des types JSON (NaN -> None)."""
    if is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, pd.Series):
        return to_jsonable(value.to_dict())
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if np.isnan(value) or np.isinf(value) else float(value)
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    return value


def meta_block(kind: str, *, start: str | None = None, end: str | None = None,
               synthetic_share: float | None = None, notes: list[str] | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"Type de résultat inconnu : {kind} ({', '.join(KINDS)}).")
    return {"kind": kind, "schema_version": RESULTS_SCHEMA_VERSION, "generated": date.today().isoformat(),
            "data_window": {"start": start, "end": end} if start or end else None,
            "synthetic_share": synthetic_share, "notes": list(notes or [])}


def write_results_json(payload: dict, output_path: str | Path, *, kind: str, start: str | None = None,
                       end: str | None = None, synthetic_share: float | None = None,
                       notes: list[str] | None = None, indent: int = 2) -> Path:
    """Écrit ``payload`` + bloc ``meta`` commun (JSON strict : aucun NaN)."""
    document = {**payload, "meta": meta_block(kind, start=start, end=end, synthetic_share=synthetic_share,
                                              notes=notes)}
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(document), ensure_ascii=False, indent=indent, allow_nan=False),
                    encoding="utf-8", newline="\n")
    return path


def read_results_json(path: str | Path, kind: str | None = None) -> dict | None:
    """Lit un résultat ; vérifie le type si le bloc ``meta`` est présent (anciens fichiers acceptés)."""
    path = Path(path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("meta")
    if kind and meta and meta.get("kind") != kind:
        raise ValueError(f"{path} : résultat de type {meta.get('kind')}, {kind} attendu.")
    return data

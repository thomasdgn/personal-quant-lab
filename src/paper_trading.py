"""Couche de paper trading & stabilisation (Projet 4B).

Cette couche s'appuie **uniquement** sur les snapshots JSON mensuels déjà produits
par `src/monthly_pipeline.py` / `src/reporting.py`. Elle ne recalcule aucune
stratégie et ne modifie aucune formule financière. Son rôle :

- indexer les rapports mensuels (`list_monthly_snapshots`, `load_monthly_snapshot`) ;
- créer une entrée de journal de paper trading (`create_paper_entry_from_snapshot`) ;
- persister / relire le journal (`save_paper_entry`, `load_paper_entries`) ;
- comparer deux rapports (`compare_monthly_reports`) ;
- enregistrer une décision **humaine** fictive (`update_manual_decision`).

**Aucun ordre réel n'est jamais exécuté.** Tous les statuts sont des marqueurs de
paper trading ; aucun ne signifie une exécution.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

PAPER_SCHEMA_VERSION = "1.0"

# Statuts de décision autorisés. Aucun ne correspond à un ordre réel.
PAPER_STATUSES = ("PENDING", "APPROVED_PAPER", "REJECTED", "SKIPPED", "NEEDS_REVIEW")
DEFAULT_STATUS = "PENDING"

# Statuts considérés comme "verrouillés" : ne pas écraser sans force explicite.
_LOCKED_STATUSES = ("APPROVED_PAPER",)

_MONTHLY_NAME = re.compile(r"^\d{4}-\d{2}-report\.json$")


class PaperTradingError(RuntimeError):
    """Erreur explicite de la couche paper trading."""


# --------------------------------------------------------------------------- #
# Chargement JSON strict (rejet des NaN / Infinity)
# --------------------------------------------------------------------------- #
def _reject_constant(token: str):
    raise PaperTradingError(f"Valeur non finie interdite dans le JSON : {token}")


def _load_json_strict(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        # parse_constant intercepte NaN / Infinity / -Infinity.
        return json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise PaperTradingError(f"JSON invalide : {path} ({exc})") from exc


# --------------------------------------------------------------------------- #
# 5.1 / 5.2 — snapshots mensuels
# --------------------------------------------------------------------------- #
def list_monthly_snapshots(monthly_dir: str | Path) -> list[Path]:
    """Liste les snapshots mensuels valides, triés chronologiquement.

    Ne renvoie que les fichiers nommés ``YYYY-MM-report.json`` situés directement
    dans ``monthly_dir`` (les sous-dossiers temporaires ``check-*``, ``test`` sont
    donc ignorés), qui se chargent comme un snapshot mensuel valide.
    """
    directory = Path(monthly_dir)
    if not directory.is_dir():
        return []
    snapshots: list[Path] = []
    for path in directory.iterdir():
        if not path.is_file() or not _MONTHLY_NAME.match(path.name):
            continue
        try:
            data = _load_json_strict(path)
        except PaperTradingError:
            continue  # fichier illisible -> ignoré silencieusement
        if isinstance(data, dict) and "schema_version" in data and "metadata" in data:
            snapshots.append(path)
    return sorted(snapshots, key=lambda p: p.name)


def load_monthly_snapshot(path: str | Path) -> dict:
    """Charge et valide un snapshot mensuel."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Snapshot introuvable : {path}")
    data = _load_json_strict(path)
    if not isinstance(data, dict):
        raise PaperTradingError(f"Snapshot invalide (racine non-objet) : {path}")
    if "schema_version" not in data:
        raise PaperTradingError(f"schema_version manquant : {path}")
    if "manual_decision" not in data:
        raise PaperTradingError(f"manual_decision manquant : {path}")
    return data


# --------------------------------------------------------------------------- #
# Helpers d'extraction (tolérants aux snapshots incomplets)
# --------------------------------------------------------------------------- #
def _strategy(snapshot: dict, key: str) -> dict:
    value = snapshot.get(key)
    return value if isinstance(value, dict) else {}


def _vt_active(snapshot: dict) -> bool:
    """Le Volatility Targeting est-il actif dans ce snapshot ?

    Compatibilité legacy : si le champ ``enabled`` est absent, on considère le VT
    actif dès lors que des poids cibles réels sont présents. Seul ``enabled: false``
    explicite désactive le VT.
    """
    vt = _strategy(snapshot, "volatility_targeted_strategy")
    if "enabled" in vt:
        return bool(vt["enabled"])
    target_weights = vt.get("target_weights")
    return (
        isinstance(target_weights, dict)
        and any(weight is not None and weight != 0 for weight in target_weights.values())
    )


def _suggested_strategy(snapshot: dict) -> str:
    """Stratégie proposée pour le suivi : celle de la politique (schéma 1.3),
    sinon Momentum + VT si actif (snapshots antérieurs)."""
    followed = (_strategy(snapshot, "policy")).get("followed")
    if followed:
        return followed
    return "momentum_vt" if _vt_active(snapshot) else "momentum"


def _available_strategies(snapshot: dict) -> list[str]:
    strategies = ["benchmark", "momentum"]
    if _vt_active(snapshot):
        strategies.append("momentum_vt")
    # Schéma 1.3 : toutes les stratégies du registre calculées ce mois-ci.
    for name in _strategy(snapshot, "strategies"):
        if name not in strategies:
            strategies.append(name)
    return strategies


def _target_weights_by_strategy(snapshot: dict) -> dict[str, dict | None]:
    weights = {
        "benchmark": _strategy(snapshot, "benchmark").get("target_weights"),
        "momentum": _strategy(snapshot, "momentum_strategy").get("target_weights"),
        "momentum_vt": _strategy(snapshot, "volatility_targeted_strategy").get("target_weights"),
    }
    for name, item in _strategy(snapshot, "strategies").items():
        if isinstance(item, dict) and name not in ("benchmark", "momentum", "momentum_vt"):
            weights[name] = item.get("target_weights")
    return weights


def _alerts_summary(snapshot: dict) -> dict:
    alerts = snapshot.get("alerts", []) or []
    counts = {"INFO": 0, "WARNING": 0, "CRITICAL": 0}
    codes = []
    for alert in alerts:
        counts[alert.get("level", "INFO")] = counts.get(alert.get("level", "INFO"), 0) + 1
        codes.append(alert.get("code"))
    return {"total": len(alerts), "counts": counts, "codes": codes}


# --------------------------------------------------------------------------- #
# 5.3 — création d'une entrée de journal
# --------------------------------------------------------------------------- #
def create_paper_entry_from_snapshot(
    snapshot: dict,
    snapshot_path: str | Path,
    markdown_path: str | Path | None = None,
    *,
    created_at: str | None = None,
) -> dict:
    """Construit une entrée de paper trading à partir d'un snapshot mensuel.

    Le statut de décision est **toujours** ``PENDING`` à la création : aucune
    approbation automatique. Les chemins sources sont conservés.
    """
    meta = snapshot.get("metadata", {})
    report_month = meta.get("report_month")
    if not report_month:
        raise PaperTradingError("Snapshot sans report_month : entrée impossible.")

    return {
        "paper_entry_id": f"paper-{report_month}",
        "schema_version": PAPER_SCHEMA_VERSION,
        "report_month": report_month,
        "report_date": meta.get("report_date"),
        "signal_date": meta.get("signal_date"),
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "source_report_markdown": str(markdown_path) if markdown_path is not None else None,
        "source_snapshot_json": str(snapshot_path),
        "pipeline_status": meta.get("pipeline_status"),
        # Stratégie effectivement suivie : aucune tant qu'aucune décision approuvée.
        "selected_strategy": None,
        "system_suggested_strategy": _suggested_strategy(snapshot),
        "available_strategies": _available_strategies(snapshot),
        "target_weights": _target_weights_by_strategy(snapshot),
        # Décision humaine : TOUJOURS PENDING à la création, même si le snapshot
        # source était déjà annoté. L'approbation ne passe que par paper-decision.
        "manual_decision_status": DEFAULT_STATUS,
        "manual_selected_strategy": None,
        "manual_approved_weights": None,
        "manual_comment": None,
        "manual_validated_at": None,
        "alerts_summary": _alerts_summary(snapshot),
        "follow_up": None,
    }


# --------------------------------------------------------------------------- #
# 5.4 / 5.5 — persistance du journal
# --------------------------------------------------------------------------- #
def save_paper_entry(entry: dict, output_path: str | Path, *, force: bool = False) -> Path:
    """Écrit une entrée de journal en JSON stable (UTF-8, sans NaN).

    Protection : ne réécrit pas silencieusement une entrée dont la décision est
    déjà verrouillée (``APPROVED_PAPER``) sans ``force=True``.
    """
    path = Path(output_path)
    if path.exists() and not force:
        try:
            existing = _load_json_strict(path)
        except PaperTradingError:
            existing = {}
        if existing.get("manual_decision_status") in _LOCKED_STATUSES:
            raise PaperTradingError(
                f"Entrée déjà approuvée (paper) : {path}. Utilise force=True pour écraser."
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    # allow_nan=False garantit un JSON standard sans NaN / Infinity.
    path.write_text(
        json.dumps(entry, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def load_paper_entry(path: str | Path) -> dict:
    """Charge une entrée de journal unique."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Entrée introuvable : {path}")
    data = _load_json_strict(path)
    if not isinstance(data, dict) or "manual_decision_status" not in data:
        raise PaperTradingError(f"Entrée de paper trading invalide : {path}")
    return data


def load_paper_entries(paper_dir: str | Path) -> list[dict]:
    """Charge le journal complet, trié chronologiquement (fichiers invalides ignorés)."""
    directory = Path(paper_dir)
    if not directory.is_dir():
        return []
    entries = []
    for path in sorted(directory.glob("*-paper-entry.json"), key=lambda p: p.name):
        try:
            data = _load_json_strict(path)
        except PaperTradingError:
            continue
        if isinstance(data, dict) and data.get("schema_version"):
            entries.append(data)
    return entries


# --------------------------------------------------------------------------- #
# 5.6 — comparaison de deux rapports
# --------------------------------------------------------------------------- #
def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _delta(current, previous) -> float | None:
    c, p = _num(current), _num(previous)
    return None if c is None or p is None else c - p


def compare_monthly_reports(previous: dict, current: dict) -> dict:
    """Compare deux snapshots mensuels et renvoie une structure sérialisable."""
    prev_mom = _strategy(previous, "momentum_strategy")
    cur_mom = _strategy(current, "momentum_strategy")
    prev_vt = _strategy(previous, "volatility_targeted_strategy")
    cur_vt = _strategy(current, "volatility_targeted_strategy")
    prev_meta = previous.get("metadata", {})
    cur_meta = current.get("metadata", {})

    prev_codes = set(_alerts_summary(previous)["codes"])
    cur_codes = set(_alerts_summary(current)["codes"])

    return {
        "previous_month": prev_meta.get("report_month"),
        "current_month": cur_meta.get("report_month"),
        "momentum_selected_from": prev_mom.get("selected_assets"),
        "momentum_selected_to": cur_mom.get("selected_assets"),
        "momentum_selected_changed": prev_mom.get("selected_assets") != cur_mom.get("selected_assets"),
        "momentum_weights_changed": prev_mom.get("target_weights") != cur_mom.get("target_weights"),
        "vt_selected_changed": prev_vt.get("selected_assets") != cur_vt.get("selected_assets"),
        "vt_weights_changed": prev_vt.get("target_weights") != cur_vt.get("target_weights"),
        "vt_cash_change": _delta(cur_vt.get("cash_weight"), prev_vt.get("cash_weight")),
        "vt_exposure_change": _delta(cur_vt.get("invested_exposure"), prev_vt.get("invested_exposure")),
        "realized_volatility_change": _delta(cur_vt.get("realized_volatility"), prev_vt.get("realized_volatility")),
        "vt_max_drawdown_change": _delta(cur_vt.get("max_drawdown"), prev_vt.get("max_drawdown")),
        "vt_capital_change": _delta(cur_vt.get("theoretical_capital"), prev_vt.get("theoretical_capital")),
        "pipeline_status_from": prev_meta.get("pipeline_status"),
        "pipeline_status_to": cur_meta.get("pipeline_status"),
        "pipeline_status_changed": prev_meta.get("pipeline_status") != cur_meta.get("pipeline_status"),
        "suggested_strategy_from": _suggested_strategy(previous),
        "suggested_strategy_to": _suggested_strategy(current),
        "suggested_strategy_changed": _suggested_strategy(previous) != _suggested_strategy(current),
        "alerts_count_change": len(cur_codes | set()) - len(prev_codes | set()),
        "new_alert_codes": sorted(cur_codes - prev_codes),
        "resolved_alert_codes": sorted(prev_codes - cur_codes),
    }


# --------------------------------------------------------------------------- #
# Décision manuelle (paper trading uniquement)
# --------------------------------------------------------------------------- #
JOURNAL_FIELDS = ("confidence", "pros", "cons", "next_check")


def _validate_journal(journal: dict) -> dict:
    """Contrôle les champs du journal de décision ; renvoie les champs renseignés."""
    unknown = set(journal) - set(JOURNAL_FIELDS)
    if unknown:
        raise PaperTradingError(f"Champs de journal inconnus : {', '.join(sorted(unknown))}.")
    clean = {k: v for k, v in journal.items() if v is not None}
    confidence = clean.get("confidence")
    if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, int)
                                   or not 1 <= confidence <= 5):
        raise PaperTradingError("La confiance doit être un entier de 1 à 5.")
    for key in ("pros", "cons", "next_check"):
        if key in clean and not isinstance(clean[key], str):
            raise PaperTradingError(f"Le champ {key} doit être un texte.")
    return clean


def update_manual_decision(
    entry: dict,
    status: str,
    *,
    strategy: str | None = None,
    comment: str | None = None,
    validated_at: str | None = None,
    journal: dict | None = None,
) -> dict:
    """Met à jour la décision **humaine** d'une entrée (aucun ordre réel).

    ``status`` doit appartenir à ``PAPER_STATUSES``. Pour ``APPROVED_PAPER``, une
    ``strategy`` valide (présente dans ``available_strategies``) est obligatoire :
    l'entrée mémorise alors la stratégie suivie et ses poids cibles.

    ``journal`` (optionnel) : champs du journal de décision du guide
    (``confidence`` 1-5, ``pros``, ``cons``, ``next_check``), stockés dans
    ``decision_journal``. Les champs absents ou ``None`` sont ignorés ; une
    entrée ancienne sans ce champ reste valide.
    """
    if status not in PAPER_STATUSES:
        raise PaperTradingError(
            f"Statut invalide : {status}. Autorisés : {', '.join(PAPER_STATUSES)}."
        )

    updated = dict(entry)  # copie superficielle
    if journal:
        updated["decision_journal"] = {**(entry.get("decision_journal") or {}), **_validate_journal(journal)}
    updated["manual_decision_status"] = status
    updated["manual_comment"] = comment
    updated["manual_validated_at"] = validated_at or datetime.now().isoformat(timespec="seconds")

    if status == "APPROVED_PAPER":
        available = entry.get("available_strategies", [])
        if strategy not in available:
            raise PaperTradingError(
                f"Stratégie inconnue : {strategy}. Disponibles : {', '.join(available)}."
            )
        weights = (entry.get("target_weights") or {}).get(strategy)
        updated["manual_selected_strategy"] = strategy
        updated["selected_strategy"] = strategy
        updated["manual_approved_weights"] = weights
    else:
        # REJECTED / SKIPPED / NEEDS_REVIEW / PENDING : aucune stratégie suivie.
        updated["manual_selected_strategy"] = strategy
        updated["selected_strategy"] = None
        updated["manual_approved_weights"] = None

    return updated

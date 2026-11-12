"""Import normalisé et rapprochement explicite du PEA ; aucune connexion bancaire."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

import pandas as pd
import yaml

from src.ledger import COLUMNS, load_transactions, state_at
from src.positions import load_positions
from src.trading_calendar import session_age


def fingerprint(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def import_transactions(source: str | Path, target: str | Path, mapping: dict | None = None, *, apply=False) -> dict:
    """Prévisualisation par défaut. Mapping explicite : colonne interne -> colonne source.

    L'interface est validée sur des exemples fictifs, pas sur un export Bourso réel.
    operation_id est obligatoire : deux achats identiques peuvent être légitimes.
    """
    mapping = mapping or {}
    frame = pd.read_csv(source, sep=mapping.get("separator", ","), dtype=str, keep_default_na=False)
    columns = mapping.get("columns") or {}
    frame = frame.rename(columns={v: k for k, v in columns.items()})
    required = set(COLUMNS[:8]) | {"operation_id"}
    if not required.issubset(frame):
        raise ValueError(f"Colonnes normalisées manquantes : {sorted(required - set(frame))}.")
    frame = frame.reindex(columns=[*COLUMNS, "operation_id"], fill_value="")
    frame["operation_id"] = frame["operation_id"].str.strip()
    if frame["operation_id"].eq("").any() or frame["operation_id"].duplicated().any():
        raise ValueError("Chaque opération importée doit avoir un identifiant unique non vide.")
    frame["date"] = pd.to_datetime(frame["date"], format=mapping.get("date_format", "%Y-%m-%d")).dt.strftime("%Y-%m-%d")
    for col in ("parts", "prix", "montant", "frais"):
        values = frame[col].str.replace("\u202f", "", regex=False).str.replace(" ", "", regex=False)
        if mapping.get("decimal", ".") == ",":
            values = values.str.replace(",", ".", regex=False)
        frame[col] = pd.to_numeric(values.replace("", "0"), errors="raise")
    target = Path(target)
    existing = pd.read_csv(target, keep_default_na=False, dtype={"operation_id": str}) if target.exists() else pd.DataFrame(columns=frame.columns)
    if not existing.empty and "operation_id" not in existing:
        raise ValueError("Journal historique sans identifiants : rapprochement manuel requis avant import.")
    old = existing.set_index("operation_id") if not existing.empty else pd.DataFrame()
    duplicates = []
    for _, row in frame.iterrows():
        key = row["operation_id"]
        if key not in old.index:
            continue
        before = old.loc[key]
        for col in COLUMNS[:8]:
            a, b = before[col], row[col]
            equal = abs(float(a or 0) - float(b or 0)) < 1e-8 if col in ("parts", "prix", "montant", "frais") else str(a) == str(b)
            if not equal:
                raise ValueError(f"Identifiant {key} réutilisé avec des données différentes.")
        duplicates.append(key)
    additions = frame[~frame["operation_id"].isin(duplicates)]
    merged = pd.concat([existing, additions], ignore_index=True).sort_values("date", kind="stable")
    # Valider avant toute écriture du journal cible.
    with tempfile.TemporaryDirectory(dir=target.parent) as folder:
        candidate = Path(folder) / "transactions.csv"
        merged.to_csv(candidate, index=False)
        checked = load_transactions(candidate)
        state = state_at(checked)
        if state["warnings"]:
            raise ValueError(" ; ".join(state["warnings"]))
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_suffix(".import.tmp")
        merged.to_csv(staged, index=False)
        staged.replace(target)
    return {"applied": bool(apply), "added": len(additions), "duplicates": len(duplicates),
            "total": len(merged), "source_sha256": fingerprint(source),
            "format_status": "normalisé ; export Bourso réel non validé"}


def reconcile(transactions_path, snapshot_path, *, receipt_path=None) -> dict:
    transactions = load_transactions(transactions_path)
    snapshot = load_positions(snapshot_path)
    raw = yaml.safe_load(Path(snapshot_path).read_text(encoding="utf-8"))
    if transactions is None or transactions.empty or snapshot is None or not snapshot["date"] or not raw.get("source"):
        raise ValueError("Journal non vide et relevé daté avec source requis.")
    when = pd.Timestamp(snapshot["date"])
    if transactions["date"].max() > when:
        raise ValueError("Le relevé précède des opérations du journal.")
    state = state_at(transactions, when)
    pea = state["enveloppes"].get("pea", {"parts": {}, "liquidites": 0.0})
    expected = {r["ticker"]: r["parts"] for r in snapshot["lignes"] if r["enveloppe"] == "pea"}
    issues = list(state["warnings"])
    for ticker in set(expected) | set(pea["parts"]):
        if abs(expected.get(ticker, 0) - pea["parts"].get(ticker, 0)) > 1e-8:
            issues.append(f"{ticker} : nombre de parts différent du relevé.")
    if "pea" not in snapshot["liquidites_eur"] or abs(snapshot["liquidites_eur"]["pea"] - pea["liquidites"]) > 0.01:
        issues.append("Liquidités différentes du relevé ou absentes.")
    result = {"ok": not issues, "issues": issues, "as_of": snapshot["date"],
              "transactions_sha256": fingerprint(transactions_path), "snapshot_sha256": fingerprint(snapshot_path),
              "snapshot_path": str(Path(snapshot_path).resolve()), "source": raw["source"]}
    if receipt_path:
        Path(receipt_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def readiness(prices, tickers, *, transactions_path, receipt_path, as_of=None, max_sessions=1) -> dict:
    now = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.now(tz="Europe/Paris").tz_localize(None)
    issues = []
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8")) if Path(receipt_path).exists() else {}
    if not receipt.get("ok") or not Path(transactions_path).exists():
        issues.append("Portefeuille réel non rapproché d'un relevé.")
    elif receipt.get("transactions_sha256") != fingerprint(transactions_path):
        issues.append("Le journal a changé depuis le rapprochement.")
    elif not Path(receipt.get("snapshot_path", "")).is_file() or receipt.get("snapshot_sha256") != fingerprint(receipt["snapshot_path"]):
        issues.append("Le relevé rapproché a changé ou est absent.")
    if receipt.get("as_of") and session_age(receipt["as_of"], now) > 22:
        issues.append("Rapprochement de plus de 22 séances : renouveler le relevé.")
    for ticker in tickers:
        series = prices[ticker].dropna() if ticker in prices else pd.Series(dtype=float)
        if series.empty or session_age(series.index[-1], now) > max_sessions:
            issues.append(f"{ticker} : cours absent ou trop ancien pour une proposition actuelle.")
    return {"ready": not issues, "issues": issues, "as_of": now.isoformat(), "execution_status": "NON_EXECUTE"}

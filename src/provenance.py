"""Empreintes reproductibles et registre persistant des essais uniques."""
import hashlib
import json
from pathlib import Path
import sqlite3


def digest_files(paths) -> str:
    digest = hashlib.sha256()
    for path in sorted(map(Path, paths), key=str):
        digest.update(path.name.encode())
        digest.update(path.read_bytes() if path.exists() else b"ABSENT")
    return digest.hexdigest()


def project_revision(root: Path) -> str:
    return digest_files([*root.glob("config/*.yaml"), *root.glob("data/processed/*.csv"),
                         *root.glob("data/macro/*.csv")])


def code_revision(root: Path) -> str:
    return digest_files([*root.glob("src/**/*.py"), *root.glob("app/**/*.py"), root / "requirements.txt"])


def record_trial(database: Path, parameters: dict, provenance: dict) -> tuple[str, int]:
    serialized = json.dumps({"parameters": parameters, "provenance": provenance}, sort_keys=True)
    identity = hashlib.sha256(serialized.encode()).hexdigest()
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE IF NOT EXISTS trials (id TEXT PRIMARY KEY, specification TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO trials VALUES (?, ?)", (identity, serialized))
        count = db.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
    return identity, count

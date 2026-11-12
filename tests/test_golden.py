"""Non-régression du rapport mensuel sur un jeu de données figé (fichier golden).

Le snapshot JSON produit à partir de prix synthétiques déterministes doit rester
identique (horodatages exclus). Après un changement **volontaire** du calcul ou
du schéma : ``python -m pytest tests/test_golden.py --update-golden``, relire le
diff Git de ``tests/golden/monthly_snapshot.json``, puis commiter.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.monthly_pipeline import MonthlyPipelineConfig, run_monthly_pipeline
from src.policy import InvestmentPolicy
from src.reporting import save_report_snapshot

GOLDEN = Path(__file__).parent / "golden" / "monthly_snapshot.json"
VOLATILE_KEYS = {"generated_at", "timestamp"}


def _frozen_prices() -> pd.DataFrame:
    index = pd.bdate_range("2016-01-01", "2026-08-31")
    rng = np.random.default_rng(20260924)
    returns = rng.normal([0.0004, 0.0005, 0.0002, 0.0001, 0.00008], [0.01, 0.012, 0.013, 0.003, 0.0002],
                         size=(len(index), 5))
    prices = pd.DataFrame(100 * np.cumprod(1 + returns, axis=0), index=index,
                          columns=["CW8.PA", "ESE.PA", "PAEEM.PA", "OBLI.PA", "CSH2.PA"])
    prices.loc[prices.index < "2019-01-01", "OBLI.PA"] = np.nan
    prices.loc[prices.index < "2025-03-17", "CSH2.PA"] = np.nan
    return prices


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _compare(actual, expected, path="racine"):
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), f"clés différentes en {path}"
        for key in expected:
            _compare(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), f"longueur différente en {path}"
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            _compare(a, e, f"{path}[{i}]")
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, rel=1e-9, abs=1e-12), f"valeur différente en {path}"
    else:
        assert actual == expected, f"valeur différente en {path} : {actual!r} != {expected!r}"


def test_monthly_snapshot_matches_golden(tmp_path, request):
    roles = {"CW8.PA": "candidate", "ESE.PA": "candidate", "PAEEM.PA": "candidate", "OBLI.PA": "defensive",
             "CSH2.PA": "cash_proxy"}
    result = run_monthly_pipeline(_frozen_prices(), MonthlyPipelineConfig(), report_date="2026-08-31",
                                  generation_time="2026-09-01T09:00:00", asset_roles=roles,
                                  policy=InvestmentPolicy())
    snapshot = _strip(json.loads(save_report_snapshot(result, tmp_path / "s.json").read_text(encoding="utf-8")))
    if request.config.getoption("--update-golden") or not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                          newline="\n")
        pytest.skip("Fichier golden (re)généré : relire le diff puis commiter.")
    _compare(snapshot, json.loads(GOLDEN.read_text(encoding="utf-8")))


def test_golden_comparison_detects_small_changes():
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    altered = json.loads(json.dumps(expected))
    altered["momentum_strategy"]["cagr"] *= 1 + 1e-6
    with pytest.raises(AssertionError, match="momentum_strategy.cagr"):
        _compare(altered, expected)
    altered = json.loads(json.dumps(expected))
    altered["policy"]["followed"] = "benchmark"
    with pytest.raises(AssertionError, match="policy.followed"):
        _compare(altered, expected)

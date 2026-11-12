"""Fiabilité des données : fiches produits (ISIN), dividendes estimés, fiscalité 2026."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import main
from src.long_history import load_long_config, to_eur_monthly
from src.taxes import TaxConfig, envelope_net_values
from src.universe import fiche_warnings, isin_is_valid, load_universe, validate_fiche

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("isin, ok", [
    ("LU1681043599", True), ("IE0002XZSHO1", True), ("FR0013346681", True), ("US0378331005", True),
    ("US0378331006", False), ("FR001334668", False), ("fr0013346681", False), ("FR00133466A1", False),
    (None, False),
])
def test_isin_checksum(isin, ok):
    assert isin_is_valid(isin) is ok


def test_every_active_asset_has_a_verified_fiche():
    assets = load_universe(ROOT / "config" / "assets.yaml")
    for asset in assets:
        fiche = asset["fiche"]
        assert fiche is not None, asset["ticker"]
        assert isin_is_valid(fiche["isin"]) and fiche["verifie_le"] and fiche["source"]
    isins = [a["fiche"]["isin"] for a in assets]
    assert len(isins) == len(set(isins))
    labels = {a["ticker"]: a["name"] for a in assets}
    assert "ESG" not in labels["ESE.PA"] and "Small Cap" not in labels["GWT.PA"]
    warnings = " ".join(fiche_warnings(load_universe(ROOT / "config" / "assets.yaml", include_inactive=True)))
    assert "OBLI.PA" in warnings and "CSH2.PA" in warnings and "GOVF.PA" in warnings


@pytest.mark.parametrize("fiche, message", [
    ({"isin": "FR0013346680"}, "ISIN invalide"),
    ({"isin": "FR0013346681", "ter_pct": 12}, "ter_pct"),
    ({"isin": "FR0013346681", "pea": "oui"}, "pea"),
    ({"isin": "FR0013346681", "verifie_le": "hier"}, "verifie_le"),
    ({"isin": "FR0013346681", "autre": 1}, "clés inconnues"),
    ("texte", "dictionnaire"),
])
def test_invalid_fiches(fiche, message):
    with pytest.raises(ValueError, match=message):
        validate_fiche(fiche, "X.PA")


def test_universe_cli(capsys):
    assert main.main(["universe"]) == 0
    out = capsys.readouterr().out
    assert "LU1681043599" in out and "Points d'attention" in out


def test_dividend_yield_is_added_to_price_index(tmp_path):
    path = tmp_path / "long.yaml"
    path.write_text("chains:\n  CW8.PA:\n    - {ticker: IDX, currency: EUR, dividend_yield_pct: 2.4}\n"
                    "  PUST.PA:\n    - {ticker: QQQ, currency: EUR}\n", encoding="utf-8")
    config = load_long_config(path)
    index = pd.date_range("2004-01-01", periods=400, freq="B")
    daily = pd.DataFrame({"IDX": 100.0, "QQQ": 50.0}, index=index)
    daily.loc[: "2004-02-15", "IDX"] = np.nan  # chaîne qui démarre plus tard
    monthly = to_eur_monthly(daily, config)
    idx = monthly["IDX"].dropna()
    assert idx.pct_change().dropna().to_numpy() == pytest.approx((1.024) ** (1 / 12) - 1)
    assert idx.iloc[0] == pytest.approx(100.0)
    assert monthly["QQQ"].pct_change().dropna().abs().max() == 0.0  # aucun ajout sans dividend_yield_pct
    path.write_text("chains:\n  CW8.PA:\n    - {ticker: IDX, currency: EUR, dividend_yield_pct: 40}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dividend_yield_pct"):
        load_long_config(path)
    assert "dividend_yield_pct" in (ROOT / "config" / "long_history.yaml").read_text(encoding="utf-8")


def test_2026_tax_rates():
    taxes = TaxConfig()
    assert (taxes.prelevements_sociaux_pct, taxes.flat_tax_pct, taxes.av_prelevements_sociaux_pct) == (18.6, 31.4, 17.2)
    # Assurance-vie < 8 ans : 12,8 % d'impôt + 17,2 % de prélèvements sociaux (pas les 18,6 % du PEA/CTO).
    assert envelope_net_values("assurance_vie", 110.0, 100.0, 3) == pytest.approx(110 - 10 * 0.30)
    assert envelope_net_values("crypto", 110.0, 100.0, 3) == pytest.approx(110 - 10 * 0.314)

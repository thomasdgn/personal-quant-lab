"""Conditions BoursoBank datées ; aucun accès bancaire ni ordre."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from src.costs import FeeModel


@dataclass(frozen=True)
class BrokerProfile:
    offer: str
    confirmed: bool
    effective_from: str
    verified_on: str
    source: str
    minimum_buy: float
    spread_bps: float
    products: dict

    def fee_model(self) -> FeeModel:
        if not self.confirmed:
            raise ValueError("Offre du courtier non confirmée.")
        free = tuple(t for t, p in self.products.items() if p.get("free_buy") is True
                     and p.get("verified_on") and p.get("isin") and p.get("source"))
        return FeeModel(proportional=0, tariff=self.offer, commission_cap=0.005,
                        minimum_order_amount=self.minimum_buy, free_buy_tickers=free,
                        spread_bps={"default": self.spread_bps})

    def check_product(self, ticker: str, assets: list[dict]) -> list[str]:
        asset = next((a for a in assets if a["ticker"] == ticker), None)
        fiche = (asset or {}).get("fiche") or {}
        issues = []
        if not asset or not asset.get("universe_active") or fiche.get("pea") is not True or not fiche.get("isin"):
            issues.append(f"{ticker} : identité / éligibilité PEA non confirmée.")
        product = self.products.get(ticker) or {}
        if product.get("tradable") is not True or product.get("isin") != fiche.get("isin"):
            issues.append(f"{ticker} : disponibilité chez BoursoBank à confirmer par ISIN.")
        return issues


def load_broker_profile(path: str | Path) -> BrokerProfile:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("broker") != "boursobank" or raw.get("envelope") != "pea":
        raise ValueError("Profil BoursoBank PEA attendu.")
    if raw.get("offer") not in ("decouverte", "trader", "ultimate_trader"):
        raise ValueError("Offre BoursoBank invalide.")
    for key in ("effective_from", "verified_on"):
        pd.Timestamp(raw[key])
    if not isinstance(raw.get("confirmed"), bool):
        raise ValueError("Confirmation explicite du barème requise.")
    from src.universe import isin_is_valid

    products = raw.get("products") or {}
    if not isinstance(products, dict):
        raise ValueError("Catalogue produits invalide.")
    for ticker, product in products.items():
        if not isinstance(product, dict) or not isin_is_valid(str(product.get("isin", ""))):
            raise ValueError(f"ISIN produit invalide pour {ticker}.")
        for key in ("tradable", "free_buy"):
            if product.get(key) is not None and not isinstance(product[key], bool):
                raise ValueError(f"{ticker}.{key} doit être true, false ou null.")
        if not product.get("source") or not product.get("verified_on"):
            raise ValueError(f"{ticker} : source et date de vérification requises.")
        pd.Timestamp(product["verified_on"])
    result = BrokerProfile(raw["offer"], raw["confirmed"], str(raw["effective_from"]), str(raw["verified_on"]),
                           raw["source"], float(raw["minimum_buy_eur"]), float(raw.get("spread_bps", 0)),
                           products)
    result.fee_model()
    return result

"""Modèle de frais d'ordre configurable (section ``costs`` de strategy_params.yaml).

Un ordre de montant ``M`` (en euros) coûte :

    frais = max(minimum_per_order, fixed_per_order + proportional × M) + demi-spread × M

- ``proportional``      : commission proportionnelle (ex. 0,001 = 0,10 %) ;
- ``fixed_per_order``   : forfait par ordre (ex. 1,00 €) ;
- ``minimum_per_order`` : commission minimale par ordre ;
- ``spread_bps``        : fourchette achat/vente estimée par ticker, en points de
  base ; on paie la moitié à chaque ordre (clé ``default`` possible).

Un ordre de montant nul ne coûte rien. Ces frais servent au planificateur de
versements et à la simulation DCA ; le backtest mensuel garde son modèle
proportionnel aux montants traités (voir ``backtest.transaction_cost``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math

import yaml


@dataclass(frozen=True)
class FeeModel:
    proportional: float = 0.001
    fixed_per_order: float = 0.0
    minimum_per_order: float = 0.0
    spread_bps: dict[str, float] = field(default_factory=dict)
    minimum_order_amount: float = 0.0
    tariff: str = "generic"
    commission_cap: float | None = None
    free_buy_tickers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("proportional", "fixed_per_order", "minimum_per_order", "minimum_order_amount"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"costs.{name} doit être un nombre positif ou nul.")
        if self.proportional >= 0.1:
            raise ValueError("costs.proportional doit être une fraction (0,001 = 0,10 %).")
        if self.tariff not in ("generic", "decouverte", "trader", "ultimate_trader"):
            raise ValueError("Barème de courtier inconnu.")
        if self.commission_cap is not None and not 0 <= self.commission_cap < 0.1:
            raise ValueError("Plafond de commission invalide.")
        for ticker, bps in self.spread_bps.items():
            if isinstance(bps, bool) or not isinstance(bps, (int, float)) or not math.isfinite(bps) or bps < 0:
                raise ValueError(f"costs.spread_bps.{ticker} doit être un nombre positif ou nul.")

    def half_spread(self, ticker: str | None) -> float:
        bps = self.spread_bps.get(ticker, self.spread_bps.get("default", 0.0)) if ticker else \
            self.spread_bps.get("default", 0.0)
        return float(bps) / 2.0 / 10_000.0

    def order_cost(self, amount: float, ticker: str | None = None, *, side: str = "BUY") -> float:
        """Frais d'un ordre d'achat ou de vente de ``amount`` euros (valeur absolue)."""
        amount = abs(float(amount))
        if not math.isfinite(amount) or side not in ("BUY", "SELL"):
            raise ValueError("Montant fini et sens BUY/SELL requis.")
        if amount == 0.0:
            return 0.0
        commission = max(self.minimum_per_order, self.fixed_per_order + self.proportional * amount)
        if self.tariff != "generic":
            threshold, fixed, rate = {"decouverte": (500, 1.99, 0.006),
                                      "trader": (7750, 16.65, 0.0022),
                                      "ultimate_trader": (10000, 9.90, 0.0012)}[self.tariff]
            commission = fixed if amount <= threshold else rate * amount
        if self.commission_cap is not None:
            commission = min(commission, self.commission_cap * amount)
        if side == "BUY" and ticker in self.free_buy_tickers:
            commission = 0.0
        return commission + self.half_spread(ticker) * amount

    def admissible(self, amount: float, *, side: str = "BUY") -> bool:
        return math.isfinite(amount) and amount > 0 and (side == "SELL" or amount + 1e-8 >= self.minimum_order_amount)

    def effective_rate(self, amount: float, ticker: str | None = None) -> float:
        """Frais rapportés au montant de l'ordre (0 si montant nul)."""
        return self.order_cost(amount, ticker) / abs(amount) if amount else 0.0


def load_fee_model(config_path: str | Path) -> FeeModel:
    """Lit la section ``costs`` ; absente = frais proportionnels du backtest."""
    with Path(config_path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    costs = raw.get("costs")
    if costs is None:
        proportional = (raw.get("backtest") or {}).get("transaction_cost", 0.001)
        return FeeModel(proportional=float(proportional))
    if not isinstance(costs, dict):
        raise ValueError(f"{config_path} : la section costs doit être un dictionnaire.")
    if "broker_profile" in costs:
        from src.broker import load_broker_profile

        return load_broker_profile(Path(config_path).parent / costs["broker_profile"]).fee_model()
    unknown = set(costs) - {"proportional", "fixed_per_order", "minimum_per_order", "spread_bps"}
    if unknown:
        raise ValueError(f"{config_path} : clés inconnues dans costs : {', '.join(sorted(unknown))}.")
    return FeeModel(
        proportional=costs.get("proportional", 0.001),
        fixed_per_order=costs.get("fixed_per_order", 0.0),
        minimum_per_order=costs.get("minimum_per_order", 0.0),
        spread_bps=dict(costs.get("spread_bps") or {}),
    )

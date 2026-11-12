"""Configuration du pipeline mensuel (``config/strategy_params.yaml``) : chargement et validation.

Extrait de ``src/monthly_pipeline.py`` (v6) ; les noms restent importables depuis ce dernier.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml


class PipelineValidationError(RuntimeError):
    """Anomalie structurelle (poids/date invalides) empêchant la publication."""


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MomentumConfig:
    lookback_months: int = 12
    skip_months: int = 1
    moving_average_window: int = 10
    top_n: int = 1
    require_positive_momentum: bool = False


@dataclass(frozen=True)
class VolTargetConfig:
    enabled: bool = True
    volatility_window: int = 3
    target_volatility: float = 0.10
    min_exposure: float = 0.0
    max_exposure: float = 1.0


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 10_000.0
    transaction_cost: float = 0.001
    cash_return: float = 0.0


@dataclass(frozen=True)
class UniverseConfig:
    """Traitement des rôles d'actifs (``role`` dans assets.yaml).

    ``defensive_as_candidates`` : les actifs ``defensive`` (obligataire) sont
    classés par le Momentum avec les actions (comportement historique).
    ``use_cash_proxy_return`` : le rendement mensuel de l'actif ``cash_proxy``
    (ETF monétaire) rémunère la poche cash ; sinon ``backtest.cash_return``.
    """

    defensive_as_candidates: bool = True
    use_cash_proxy_return: bool = True


@dataclass(frozen=True)
class ReportingConfig:
    stale_data_days_warning: int = 7
    stale_data_days_critical: int = 30


@dataclass(frozen=True)
class MonthlyPipelineConfig:
    benchmark_ticker: str = "CW8.PA"
    momentum: MomentumConfig = field(default_factory=MomentumConfig)
    volatility_targeting: VolTargetConfig = field(default_factory=VolTargetConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    universe: UniverseConfig = field(default_factory=UniverseConfig)

    def validate(self) -> None:
        """Vérifie la cohérence de la configuration."""
        m = self.momentum
        if m.lookback_months <= 0 or m.skip_months < 0 or m.skip_months >= m.lookback_months:
            raise ValueError("Paramètres momentum invalides (lookback/skip).")
        if m.moving_average_window <= 0 or m.top_n <= 0:
            raise ValueError("Paramètres momentum invalides (MA/top_n).")
        v = self.volatility_targeting
        if v.target_volatility <= 0 or v.volatility_window <= 1:
            raise ValueError("Paramètres de volatility targeting invalides.")
        if not (0.0 <= v.min_exposure <= v.max_exposure <= 1.0):
            raise ValueError("Bornes d'exposition invalides (0 <= min <= max <= 1).")
        b = self.backtest
        if b.initial_capital <= 0 or b.transaction_cost < 0:
            raise ValueError("Paramètres de backtest invalides.")
        if not self.benchmark_ticker:
            raise ValueError("Le ticker de benchmark est obligatoire.")


def load_config(path: str | Path) -> MonthlyPipelineConfig:
    """Charge et valide `config/strategy_params.yaml`."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration introuvable : {path}")
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"{path} : la configuration doit être un dictionnaire YAML.")

    benchmark = raw.get("benchmark") or {}
    if not isinstance(benchmark, dict) or not isinstance(benchmark.get("ticker", "CW8.PA"), str):
        raise ValueError(f"{path} : benchmark.ticker doit être un texte (ex. CW8.PA).")
    config = MonthlyPipelineConfig(
        benchmark_ticker=benchmark.get("ticker", "CW8.PA"),
        momentum=_config_section(raw, "momentum", MomentumConfig, path),
        volatility_targeting=_config_section(raw, "volatility_targeting", VolTargetConfig, path),
        backtest=_config_section(raw, "backtest", BacktestConfig, path),
        reporting=_config_section(raw, "reporting", ReportingConfig, path),
        universe=_config_section(raw, "universe", UniverseConfig, path),
    )
    try:
        config.validate()
    except ValueError as exc:
        raise ValueError(f"{path} : {exc}") from exc
    return config


def _config_section(raw: dict, name: str, cls: type, path: Path):
    """Construit une section typée ; erreurs explicites (fichier, clé, attendu)."""
    section = raw.get(name) or {}
    if not isinstance(section, dict):
        raise ValueError(f"{path} : la section '{name}' doit être un dictionnaire.")
    expected = {f.name: f for f in fields(cls)}
    unknown = sorted(set(section) - set(expected))
    if unknown:
        raise ValueError(f"{path} : clé inconnue '{name}.{unknown[0]}' "
                         f"(clés attendues : {', '.join(expected)}).")
    for key, value in section.items():
        default = expected[key].default
        if isinstance(default, bool):
            ok, label = isinstance(value, bool), "true ou false"
        elif isinstance(default, int):
            ok, label = isinstance(value, int) and not isinstance(value, bool), "un entier"
        elif isinstance(default, float):
            ok, label = isinstance(value, (int, float)) and not isinstance(value, bool), "un nombre"
        else:
            ok, label = True, ""
        if not ok:
            raise ValueError(f"{path} : '{name}.{key}' doit être {label} (valeur lue : {value!r}).")
    return cls(**section)

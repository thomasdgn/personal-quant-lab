"""Politique d'investissement (``config/policy.yaml``) et contrôles informatifs.

La politique dit **quelle stratégie du registre est suivie** par le rapport, le
journal, le plan de versement et le tableau de bord, ainsi que les garde-fous
de l'investisseuse (drawdown maximal accepté, règle de rééquilibrage). Le
laboratoire ne la modifie jamais : c'est un choix humain.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from src.strategies import REGISTRY

REBALANCING_RULES = ("mensuel", "bandes")
_KEYS = {"objectif", "horizon_ans", "strategie_suivie", "coeur_satellite", "drawdown_max_accepte",
         "reequilibrage", "bande_tolerance_pct", "revue", "plan_suivi", "allocation_fixe", "regle_krach"}


@dataclass(frozen=True)
class InvestmentPolicy:
    objectif: str = "Croissance long terme du PEA ; décision finale humaine."
    horizon_ans: int = 30
    strategie_suivie: str = "momentum_vt"
    part_coeur: float = 0.8
    satellite: str = "momentum_vt"
    drawdown_max_accepte: float = 0.25
    reequilibrage: str = "mensuel"
    bande_tolerance_pct: float = 5.0
    revue: str = "mensuelle"
    plan_suivi: str | None = None                                  # plan de config/plans.yaml (information)
    allocation_fixe: dict[str, float] = field(default_factory=dict)  # utilisée si strategie_suivie = allocation_fixe
    regle_krach: str | None = None      # engagement écrit à froid, relu quand la baisse dépasse le seuil
    seuil_krach: float = 0.30           # baisse depuis le plus haut qui déclenche le rappel

    def __post_init__(self) -> None:
        if self.strategie_suivie not in REGISTRY:
            raise ValueError(f"strategie_suivie inconnue : {self.strategie_suivie!r} "
                             f"(attendu : {', '.join(REGISTRY)}).")
        if self.satellite not in REGISTRY or self.satellite == "core_satellite":
            raise ValueError(f"coeur_satellite.satellite invalide : {self.satellite!r} "
                             "(une stratégie du registre autre que core_satellite).")
        if not 0.0 <= self.part_coeur <= 1.0:
            raise ValueError("coeur_satellite.part_coeur doit être compris entre 0 et 1.")
        if not 0.0 < self.drawdown_max_accepte < 1.0:
            raise ValueError("drawdown_max_accepte doit être une fraction entre 0 et 1 (ex. 0.25).")
        if self.reequilibrage not in REBALANCING_RULES:
            raise ValueError(f"reequilibrage doit être parmi {', '.join(REBALANCING_RULES)}.")
        if not 0.0 < self.bande_tolerance_pct < 50.0:
            raise ValueError("bande_tolerance_pct doit être compris entre 0 et 50.")
        if not isinstance(self.horizon_ans, int) or isinstance(self.horizon_ans, bool) or self.horizon_ans <= 0:
            raise ValueError("horizon_ans doit être un entier strictement positif.")
        if not isinstance(self.allocation_fixe, dict) or any(
                not isinstance(t, str) or isinstance(w, bool) or not isinstance(w, (int, float)) or w <= 0
                for t, w in self.allocation_fixe.items()):
            raise ValueError("allocation_fixe doit associer des tickers à des poids positifs.")
        if self.allocation_fixe and abs(sum(self.allocation_fixe.values()) - 1.0) > 1e-6:
            raise ValueError("allocation_fixe : la somme des poids doit valoir 1.")
        if self.strategie_suivie == "allocation_fixe" and not self.allocation_fixe:
            raise ValueError("strategie_suivie = allocation_fixe exige une section allocation_fixe.")
        if self.regle_krach is not None and (not isinstance(self.regle_krach, str) or not self.regle_krach.strip()):
            raise ValueError("regle_krach.texte doit être une phrase non vide.")
        if isinstance(self.seuil_krach, bool) or not isinstance(self.seuil_krach, (int, float)) \
                or not 0.0 < self.seuil_krach < 1.0:
            raise ValueError("regle_krach.seuil_baisse doit être une fraction entre 0 et 1 (ex. 0.30).")

    def to_dict(self) -> dict:
        return asdict(self)


def load_policy(path: str | Path) -> InvestmentPolicy:
    """Charge la politique ; fichier absent => politique par défaut (momentum_vt)."""
    path = Path(path)
    if not path.exists():
        return InvestmentPolicy()
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} : la politique doit être un dictionnaire YAML.")
    unknown = sorted(set(raw) - _KEYS)
    if unknown:
        raise ValueError(f"{path} : clé inconnue '{unknown[0]}' (clés attendues : {', '.join(sorted(_KEYS))}).")
    core = raw.get("coeur_satellite") or {}
    if not isinstance(core, dict) or set(core) - {"part_coeur", "satellite"}:
        raise ValueError(f"{path} : coeur_satellite accepte seulement part_coeur et satellite.")
    crash = raw.get("regle_krach") or {}
    if not isinstance(crash, dict) or set(crash) - {"texte", "seuil_baisse"}:
        raise ValueError(f"{path} : regle_krach accepte seulement texte et seuil_baisse.")
    kwargs = {k: v for k, v in raw.items() if k not in ("coeur_satellite", "regle_krach")}
    kwargs.update({k: v for k, v in core.items()})
    if "texte" in crash:
        kwargs["regle_krach"] = crash["texte"]
    if "seuil_baisse" in crash:
        kwargs["seuil_krach"] = crash["seuil_baisse"]
    if "allocation_fixe" in kwargs:
        allocation = kwargs["allocation_fixe"] or {}
        if not isinstance(allocation, dict):
            raise ValueError(f"{path} : allocation_fixe doit être un dictionnaire ticker: poids.")
        kwargs["allocation_fixe"] = {str(t): w for t, w in allocation.items()}
    try:
        return InvestmentPolicy(**kwargs)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path} : {exc}") from exc


def policy_checks(policy: InvestmentPolicy, research: dict | None, snapshot: dict | None) -> list[dict]:
    """Contrôles **informatifs** de la politique face aux preuves disponibles.

    Renvoie une liste ``{"level", "message"}`` (INFO / WARNING). Aucune
    modification automatique de la politique.
    """
    checks: list[dict] = []
    followed = policy.strategie_suivie
    rows = {row.get("key"): row for row in (research or {}).get("strategies", [])}
    row = rows.get(followed)
    if research is None:
        checks.append({"level": "INFO", "message": "Aucune étude de recherche : lance `python main.py research`."})
    elif row is None:
        checks.append({"level": "INFO", "message": f"La stratégie suivie ({followed}) n'est pas dans l'étude de "
                                                    "recherche (ex. core_satellite) : pas de comparaison statistique."})
    else:
        drawdown = row.get("max_drawdown")
        if drawdown is not None and abs(drawdown) > policy.drawdown_max_accepte:
            checks.append({"level": "WARNING", "message": f"Max drawdown historique de {followed} ({drawdown:.1%}) "
                                                          f"au-delà de la limite de la politique "
                                                          f"({-policy.drawdown_max_accepte:.0%})."})
        else:
            checks.append({"level": "INFO", "message": f"Max drawdown historique de {followed} "
                                                       f"({'n/a' if drawdown is None else f'{drawdown:.1%}'}) "
                                                       "dans la limite de la politique."})
        high = row.get("sharpe_diff_high")
        if high is not None and high < 0:
            checks.append({"level": "WARNING", "message": f"{followed} a un Sharpe significativement inférieur au "
                                                          "Buy & Hold dans l'étude (IC 90 % entièrement négatif)."})
        elif row.get("sharpe_diff") is not None and row["sharpe_diff"] < 0:
            checks.append({"level": "INFO", "message": f"{followed} a un Sharpe inférieur au Buy & Hold dans l'étude "
                                                       f"(écart {row['sharpe_diff']:+.2f}, non significatif)."})
        better = [r for r in rows.values() if r.get("sharpe_diff_low") is not None and r["sharpe_diff_low"] > 0]
        if better:
            checks.append({"level": "INFO", "message": "Stratégies significativement meilleures que le Buy & Hold : "
                                                       + ", ".join(r["label"] for r in better) + "."})
    strategy = ((snapshot or {}).get("strategies") or {}).get(followed)
    if strategy and strategy.get("current_drawdown") is not None \
            and abs(strategy["current_drawdown"]) > policy.drawdown_max_accepte:
        checks.append({"level": "WARNING", "message": f"Drawdown courant de {followed} "
                                                      f"({strategy['current_drawdown']:.1%}) au-delà de la limite."})
    return checks

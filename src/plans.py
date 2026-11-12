"""Plans d'investissement : projections, relecture historique et adéquation au profil.

Un **plan** (``config/plans.yaml``) répartit un versement mensuel entre des
**poches** (ETF à allocation fixe, stratégie du registre, fonds euros, crypto),
chacune logée dans une **enveloppe** (PEA, assurance-vie, CTO, crypto) avec sa
fiscalité. Pour un profil (``config/profil.yaml``), chaque plan est :

1. **projeté** : ``n`` trajectoires par bootstrap par blocs des rendements
   mensuels historiques (historique long en EUR, partiellement synthétique ;
   les mêmes mois sont tirés pour toutes les poches, ce qui conserve leurs
   corrélations). Frais d'ordre, frais de gestion de l'assurance-vie,
   fiscalité de sortie par enveloppe, plafond de versements du PEA (le
   surplus bascule sur un CTO) et inflation sont pris en compte ;
2. **rejoué sur le passé** : le même versement lancé à chaque mois de départ
   possible de l'historique (pire, médiane, meilleur départ) ;
3. **confronté au profil** : baisse supportable, temps disponible, horizon,
   zones, options, enveloppes ouvertes, taille des ordres.

**Scénarios de rendement explicites** (v6, ``scenarios`` de ``config/plans.yaml``) :
« historique » rejoue les rendements moyens de 2005-2026, période très
favorable aux actions ; « central » et « défavorable » gardent exactement les
mêmes chocs (volatilité, krachs, corrélations, écarts entre zones) mais
recentrent le rendement moyen des actions et des obligations sur une hypothèse
chiffrée. La crypto est recentrée sur son propre rendement supposé.

**Honnêteté du modèle** : chaque plan indique où son vrai passé tombe dans la
distribution simulée (même historique) ; un écart marqué est signalé comme une
divergence. Les seuils d'adéquation sont des conventions affichées, pas des
résultats. Rien n'est garanti : ce sont des ordres de grandeur, pas des
promesses ni des conseils. Aucun ordre.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.costs import FeeModel
from src.investor_profile import TIME_BUDGETS, ZONES, InvestorProfile, ProfileAssessment
from src.strategies import REGISTRY
from src.taxes import ENVELOPES, TaxConfig, envelope_net_values

POCKET_TYPES = ("etf", "strategie", "fonds_euros", "crypto")
PERCENTILES = (5, 10, 25, 50, 75, 90, 95)
PEA_CEILING = 150_000.0
STRATEGY_LINES = {"top3_trend": 3, "core_satellite": 2, "static_80_20": 2, "static_60_40": 2, "inverse_vol": 6}
TIME_ORDER = list(TIME_BUDGETS)
STATUS_ORDER = {"adapté": 0, "adapté avec réserves": 1, "peu adapté": 2}


@dataclass(frozen=True)
class Hypotheses:
    inflation_pct: float = 2.0
    fonds_euros_taux_pct: float = 2.5
    av_frais_gestion_uc_pct: float = 0.6
    crypto_frais_achat_pct: float = 1.0
    crypto_rendement_annuel_pct: float = 5.0
    # esperance : rendement MOYEN (arithmétique) = hypothèse ; la médiane est alors bien plus basse (volatilité
    # extrême). geometrique : rendement MÉDIAN = hypothèse ; la moyenne devient alors très élevée (optimiste).
    crypto_hypothese: str = "esperance"
    taux_retrait_pct: float = 3.5
    ajustement_prudent_pct: float = -2.0
    bloc_mois: int = 12
    simulations: int = 2000
    ordre_minimum_eur: float = 30.0
    seuil_risque_ok: float = 0.35          # P(baisse > tolérance) jusqu'à laquelle le risque est « adapté »
    seuil_risque_reserve: float = 0.65     # au-delà : « peu adapté » (conventions, pas des résultats)
    frequence_achat_mois: int = 1          # achat tous les N mois (patrimoine.yaml > profil), pour les frais fixes


@dataclass(frozen=True)
class Scenario:
    """Hypothèse de rendement : ``None`` = rendement moyen historique conservé."""

    key: str
    label: str
    actions_pct: float | None = None       # rendement annuel moyen (géométrique, EUR) visé pour le benchmark actions
    obligations_pct: float | None = None   # idem pour l'actif défensif (obligataire / monétaire)
    description: str = ""
    # "historique" : les stratégies gardent leur avance passée ; "nulle" : aucune surperformance supposée
    # (même Sharpe que le benchmark, volatilité et krachs propres conservés).
    surperformance: str = "historique"

    @property
    def is_historical(self) -> bool:
        return self.actions_pct is None and self.obligations_pct is None and self.surperformance == "historique"


HISTORICAL = Scenario("historique", "Historique")


@dataclass(frozen=True)
class Pocket:
    nom: str
    enveloppe: str
    part: float
    type: str
    allocation: dict[str, float] = field(default_factory=dict)
    strategie: str | None = None

    @property
    def risky(self) -> bool:
        return self.type != "fonds_euros"

    @property
    def lines(self) -> int:
        if self.type == "etf" or self.type == "crypto":
            return len(self.allocation)
        if self.type == "strategie":
            return STRATEGY_LINES.get(self.strategie or "", 1)
        return 1


@dataclass(frozen=True)
class PlanDef:
    id: str
    nom: str
    resume: str
    pour_qui: str
    temps: str
    complexite: int
    horizon_min_ans: int
    zones: tuple[str, ...]
    poches: tuple[Pocket, ...]
    routine: tuple[str, ...]
    necessite: tuple[str, ...] = ()
    esg: str | None = None

    @property
    def envelopes(self) -> list[str]:
        return list(dict.fromkeys(p.enveloppe for p in self.poches))

    @property
    def has_crypto(self) -> bool:
        return any(p.type == "crypto" for p in self.poches)


# --------------------------------------------------------------------------- #
# Lecture et validation
# --------------------------------------------------------------------------- #
def _pocket(raw: dict, where: str) -> Pocket:
    if not isinstance(raw, dict):
        raise ValueError(f"{where} : une poche doit être un dictionnaire.")
    unknown = set(raw) - {"nom", "enveloppe", "part", "type", "allocation", "strategie", "taux"}
    if unknown:
        raise ValueError(f"{where} : clés inconnues : {', '.join(sorted(unknown))}.")
    kind = raw.get("type")
    if kind not in POCKET_TYPES:
        raise ValueError(f"{where} : type doit valoir l'un de : {', '.join(POCKET_TYPES)}.")
    envelope = raw.get("enveloppe")
    if envelope not in ENVELOPES:
        raise ValueError(f"{where} : enveloppe doit valoir l'un de : {', '.join(ENVELOPES)}.")
    if kind == "crypto" and envelope not in ("crypto", "cto"):
        raise ValueError(f"{where} : une poche crypto va dans l'enveloppe crypto ou cto (jamais dans le PEA).")
    if kind == "fonds_euros" and envelope != "assurance_vie":
        raise ValueError(f"{where} : le fonds euros n'existe qu'en assurance-vie.")
    part = raw.get("part")
    if isinstance(part, bool) or not isinstance(part, (int, float)) or not 0 < part <= 1:
        raise ValueError(f"{where} : part doit être un nombre dans ]0 ; 1].")
    allocation = raw.get("allocation") or {}
    if kind in ("etf", "crypto"):
        if not isinstance(allocation, dict) or not allocation or \
                abs(sum(float(v) for v in allocation.values()) - 1.0) > 1e-9:
            raise ValueError(f"{where} : allocation doit être un dictionnaire de poids sommant à 1.")
    strategy = raw.get("strategie")
    if kind == "strategie" and strategy not in REGISTRY:
        raise ValueError(f"{where} : stratégie inconnue {strategy!r} (disponibles : {', '.join(REGISTRY)}).")
    return Pocket(nom=str(raw.get("nom", kind)), enveloppe=envelope, part=float(part), type=kind,
                  allocation={str(k): float(v) for k, v in allocation.items()}, strategie=strategy)


def load_plans(path: str | Path) -> tuple[Hypotheses, list[PlanDef]]:
    """Hypothèses et plans, validés (messages explicites avec le chemin)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Fichier de plans introuvable : {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    hyp_raw = raw.get("hypotheses") or {}
    unknown = set(hyp_raw) - set(Hypotheses.__dataclass_fields__)
    if unknown:
        raise ValueError(f"{path} : hypothèses inconnues : {', '.join(sorted(unknown))}.")
    hyp = Hypotheses(**hyp_raw)
    if hyp.bloc_mois < 1 or hyp.simulations < 10:
        raise ValueError(f"{path} : bloc_mois ≥ 1 et simulations ≥ 10 attendus.")
    if hyp.crypto_hypothese not in ("esperance", "geometrique"):
        raise ValueError(f"{path} : crypto_hypothese doit valoir esperance ou geometrique.")
    plans, seen = [], set()
    for i, item in enumerate(raw.get("plans") or []):
        where = f"{path} > plans[{i}]"
        if not isinstance(item, dict) or not item.get("id"):
            raise ValueError(f"{where} : id obligatoire.")
        if item["id"] in seen:
            raise ValueError(f"{where} : id en double {item['id']}.")
        seen.add(item["id"])
        pockets = tuple(_pocket(p, f"{where} > poches[{j}]") for j, p in enumerate(item.get("poches") or []))
        if not pockets or abs(sum(p.part for p in pockets) - 1.0) > 1e-9:
            raise ValueError(f"{where} : les parts des poches doivent sommer à 1.")
        if item.get("temps") not in TIME_BUDGETS:
            raise ValueError(f"{where} : temps doit valoir l'un de : {', '.join(TIME_BUDGETS)}.")
        zones = tuple(item.get("zones") or ())
        if not zones or any(z not in ZONES for z in zones):
            raise ValueError(f"{where} : zones doit être une liste parmi {', '.join(ZONES)}.")
        needs = tuple(item.get("necessite") or ())
        if any(n not in ("assurance_vie", "cto", "crypto") for n in needs):
            raise ValueError(f"{where} : necessite accepte assurance_vie, cto, crypto.")
        plans.append(PlanDef(id=str(item["id"]), nom=str(item.get("nom", item["id"])), resume=str(item.get("resume", "")),
                             pour_qui=str(item.get("pour_qui", "")), temps=item["temps"],
                             complexite=int(item.get("complexite", 1)), horizon_min_ans=int(item.get("horizon_min_ans", 1)),
                             zones=zones, poches=pockets, routine=tuple(item.get("routine") or ()), necessite=needs,
                             esg=item.get("esg")))
    if not plans:
        raise ValueError(f"{path} : aucun plan défini.")
    return hyp, plans


def load_scenarios(path: str | Path) -> tuple[dict[str, Scenario], str]:
    """Scénarios de rendement (``scenarios``) et scénario par défaut (``scenario_defaut``)."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = raw.get("scenarios") or {}
    if not isinstance(section, dict):
        raise ValueError(f"{path} : scenarios doit être un dictionnaire.")
    scenarios = {"historique": HISTORICAL}
    for key, item in section.items():
        if not isinstance(item, dict) or set(item) - {"label", "actions_pct", "obligations_pct", "description",
                                                      "surperformance"}:
            raise ValueError(f"{path} : scénario {key} invalide (label, actions_pct, obligations_pct, description, "
                             "surperformance).")
        if item.get("surperformance", "historique") not in ("historique", "nulle"):
            raise ValueError(f"{path} : {key}.surperformance doit valoir historique ou nulle.")
        for field_name in ("actions_pct", "obligations_pct"):
            value = item.get(field_name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not -10 <= value <= 20):
                raise ValueError(f"{path} : {key}.{field_name} doit être un pourcentage annuel entre -10 et 20.")
        scenarios[str(key)] = Scenario(str(key), str(item.get("label", key)), item.get("actions_pct"),
                                       item.get("obligations_pct"), str(item.get("description", "")),
                                       str(item.get("surperformance", "historique")))
    default = str(raw.get("scenario_defaut", "historique"))
    if default not in scenarios:
        raise ValueError(f"{path} : scenario_defaut {default!r} inconnu ({', '.join(scenarios)}).")
    return scenarios, default


# --------------------------------------------------------------------------- #
# Rendements des poches
# --------------------------------------------------------------------------- #
def to_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    return daily.resample("ME").last()


def recenter(returns: pd.Series, annual_return: float, mode: str = "geometrique") -> pd.Series:
    """Décale les rendements log (forme et volatilité conservées) pour que la
    moyenne géométrique (``geometrique``) ou arithmétique (``esperance``)
    annuelle vaille ``annual_return``."""
    r = returns.dropna()
    logs = np.log1p(r)
    monthly_target = np.log1p(annual_return) / 12.0
    if mode == "esperance":
        return np.expm1(logs + monthly_target - np.log(float((1.0 + r).mean())))
    if mode != "geometrique":
        raise ValueError(f"Mode de recentrage inconnu : {mode} (geometrique ou esperance).")
    return np.expm1(logs - logs.mean() + monthly_target)


@dataclass
class PlanInputs:
    """Rendements mensuels des poches : ``main`` (fenêtre commune) et ``crypto``."""

    main: pd.DataFrame
    crypto: pd.DataFrame           # rendements recentrés (projections)
    strategy_returns: dict[str, pd.Series]
    notes: list[str]
    crypto_raw: pd.DataFrame = field(default_factory=pd.DataFrame)  # vrai passé (relecture historique)
    scenario: Scenario = HISTORICAL

    @property
    def window(self) -> tuple[str, str]:
        return self.main.index.min().date().isoformat(), self.main.index.max().date().isoformat()


def pocket_key(plan: PlanDef, index: int) -> str:
    return f"{plan.id}:{index}"


def build_inputs(plans: list[PlanDef], monthly: pd.DataFrame, *, strategy_returns: dict[str, pd.Series],
                 crypto_monthly: pd.DataFrame | None, hyp: Hypotheses) -> PlanInputs:
    """Séries de rendements de chaque poche.

    ``monthly`` : prix mensuels en EUR (historique long) ; ``strategy_returns`` :
    rendements nets des stratégies du registre (frais de rotation inclus).
    """
    main, crypto, crypto_raw, notes = {}, {}, {}, []
    for plan in plans:
        for i, pocket in enumerate(plan.poches):
            key = pocket_key(plan, i)
            if pocket.type == "etf":
                missing = [t for t in pocket.allocation if t not in monthly.columns]
                if missing:
                    raise ValueError(f"Plan {plan.id} : prix introuvables pour {', '.join(missing)}.")
                rets = monthly[list(pocket.allocation)].pct_change(fill_method=None)
                weights = pd.Series(pocket.allocation)
                main[key] = rets.mul(weights, axis=1).sum(axis=1, min_count=len(weights))
            elif pocket.type == "strategie":
                if pocket.strategie not in strategy_returns:
                    raise ValueError(f"Plan {plan.id} : rendements de la stratégie {pocket.strategie} absents.")
                main[key] = strategy_returns[pocket.strategie]
            elif pocket.type == "fonds_euros":
                main[key] = pd.Series((1 + hyp.fonds_euros_taux_pct / 100) ** (1 / 12) - 1, index=monthly.index)
            else:
                if crypto_monthly is None:
                    raise ValueError(f"Plan {plan.id} : prix crypto indisponibles (data/processed/crypto_prices.csv).")
                missing = [t for t in pocket.allocation if t not in crypto_monthly.columns]
                if missing:
                    raise ValueError(f"Plan {plan.id} : prix crypto introuvables pour {', '.join(missing)}.")
                rets = crypto_monthly[list(pocket.allocation)].pct_change(fill_method=None).dropna()
                combined = rets.mul(pd.Series(pocket.allocation), axis=1).sum(axis=1)
                crypto_raw[key] = combined
                crypto[key] = recenter(combined, hyp.crypto_rendement_annuel_pct / 100, hyp.crypto_hypothese)
    frame = pd.DataFrame(main)
    start = max(frame[c].first_valid_index() for c in frame)
    end = min(frame[c].last_valid_index() for c in frame)
    frame = frame.loc[start:end]
    if frame.isna().any().any():
        frame = frame.fillna(0.0)
        notes.append("Quelques mois manquants remplacés par un rendement nul.")
    crypto_frame = pd.DataFrame(crypto).dropna() if crypto else pd.DataFrame()
    if not crypto_frame.empty:
        column = crypto_frame.columns[0]
        geo = float((1 + crypto_frame[column]).prod() ** (12 / len(crypto_frame)) - 1)
        kind = "moyen (espérance)" if hyp.crypto_hypothese == "esperance" else "médian (géométrique)"
        notes.append(f"Crypto : historique {crypto_frame.index.min():%Y-%m} → {crypto_frame.index.max():%Y-%m}, "
                     f"rendement {kind} fixé à {hyp.crypto_rendement_annuel_pct:.0f} %/an (hypothèse) ; volatilité "
                     f"et chutes historiques conservées, soit un rendement géométrique d'environ {geo:.0%}/an : "
                     "le scénario le plus probable pour la poche crypto est une forte perte ; tirages indépendants "
                     "du reste du portefeuille.")
    return PlanInputs(main=frame, crypto=crypto_frame, strategy_returns=strategy_returns, notes=notes,
                      crypto_raw=pd.DataFrame(crypto_raw).dropna() if crypto_raw else pd.DataFrame())


# --------------------------------------------------------------------------- #
# Moteur de simulation (vectorisé sur les trajectoires)
# --------------------------------------------------------------------------- #
def _block_indices(n_obs: int, n_paths: int, horizon: int, block: int, rng: np.random.Generator) -> np.ndarray:
    n_blocks = math.ceil(horizon / block)
    starts = rng.integers(0, n_obs, size=(n_paths, n_blocks))
    return ((starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_paths, -1)[:, :horizon]) % n_obs


def _pocket_paths(plan: PlanDef, inputs: PlanInputs, idx_main: np.ndarray, idx_crypto: np.ndarray | None,
                  hyp: Hypotheses, prudent: bool) -> list[np.ndarray]:
    paths = []
    adjust = (1 + hyp.ajustement_prudent_pct / 100) ** (1 / 12) if prudent else 1.0
    for i, pocket in enumerate(plan.poches):
        key = pocket_key(plan, i)
        if pocket.type == "crypto":
            assert idx_crypto is not None
            r = inputs.crypto[key].to_numpy(dtype=float)[idx_crypto]
        else:
            r = inputs.main[key].to_numpy(dtype=float)[idx_main]
        if pocket.risky and prudent:
            r = (1 + r) * adjust - 1
        if pocket.enveloppe == "assurance_vie" and pocket.type != "fonds_euros":
            r = r - hyp.av_frais_gestion_uc_pct / 100 / 12
        paths.append(r)
    return paths


def _fees(plan: PlanDef, envelope: str, amount: float, fee_model: FeeModel, hyp: Hypotheses) -> float:
    """Frais d'ordre d'un versement ``amount`` dans une enveloppe."""
    if amount <= 0:
        return 0.0
    if envelope == "assurance_vie":
        return 0.0
    pockets = [p for p in plan.poches if p.enveloppe == envelope]
    if envelope == "crypto":
        return amount * hyp.crypto_frais_achat_pct / 100
    total = sum(p.part for p in pockets)
    # Avec des frais fixes, on regroupe les petits achats : un ordre d'au moins `minimum` euros
    # (frais <= 2 % du montant, comme le plan de versement), passé une fois tous les quelques mois.
    fixed = fee_model.fixed_per_order + fee_model.minimum_per_order
    minimum = max(hyp.ordre_minimum_eur, fixed / 0.02)
    every = max(1, hyp.frequence_achat_mois)
    fee = 0.0
    for p in pockets:
        per_line = amount * p.part / total / p.lines
        order = per_line * every  # un ordre tous les `every` mois, versements cumulés
        for _ in range(p.lines):
            if order >= minimum:
                fee += fee_model.order_cost(order) / every
            else:
                fee += per_line / minimum * fee_model.order_cost(minimum)
    return fee


def _engine(plan: PlanDef, paths: list[np.ndarray], *, capital: float, monthly: float, hyp: Hypotheses,
            taxes: TaxConfig, fee_model: FeeModel, record: bool = True) -> dict:
    n, horizon = paths[0].shape
    envelopes = plan.envelopes
    env_returns: dict[str, np.ndarray] = {}
    env_share: dict[str, float] = {}
    for env in envelopes:
        members = [(p, path) for p, path in zip(plan.poches, paths, strict=True) if p.enveloppe == env]
        share = sum(p.part for p, _ in members)
        env_share[env] = share
        env_returns[env] = np.sum([(p.part / share) * path for p, path in members], axis=0)
    # Plafond du PEA : le surplus de versements bascule sur un CTO investi comme le PEA.
    overflow = "pea" in envelopes
    keys = envelopes + (["cto_surplus"] if overflow else [])
    if overflow:
        env_returns["cto_surplus"] = env_returns["pea"]
    value = {k: np.zeros(n) for k in keys}
    invested = dict.fromkeys(keys, 0.0)
    fees_total = 0.0
    pea_cum = 0.0
    total_path = np.empty((n, horizon + 1)) if record else None
    unit = np.ones(n)
    peak_unit = np.ones(n)
    worst_dd = np.zeros(n)
    peak_value = np.zeros(n)
    max_loss = np.zeros(n)
    if total_path is not None:
        total_path[:, 0] = capital
    for t in range(horizon):
        amount = capital + monthly if t == 0 else monthly
        flows = {}
        for env in envelopes:
            flow = amount * env_share[env]
            if env == "pea":
                allowed = max(0.0, min(flow, PEA_CEILING - pea_cum))
                pea_cum += allowed
                flows["cto_surplus"] = flow - allowed
                flow = allowed
            flows[env] = flow
        weights_num = np.zeros(n)
        port_ret = np.zeros(n)
        for key in keys:
            flow = flows.get(key, 0.0)
            if key == "cto_surplus":
                fee = sum(fee_model.order_cost(flow * p.part / env_share["pea"])
                          for p in plan.poches if p.enveloppe == "pea") if flow > 0 else 0.0
            else:
                fee = _fees(plan, key, flow, fee_model, hyp)
            fees_total += fee
            invested[key] += flow
            start_value = value[key] + flow - fee
            ret = env_returns[key][:, t]
            weights_num += start_value
            port_ret += start_value * ret
            value[key] = start_value * (1.0 + ret)
        total = sum(value.values())
        with np.errstate(invalid="ignore", divide="ignore"):
            r_p = np.where(weights_num > 0, port_ret / np.where(weights_num > 0, weights_num, 1.0), 0.0)
        unit *= 1.0 + r_p
        peak_unit = np.maximum(peak_unit, unit)
        worst_dd = np.minimum(worst_dd, unit / peak_unit - 1.0)
        peak_value = np.maximum(peak_value, total)
        max_loss = np.maximum(max_loss, peak_value - total)
        if total_path is not None:
            total_path[:, t + 1] = total
    years = horizon / 12.0
    net = {}
    for key in keys:
        tax_env = "cto" if key == "cto_surplus" else key
        net[key] = envelope_net_values(tax_env, value[key], invested[key], years, taxes)
    return {"gross": value, "net": net, "invested": invested, "fees_total": fees_total, "path": total_path,
            "max_drawdown": worst_dd, "max_loss_eur": max_loss, "keys": keys}


def _pct(values: np.ndarray) -> dict[str, float]:
    return {f"p{q}": float(np.percentile(values, q)) for q in PERCENTILES}


def implied_annual_return(final_value: float, capital: float, monthly: float, months: int) -> float | None:
    """Rendement annuel constant qui transforme les versements en ``final_value`` (TRI simplifié)."""
    if final_value <= 0 or months <= 0:
        return None

    def future(rate: float) -> float:
        m = (1 + rate) ** (1 / 12) - 1
        growth = (1 + m) ** months
        annuity = monthly * ((growth - 1) / m * (1 + m)) if abs(m) > 1e-12 else monthly * months
        return capital * growth + annuity

    low, high = -0.99, 1.0
    for _ in range(200):
        mid = (low + high) / 2
        if future(mid) < final_value:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def simulate_plan(plan: PlanDef, inputs: PlanInputs, *, capital: float, monthly: float, horizon_years: int,
                  hyp: Hypotheses, taxes: TaxConfig, fee_model: FeeModel, n_sims: int | None = None, seed: int = 42,
                  prudent: bool = False, goal_real: float | None = None, drawdown_tolerance: float | None = None) -> dict:
    """Projection par bootstrap par blocs (voir la docstring du module)."""
    horizon = int(horizon_years * 12)
    n = n_sims or hyp.simulations
    rng = np.random.default_rng(seed)
    idx_main = _block_indices(len(inputs.main), n, horizon, hyp.bloc_mois, rng)
    idx_crypto = _block_indices(len(inputs.crypto), n, horizon, hyp.bloc_mois, rng) if plan.has_crypto else None
    out = _engine(plan, _pocket_paths(plan, inputs, idx_main, idx_crypto, hyp, prudent), capital=capital,
                  monthly=monthly, hyp=hyp, taxes=taxes, fee_model=fee_model)
    deflator_month = (1 + hyp.inflation_pct / 100) ** (np.arange(horizon + 1) / 12.0)
    path = out["path"]
    real_path = path / deflator_month
    year_idx = np.arange(0, horizon + 1, 12)
    if year_idx[-1] != horizon:
        year_idx = np.append(year_idx, horizon)
    contributed = capital + monthly * np.arange(horizon + 1)
    # Versements en euros d'aujourd'hui : chaque versement ramené à la date où il est fait.
    flows = np.full(horizon, float(monthly))
    flows[0] += capital
    contributed_real = np.concatenate([[capital], np.cumsum(flows / deflator_month[:-1])])
    gross = sum(out["gross"].values())
    net = sum(out["net"].values())
    deflator = deflator_month[-1]
    net_real = net / deflator
    total_in = capital + monthly * horizon
    fan = {"months": year_idx.tolist(), "contributed": contributed[year_idx].tolist(),
           "contributed_real": contributed_real[year_idx].tolist(),
           "nominal": {f"p{q}": np.percentile(path[:, year_idx], q, axis=0).tolist() for q in PERCENTILES},
           "real": {f"p{q}": np.percentile(real_path[:, year_idx], q, axis=0).tolist() for q in PERCENTILES}}
    result = {
        "plan": plan.id, "nom": plan.nom, "horizon_years": horizon_years, "capital": capital, "monthly": monthly,
        "contributed": total_in, "contributed_real": float(contributed_real[-1]), "n_sims": n, "prudent": prudent, "fan": fan,
        "final": {"gross": _pct(gross), "net": _pct(net), "net_real": _pct(net_real),
                  "income_real_monthly": _pct(net_real * hyp.taux_retrait_pct / 100 / 12)},
        "prob_loss": float((net < total_in).mean()),
        "prob_real_loss": float((net_real < contributed_real[-1]).mean()),
        "drawdown": {**_pct(out["max_drawdown"]),
                     "prob_beyond_tolerance": None if drawdown_tolerance is None else
                     float((out["max_drawdown"] < -drawdown_tolerance).mean())},
        "max_loss_eur": _pct(out["max_loss_eur"]),
        "fees_total": out["fees_total"],
        "by_envelope": {k: {"invested": out["invested"][k], "median_net": float(np.median(out["net"][k]))}
                        for k in out["keys"] if out["invested"][k] > 0},
        "implied_return_median": implied_annual_return(float(np.median(gross)), capital, monthly, horizon),
        "goal_real": goal_real, "prob_goal": None, "goal_curve": None,
    }
    if goal_real:
        result["prob_goal"] = float((net_real >= goal_real).mean())
        result["goal_curve"] = [float((real_path[:, m] >= goal_real).mean()) for m in year_idx]
    return result


def _history_inputs(plan: PlanDef, inputs: PlanInputs) -> PlanInputs:
    """Rendements historiques alignés sur les mêmes dates ; la crypto garde son vrai
    passé (pas de recentrage) pour la relecture historique."""
    main = inputs.main
    if not plan.has_crypto:
        return PlanInputs(main=main, crypto=inputs.crypto, strategy_returns=inputs.strategy_returns, notes=[])
    common = main.index.intersection(inputs.crypto_raw.index)
    return PlanInputs(main=main.loc[common], crypto=inputs.crypto_raw.loc[common],
                      strategy_returns=inputs.strategy_returns, notes=[])


def historical_windows(plan: PlanDef, inputs: PlanInputs, *, capital: float, monthly: float, horizon_years: int,
                       hyp: Hypotheses, taxes: TaxConfig, fee_model: FeeModel) -> dict:
    """Le plan lancé à chaque mois de départ possible de l'historique (fenêtres complètes)."""
    horizon = int(horizon_years * 12)
    sub = _history_inputs(plan, inputs)
    main = sub.main
    n_windows = len(main) - horizon + 1
    if n_windows < 1:
        return {"available": False, "reason": f"horizon de {horizon_years} ans plus long que l'historique disponible "
                                              f"({len(main) // 12} ans)."}
    idx = np.arange(n_windows)[:, None] + np.arange(horizon)[None, :]
    out = _engine(plan, _pocket_paths(plan, sub, idx, idx if plan.has_crypto else None, hyp, False),
                  capital=capital, monthly=monthly, hyp=hyp, taxes=taxes, fee_model=fee_model, record=False)
    net_real = sum(out["net"].values()) / (1 + hyp.inflation_pct / 100) ** (horizon / 12)
    starts = main.index[:n_windows]
    worst, best = int(np.argmin(net_real)), int(np.argmax(net_real))
    return {"available": True, "n_windows": n_windows, "first_start": starts[0].date().isoformat(),
            "last_start": starts[-1].date().isoformat(),
            "net_real": {"min": float(net_real.min()), "median": float(np.median(net_real)),
                         "max": float(net_real.max())},
            "worst_start": starts[worst].date().isoformat(), "best_start": starts[best].date().isoformat(),
            "worst_drawdown": float(out["max_drawdown"].min())}


def replay(plan: PlanDef, inputs: PlanInputs, *, capital: float, monthly: float, horizon_years: int,
           hyp: Hypotheses, taxes: TaxConfig, fee_model: FeeModel) -> pd.DataFrame:
    """Une trajectoire réelle : le plan lancé au début de l'historique disponible."""
    sub = _history_inputs(plan, inputs)
    main = sub.main
    horizon = min(int(horizon_years * 12), len(main))
    idx = np.arange(horizon)[None, :]
    out = _engine(plan, _pocket_paths(plan, sub, idx, idx if plan.has_crypto else None, hyp, False),
                  capital=capital, monthly=monthly, hyp=hyp, taxes=taxes, fee_model=fee_model)
    dates = main.index[:horizon]
    return pd.DataFrame({"valeur": out["path"][0, 1:], "versé": capital + monthly * np.arange(1, horizon + 1)},
                        index=dates)


# --------------------------------------------------------------------------- #
# Adéquation au profil
# --------------------------------------------------------------------------- #
def evaluate_fit(plan: PlanDef, result: dict, profile: InvestorProfile, assessment: ProfileAssessment,
                 hyp: Hypotheses) -> dict:
    """Compare un plan simulé aux préférences déclarées (repères, pas un conseil)."""
    checks: list[tuple[str, str]] = []  # (niveau, message) niveau = ok | reserve | ko
    prob = result["drawdown"]["prob_beyond_tolerance"]
    median_dd = result["drawdown"]["p50"]
    tol = assessment.drawdown_tolerance
    if prob is not None:
        level = "ok" if prob <= hyp.seuil_risque_ok else "reserve" if prob <= hyp.seuil_risque_reserve else "ko"
        checks.append((level, f"Risque de dépasser ta baisse supportable ({tol:.0%}) sur l'horizon : {prob:.0%} "
                              f"(pire baisse médiane {median_dd:.0%})."))
    if plan.complexite <= assessment.max_complexity:
        checks.append(("ok", f"Complexité {plan.complexite}/4 compatible avec ton temps disponible."))
    elif plan.complexite == assessment.max_complexity + 1:
        checks.append(("reserve", f"Complexité {plan.complexite}/4 un peu au-delà de ton temps disponible."))
    else:
        checks.append(("ko", f"Complexité {plan.complexite}/4 trop élevée pour ton temps disponible."))
    if profile.experience == "debutant" and plan.complexite >= 3:
        checks.append(("reserve", "Stratégie active : la pratiquer d'abord en paper trading (6 mois au moins)."))
    if profile.horizon_ans < plan.horizon_min_ans:
        checks.append(("ko", f"Horizon de {profile.horizon_ans} ans inférieur au minimum du plan "
                             f"({plan.horizon_min_ans} ans)."))
    extra = [z for z in plan.zones if z not in profile.zones]
    if not set(plan.zones) & set(profile.zones):
        checks.append(("ko", "Aucune des zones du plan ne fait partie de tes préférences."))
    elif extra and len(plan.zones) < len(ZONES):
        checks.append(("reserve", f"Inclut des zones non choisies : {', '.join(ZONES[z] for z in extra)}."))
    missing_zones = [z for z in profile.zones if z not in plan.zones]
    if missing_zones and len(plan.zones) < len(ZONES):
        checks.append(("ok", f"N'inclut pas : {', '.join(ZONES[z] for z in missing_zones)}."))
    if "crypto" in plan.necessite and not profile.options.crypto:
        checks.append(("ko", "Contient de la crypto, que tu n'as pas retenue."))
    elif "crypto" in plan.necessite:
        share = sum(p.part for p in plan.poches if p.type == "crypto")
        if share * 100 > profile.options.part_crypto_max_pct + 1e-9:
            checks.append(("ko", f"Poche crypto de {share:.0%} au-delà de ton plafond "
                                 f"({profile.options.part_crypto_max_pct:.0f} %)."))
        checks.append(("reserve", "Nécessite un compte sur une plateforme crypto agréée (PSAN/CASP) ou un ETN sur CTO."))
    if "assurance_vie" in plan.necessite and not profile.envelope_open("assurance_vie"):
        checks.append(("reserve", "Nécessite d'ouvrir une assurance-vie (contrat en ligne sans frais d'entrée)."))
    for pocket in plan.poches:
        per_line = profile.versement_mensuel_eur * pocket.part / max(pocket.lines, 1)
        if pocket.type != "fonds_euros" and 0 < per_line < hyp.ordre_minimum_eur:
            every = math.ceil(hyp.ordre_minimum_eur / per_line)
            checks.append(("reserve", f"{pocket.nom} : {per_line:.0f} € par ligne et par mois, regrouper les achats "
                                      f"tous les {every} mois."))
    if not profile.epargne_precaution_ok:
        checks.append(("reserve", "Constituer d'abord l'épargne de précaution."))
    if profile.options.esg and plan.esg:
        checks.append(("ok", plan.esg))
    levels = [level for level, _ in checks]
    status = "peu adapté" if "ko" in levels else "adapté avec réserves" if "reserve" in levels else "adapté"
    return {"status": status, "checks": [{"niveau": lvl, "message": msg} for lvl, msg in checks]}


# --------------------------------------------------------------------------- #
# Étude complète
# --------------------------------------------------------------------------- #
def model_check(sim_reference: dict, historical: dict, horizon_years: int, n_months: int) -> dict:
    """Où tombe la médiane du vrai passé dans la distribution simulée sur le même historique ?

    Entre le 25e et le 75e centile : cohérent. En dehors : divergent (la simulation,
    qui mélange les années, et la succession réelle des années racontent deux
    histoires différentes). Le vrai passé ne contient qu'environ ``n_months /
    horizon`` périodes indépendantes : aucune des deux mesures n'est une preuve.
    """
    independent = n_months / (horizon_years * 12)
    if not historical.get("available"):
        return {"status": "indisponible", "percentile": None, "independent_periods": independent,
                "text": "Vrai passé trop court pour cet horizon : seul le modèle est disponible."}
    net = sim_reference["final"]["net_real"]
    qs = [5, 10, 25, 50, 75, 90, 95]
    values = [net[f"p{q}"] for q in qs]
    median = historical["net_real"]["median"]
    percentile = float(np.interp(median, values, [q / 100 for q in qs]))
    if median < values[0]:
        percentile = 0.0
    elif median > values[-1]:
        percentile = 1.0
    status = "cohérent" if 0.25 <= percentile <= 0.75 else "divergent"
    where = ("sous le 5e centile" if percentile == 0.0 else "au-dessus du 95e centile" if percentile == 1.0
             else f"au {percentile:.0%} de la distribution")
    text = (f"Médiane du vrai passé {where} simulée sur le même historique ; environ {independent:.1f} période(s) "
            f"indépendante(s) de {horizon_years} ans dans les données.")
    if status == "divergent":
        text += " Modèle et vrai passé divergent : l'ordre des années compte beaucoup pour ce plan."
    return {"status": status, "percentile": percentile, "independent_periods": independent, "text": text}


def run_plans(plans: list[PlanDef], inputs: PlanInputs, profile: InvestorProfile, assessment: ProfileAssessment, *,
              hyp: Hypotheses, taxes: TaxConfig, fee_model: FeeModel, n_sims: int | None = None,
              prudent: bool = False, seed: int = 42, reference_inputs: PlanInputs | None = None,
              scenario_inputs: dict[str, PlanInputs] | None = None) -> dict:
    """Projection, relecture historique et adéquation de chaque plan pour le profil.

    ``inputs`` : rendements du scénario choisi. ``reference_inputs`` : scénario
    historique, pour le contrôle modèle / vrai passé (défaut : ``inputs`` s'il
    est historique). ``scenario_inputs`` : tous les scénarios, pour la table de
    sensibilité.
    """
    kwargs: dict[str, Any] = {"capital": profile.capital_initial_eur, "monthly": profile.versement_mensuel_eur,
              "horizon_years": profile.horizon_ans, "hyp": hyp, "taxes": taxes, "fee_model": fee_model}
    results = {}
    for plan in plans:
        sim = simulate_plan(plan, inputs, **kwargs, n_sims=n_sims, seed=seed, prudent=prudent,
                            goal_real=profile.objectif_capital_eur, drawdown_tolerance=assessment.drawdown_tolerance)
        reference = reference_inputs if reference_inputs is not None else \
            (inputs if inputs.scenario.is_historical else None)
        base = reference if reference is not None else inputs
        historical = historical_windows(plan, base, **kwargs)
        check = None
        if reference is not None:
            sim_ref = sim if reference is inputs else simulate_plan(plan, reference, **kwargs,
                                                                   n_sims=min(n_sims or hyp.simulations, 1000),
                                                                   seed=seed)
            check = model_check(sim_ref, historical, profile.horizon_ans, len(reference.main))
        results[plan.id] = {
            "plan": plan, "simulation": sim, "historical": historical, "model_check": check,
            "replay": replay(plan, base, **kwargs), "fit": evaluate_fit(plan, sim, profile, assessment, hyp),
        }
    sensitivity: dict[str, dict[str, dict]] | None = None
    if scenario_inputs:
        sensitivity = {plan.id: {} for plan in plans}
        for key, scenario_input in scenario_inputs.items():
            for plan in plans:
                final = simulate_plan(plan, scenario_input, **kwargs, n_sims=min(n_sims or hyp.simulations, 500),
                                      seed=seed)["final"]["net_real"]
                sensitivity[plan.id][key] = {"label": scenario_input.scenario.label, "p10": final["p10"],
                                             "p50": final["p50"], "p90": final["p90"]}
    ranking = sorted(results, key=lambda k: (STATUS_ORDER[results[k]["fit"]["status"]],
                                             -results[k]["simulation"]["final"]["net_real"]["p50"]))
    return {"window": inputs.window, "notes": inputs.notes, "profile": profile, "assessment": assessment,
            "hypotheses": hyp, "prudent": prudent, "results": results, "ranking": ranking,
            "scenario": inputs.scenario, "sensitivity": sensitivity}


def strategy_net_returns(names: set[str], monthly: pd.DataFrame, ctx, transaction_cost: float) -> dict[str, pd.Series]:
    """Rendements nets (frais de rotation inclus) des stratégies du registre utilisées par les plans."""
    from src.engine import run_strategies

    return {name: run.returns for name, run in run_strategies(monthly, ctx, cost=transaction_cost,
                                                               names=sorted(names)).items()}


def shift_prices(prices: pd.DataFrame, roles: dict[str, str], *, benchmark: str, scenario: Scenario,
                 window_start: pd.Timestamp | None = None) -> pd.DataFrame:
    """Prix aux mêmes chocs mais au rendement moyen du scénario.

    Le rendement log mensuel de chaque action est décalé d'une même constante,
    choisie pour que le benchmark ait en moyenne (géométrique, sur la fenêtre
    des plans) le rendement annuel ``actions_pct`` : les écarts historiques
    entre zones et toute la volatilité sont conservés. Les actifs défensifs
    sont recentrés individuellement sur ``obligations_pct``. Monétaire inchangé.
    """
    if scenario.is_historical:
        return prices
    logs = np.log1p(prices.pct_change(fill_method=None))
    window = logs.loc[window_start:] if window_start is not None else logs
    shifts: dict[str, float] = {}
    if scenario.actions_pct is not None:
        delta = np.log1p(scenario.actions_pct / 100) / 12 - float(window[benchmark].mean())
        shifts.update({c: delta for c in prices.columns if roles.get(c, "candidate") == "candidate"})
    if scenario.obligations_pct is not None:
        shifts.update({c: np.log1p(scenario.obligations_pct / 100) / 12 - float(window[c].mean())
                       for c in prices.columns if roles.get(c) == "defensive" and window[c].notna().any()})
    out = {}
    for column in prices.columns:
        series = prices[column]
        if column not in shifts or series.dropna().empty:
            out[column] = series
            continue
        first = series.first_valid_index()
        shifted = (logs[column] + shifts[column]).loc[first:].fillna(0.0).cumsum()
        rebuilt = series.loc[first] * np.exp(shifted)
        out[column] = rebuilt.where(series.loc[first:].notna()).reindex(series.index)
    return pd.DataFrame(out, index=prices.index)


def remove_alpha(returns: pd.Series, benchmark: pd.Series) -> pd.Series:
    """Recentre une stratégie sur le Sharpe du benchmark (aucune surperformance supposée).

    Rendement log moyen visé = moyenne du benchmark × (volatilité de la stratégie
    / volatilité du benchmark) : une stratégie moins risquée rapporte moins, sans
    avance propre. La forme des rendements (krachs, volatilité) est conservée.
    """
    joined = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    if len(joined) < 24:
        return returns
    logs = np.log1p(joined)
    vol_b = float(logs.iloc[:, 1].std())
    if vol_b <= 0:
        return returns
    target = float(logs.iloc[:, 1].mean()) * float(logs.iloc[:, 0].std()) / vol_b
    shift = target - float(logs.iloc[:, 0].mean())
    return np.expm1(np.log1p(returns) + shift)


def prepare_inputs(plans: list[PlanDef], hyp: Hypotheses, *, long_prices: pd.DataFrame, roles: dict[str, str],
                   long_config: dict, config, policy, crypto_daily: pd.DataFrame | None,
                   scenario: Scenario = HISTORICAL) -> PlanInputs:
    """Rendements des poches à partir des fichiers du projet (historique long, crypto), pour un scénario."""

    from src.cli.common import _long_universe, _strategy_context

    monthly = _long_universe(long_prices, roles, long_config)
    etf_tickers = {t for plan in plans for p in plan.poches if p.type == "etf" for t in p.allocation}
    extra = [t for t in etf_tickers if t not in monthly.columns and t in long_prices.columns]
    names = {p.strategie for plan in plans for p in plan.poches if p.type == "strategie" and p.strategie}
    crypto_monthly = to_monthly(crypto_daily) if crypto_daily is not None else None

    def build(universe: pd.DataFrame) -> PlanInputs:
        prices = universe.join(long_prices[extra]) if extra else universe
        ctx = _strategy_context(config, roles, universe.columns, policy)
        returns = strategy_net_returns(names, universe, ctx, config.backtest.transaction_cost)
        return build_inputs(plans, prices, strategy_returns=returns, crypto_monthly=crypto_monthly, hyp=hyp)

    base = build(monthly)
    if scenario.is_historical:
        base.scenario = scenario
        return base
    # Même fenêtre que les plans : le rendement visé l'est sur les mois effectivement tirés.
    shifted = shift_prices(monthly, roles, benchmark=config.benchmark_ticker, scenario=scenario,
                           window_start=base.main.index.min())
    inputs = build(shifted)
    inputs.scenario = scenario
    if scenario.surperformance == "nulle":
        benchmark = shifted[config.benchmark_ticker].pct_change(fill_method=None).reindex(inputs.main.index)
        for plan in plans:
            for i, pocket in enumerate(plan.poches):
                if pocket.type == "strategie" and pocket.strategie != "benchmark":
                    key = pocket_key(plan, i)
                    inputs.main[key] = remove_alpha(inputs.main[key], benchmark)
        inputs.notes.append("Stratégies actives sans surperformance supposée (même Sharpe que le Buy & Hold) : "
                            "l'étude de robustesse ne démontre aucune avance.")
    inputs.notes.append(f"Scénario « {scenario.label} » : actions recentrées sur "
                        + ("leur moyenne historique" if scenario.actions_pct is None else f"{scenario.actions_pct:.1f} %/an")
                        + ", défensif sur "
                        + ("sa moyenne historique" if scenario.obligations_pct is None
                           else f"{scenario.obligations_pct:.1f} %/an")
                        + " (mêmes chocs que l'historique).")
    return inputs

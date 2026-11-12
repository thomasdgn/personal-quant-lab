"""Profil investisseur : questionnaire, validation et lecture du profil.

Le profil décrit la situation et les préférences déclarées (capital, versement,
objectif, horizon, réaction à une baisse, temps disponible, zones, options,
expérience, enveloppes ouvertes). Il est **personnel** : ``config/profil.yaml``
est ignoré par Git ; ``config/profil.example.yaml`` sert de modèle.

``assess_profile`` en déduit des repères **indicatifs** (baisse supportable,
classe de risque, complexité acceptable, remarques de budget). Ce ne sont pas
des conseils : ces repères servent seulement à confronter les plans
d'investissement simulés (``src/plans.py``) aux préférences déclarées. Le
laboratoire ne passe aucun ordre et ne modifie jamais la politique suivie.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

OBJECTIVES = {
    "retraite": "Retraite / long terme (20 ans et plus)",
    "independance": "Indépendance financière (10 à 20 ans)",
    "projet": "Projet (achat immobilier…) sous 5 à 10 ans",
    "mixte": "Mixte : un projet à moyen terme et une poche long terme",
}
REACTIONS = {
    "acheter_plus": "J'achète plus",
    "ne_rien_faire": "Je ne touche à rien",
    "reduire": "Je réduis une partie",
    "tout_vendre": "Je vends tout",
}
TIME_BUDGETS = {
    "5min": "5 à 10 minutes par mois",
    "30min": "Environ 30 minutes par mois",
    "1-2h": "1 à 2 heures par mois",
    "hobby": "Plus : c'est un loisir",
}
ZONES = {"monde": "Monde (diversifié)", "europe": "Europe", "us": "États-Unis / tech", "emergents": "Émergents / Asie"}
EXPERIENCES = {"debutant": "Débutant", "intermediaire": "Intermédiaire", "avance": "Avancé"}
ENVELOPE_LABELS = {"pea": "PEA", "assurance_vie": "Assurance-vie", "cto": "Compte-titres (CTO)"}

# Baisse maximale supportable (depuis un plus haut) selon la réaction déclarée.
DRAWDOWN_BY_REACTION = {"tout_vendre": 0.15, "reduire": 0.25, "ne_rien_faire": 0.35, "acheter_plus": 0.45}
# Complexité maximale d'un plan (1 = passif, 4 = actif et suivi) selon le temps disponible.
COMPLEXITY_BY_TIME = {"5min": 1, "30min": 2, "1-2h": 3, "hobby": 4}
RISK_CLASSES = ("Prudent", "Équilibré", "Dynamique", "Offensif")
BEGINNER_MARGIN = 0.05

# Questionnaire commun au tableau de bord et à la CLI (``main.py profile --questionnaire``).
QUESTIONS: tuple[dict, ...] = (
    {"key": "capital_initial_eur", "kind": "amount",
     "question": "Quelle somme de départ peux-tu investir (hors épargne de précaution) ?"},
    {"key": "versement_mensuel_eur", "kind": "amount",
     "question": "Combien veux-tu verser chaque mois, toutes enveloppes confondues ?"},
    {"key": "objectif", "kind": "choice", "options": OBJECTIVES,
     "question": "Quel est ton objectif principal ?"},
    {"key": "horizon_ans", "kind": "years", "question": "Dans combien d'années auras-tu besoin de cet argent ?"},
    {"key": "objectif_capital_eur", "kind": "amount_optional",
     "question": "Capital visé à l'horizon, en euros d'aujourd'hui (vide = pas de cible) ?"},
    {"key": "reaction_baisse", "kind": "choice", "options": REACTIONS,
     "question": "Ton portefeuille perd 30 % en quelques mois (2008, mars 2020). Que fais-tu ?"},
    {"key": "temps_mensuel", "kind": "choice", "options": TIME_BUDGETS,
     "question": "Combien de temps veux-tu y consacrer chaque mois ?"},
    {"key": "zones", "kind": "multi", "options": ZONES, "question": "Quelles zones veux-tu privilégier ?"},
    {"key": "experience", "kind": "choice", "options": EXPERIENCES, "question": "Quelle est ton expérience ?"},
)


@dataclass(frozen=True)
class Options:
    crypto: bool = False
    part_crypto_max_pct: float = 5.0
    esg: bool = False
    securite: bool = False  # poche obligataire / fonds euros souhaitée


@dataclass(frozen=True)
class InvestorProfile:
    capital_initial_eur: float = 0.0
    versement_mensuel_eur: float = 200.0
    objectif: str = "retraite"
    horizon_ans: int = 20
    objectif_capital_eur: float | None = None
    reaction_baisse: str = "ne_rien_faire"
    temps_mensuel: str = "30min"
    zones: tuple[str, ...] = ("monde",)
    options: Options = field(default_factory=Options)
    experience: str = "debutant"
    enveloppes: dict = field(default_factory=lambda: {"pea": {"ouvert": True, "date_ouverture": None},
                                                      "assurance_vie": {"ouvert": False}, "cto": {"ouvert": False}})
    epargne_precaution_ok: bool = True

    def envelope_open(self, envelope: str) -> bool:
        return bool((self.enveloppes.get(envelope) or {}).get("ouvert"))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["zones"] = list(self.zones)
        return data


def _number(raw: dict, key: str, path: str, *, minimum: float = 0.0, optional: bool = False) -> float | None:
    value = raw.get(key)
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ValueError(f"{path} : {key} doit être un nombre supérieur ou égal à {minimum:g}.")
    return float(value)


def _choice(raw: dict, key: str, allowed: dict, path: str) -> str:
    value = raw.get(key)
    if value not in allowed:
        raise ValueError(f"{path} : {key} doit valoir l'un de : {', '.join(allowed)} (reçu : {value!r}).")
    return str(value)


def profile_from_dict(raw: dict, path: str = "profil") -> InvestorProfile:
    """Valide un dictionnaire de profil (messages d'erreur explicites)."""
    if not isinstance(raw, dict):
        raise ValueError(f"{path} : le profil doit être un dictionnaire YAML.")
    known = {f for f in InvestorProfile.__dataclass_fields__}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{path} : clés inconnues : {', '.join(sorted(unknown))}.")
    horizon = _number(raw, "horizon_ans", path, minimum=1)
    zones = raw.get("zones", ["monde"])
    if not isinstance(zones, list) or not zones or any(z not in ZONES for z in zones):
        raise ValueError(f"{path} : zones doit être une liste non vide parmi {', '.join(ZONES)}.")
    options_raw = raw.get("options") or {}
    if not isinstance(options_raw, dict) or set(options_raw) - set(Options.__dataclass_fields__):
        raise ValueError(f"{path} : options accepte seulement {', '.join(Options.__dataclass_fields__)}.")
    for key in ("crypto", "esg", "securite"):
        if key in options_raw and not isinstance(options_raw[key], bool):
            raise ValueError(f"{path} : options.{key} doit être true ou false.")
    crypto_max = options_raw.get("part_crypto_max_pct", 5.0)
    if isinstance(crypto_max, bool) or not isinstance(crypto_max, (int, float)) or not 0 <= crypto_max <= 20:
        raise ValueError(f"{path} : options.part_crypto_max_pct doit être entre 0 et 20.")
    envelopes = raw.get("enveloppes") or InvestorProfile().enveloppes
    if not isinstance(envelopes, dict) or set(envelopes) - set(ENVELOPE_LABELS):
        raise ValueError(f"{path} : enveloppes accepte seulement {', '.join(ENVELOPE_LABELS)}.")
    for name, item in envelopes.items():
        if not isinstance(item, dict) or not isinstance(item.get("ouvert"), bool):
            raise ValueError(f"{path} : enveloppes.{name}.ouvert doit être true ou false.")
    precaution = raw.get("epargne_precaution_ok", True)
    if not isinstance(precaution, bool):
        raise ValueError(f"{path} : epargne_precaution_ok doit être true ou false.")
    return InvestorProfile(
        capital_initial_eur=_number(raw, "capital_initial_eur", path) or 0.0,
        versement_mensuel_eur=_number(raw, "versement_mensuel_eur", path) or 0.0,
        objectif=_choice(raw, "objectif", OBJECTIVES, path),
        horizon_ans=int(horizon or 1),
        objectif_capital_eur=_number(raw, "objectif_capital_eur", path, optional=True),
        reaction_baisse=_choice(raw, "reaction_baisse", REACTIONS, path),
        temps_mensuel=_choice(raw, "temps_mensuel", TIME_BUDGETS, path),
        zones=tuple(zones),
        options=Options(crypto=bool(options_raw.get("crypto", False)), part_crypto_max_pct=float(crypto_max),
                        esg=bool(options_raw.get("esg", False)), securite=bool(options_raw.get("securite", False))),
        experience=_choice(raw, "experience", EXPERIENCES, path),
        enveloppes=envelopes,
        epargne_precaution_ok=precaution,
    )


def load_profile(path: str | Path) -> InvestorProfile | None:
    """Profil personnel ; ``None`` si le fichier n'existe pas encore."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{path} : YAML invalide ({exc}).") from exc
    return profile_from_dict(raw, str(path))


HEADER = ("# Profil investisseur — PERSONNEL (ce fichier est ignoré par Git).\n"
          "# Modifiable à la main, via `python main.py profile --questionnaire` ou la page Profil du tableau de bord.\n"
          "# Sert uniquement à confronter les plans simulés à tes préférences : aucun ordre, aucun conseil.\n")


def save_profile(profile: InvestorProfile, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(profile.to_dict(), allow_unicode=True, sort_keys=False)
    path.write_text(HEADER + body, encoding="utf-8", newline="\n")
    return path


@dataclass(frozen=True)
class ProfileAssessment:
    drawdown_tolerance: float          # baisse supportable retenue (marge débutant incluse)
    declared_drawdown: float           # baisse supportable déclarée
    risk_class: str
    max_complexity: int
    horizon_class: str                 # court / moyen / long
    max_equity_share: float            # repère de part actions selon l'horizon
    notes: tuple[str, ...]


def assess_profile(profile: InvestorProfile) -> ProfileAssessment:
    """Repères indicatifs déduits du profil (pas un conseil en investissement)."""
    declared = DRAWDOWN_BY_REACTION[profile.reaction_baisse]
    notes: list[str] = []
    tolerance = declared
    if profile.experience == "debutant" and profile.reaction_baisse in ("acheter_plus", "ne_rien_faire"):
        tolerance = declared - BEGINNER_MARGIN
        notes.append(f"Tolérance déclarée ({declared:.0%}) jamais éprouvée sur un vrai krach : le laboratoire retient "
                     f"{tolerance:.0%} par prudence. Ce repère s'ajustera avec l'expérience.")
    if profile.horizon_ans < 5:
        horizon_class, equity = "court", 0.3
        notes.append("Horizon court : une forte part d'actions peut ne pas avoir le temps de se remettre d'une crise.")
    elif profile.horizon_ans < 10:
        horizon_class, equity = "moyen", 0.7
    else:
        horizon_class, equity = "long", 1.0
    reaction_score = {"tout_vendre": 0, "reduire": 1, "ne_rien_faire": 2, "acheter_plus": 3}[profile.reaction_baisse]
    horizon_score = {"court": 0, "moyen": 1, "long": 2}[horizon_class]
    experience_score = {"debutant": 0, "intermediaire": 1, "avance": 1}[profile.experience]
    score = reaction_score + horizon_score + experience_score
    risk_class = RISK_CLASSES[min(3, score * 4 // 7)]
    complexity = COMPLEXITY_BY_TIME[profile.temps_mensuel]
    if profile.experience == "debutant" and complexity > 3:
        notes.append("Beaucoup de temps disponible mais débutant : un plan simple d'abord, la partie active en "
                     "paper trading tant que ses règles ne sont pas maîtrisées.")
    budget = profile.versement_mensuel_eur
    if budget < 200:
        notes.append(f"Petit versement ({budget:.0f} €/mois) : 1 à 2 lignes au plus par mois, ETF à petite part "
                     "(WPEA.PA plutôt que CW8.PA), courtier sans frais fixes ; regrouper les petites lignes "
                     "(ex. un achat trimestriel).")
    if not profile.epargne_precaution_ok:
        notes.append("Épargne de précaution à constituer d'abord (3 à 6 mois de dépenses sur livrets).")
    if profile.options.crypto:
        notes.append(f"Crypto : poche plafonnée à {profile.options.part_crypto_max_pct:.0f} % ; hors PEA (plateforme "
                     "agréée ou ETN sur CTO), imposée à 31,4 % sur la plus-value ; perte totale possible.")
    if profile.options.esg:
        notes.append("ESG : l'univers suivi contient peu d'ETF ISR éligibles au PEA ; les plans utilisent les ETF "
                     "de l'univers et signalent l'équivalent ISR à vérifier chez l'émetteur.")
    if profile.objectif == "projet" and horizon_class != "long":
        notes.append("Objectif projet : réduire progressivement le risque dans les 3 dernières années.")
    if not profile.envelope_open("pea"):
        notes.append("PEA non ouvert : l'ouvrir tôt (même avec un petit montant) lance le compteur fiscal des 5 ans.")
    return ProfileAssessment(drawdown_tolerance=tolerance, declared_drawdown=declared, risk_class=risk_class,
                             max_complexity=complexity, horizon_class=horizon_class, max_equity_share=equity,
                             notes=tuple(notes))


def profile_lines(profile: InvestorProfile, assessment: ProfileAssessment) -> list[str]:
    """Résumé lisible (CLI, rapports)."""
    envelopes = ", ".join(f"{ENVELOPE_LABELS[k]} {'ouvert' if v.get('ouvert') else 'non ouvert'}"
                          for k, v in profile.enveloppes.items())
    target = "aucun" if profile.objectif_capital_eur is None else f"{profile.objectif_capital_eur:,.0f} €".replace(",", " ")
    options = [name for name, on in (("crypto", profile.options.crypto), ("ESG", profile.options.esg),
                                     ("poche sécurisée", profile.options.securite)) if on]
    return [
        f"Capital de départ {profile.capital_initial_eur:,.0f} € · versement {profile.versement_mensuel_eur:,.0f} €/mois"
        .replace(",", " "),
        f"Objectif : {OBJECTIVES[profile.objectif]} · horizon {profile.horizon_ans} ans · capital visé {target}",
        f"Face à une baisse de 30 % : {REACTIONS[profile.reaction_baisse]} · temps : {TIME_BUDGETS[profile.temps_mensuel]}",
        f"Zones : {', '.join(ZONES[z] for z in profile.zones)} · options : {', '.join(options) or 'aucune'} · "
        f"expérience : {EXPERIENCES[profile.experience]}",
        f"Enveloppes : {envelopes}",
        f"Repères : classe {assessment.risk_class}, baisse supportable retenue {assessment.drawdown_tolerance:.0%}, "
        f"complexité acceptable {assessment.max_complexity}/4, horizon {assessment.horizon_class}",
    ]


def _yes(answer: str) -> bool:
    return answer.strip().lower() in ("o", "oui", "y", "yes", "1", "true")


def run_questionnaire(ask, show=print, base: InvestorProfile | None = None) -> InvestorProfile:
    """Questionnaire interactif. ``ask(prompt) -> str`` (``input`` en CLI) ;
    une réponse vide garde la valeur actuelle (``base`` ou défauts)."""
    base = base or InvestorProfile()
    data = base.to_dict()
    for q in QUESTIONS:
        key, current = q["key"], data.get(q["key"])
        show("")
        show(q["question"])
        if q["kind"] in ("choice", "multi"):
            keys = list(q["options"])
            for i, text in enumerate(q["options"].values(), 1):
                show(f"  {i}. {text}")
            shown = ", ".join(str(keys.index(v) + 1) for v in current or []) if q["kind"] == "multi" else \
                str(keys.index(str(current)) + 1)
            while True:
                answer = ask(f"Choix{' (ex. 1,4)' if q['kind'] == 'multi' else ''} [{shown}] : ").strip()
                if not answer:
                    break
                parts = [part for part in answer.replace(" ", "").split(",") if part]
                if parts and all(part.isdigit() and 1 <= int(part) <= len(keys) for part in parts) and                         (q["kind"] == "multi" or len(parts) == 1):
                    picks = list(dict.fromkeys(keys[int(part) - 1] for part in parts))
                    data[key] = picks if q["kind"] == "multi" else picks[0]
                    break
                show("Réponse invalide, recommence.")
        else:
            while True:
                answer = ask(f"Valeur [{'' if current is None else current}] : ").strip().replace(" ", "").replace(",", ".")
                if not answer:
                    break
                try:
                    number = float(answer)
                except ValueError:
                    show("Nombre attendu, recommence.")
                    continue
                data[key] = int(number) if q["kind"] == "years" else number
                break
    for option, text in (("crypto", "Inclure une petite poche crypto ?"), ("esg", "Privilégier l'ESG / ISR ?"),
                         ("securite", "Vouloir une poche sécurisée (obligations / fonds euros) ?")):
        answer = ask(f"{text} (o/n) [{'o' if data['options'][option] else 'n'}] : ")
        if answer.strip():
            data["options"][option] = _yes(answer)
    for envelope in ("pea", "assurance_vie", "cto"):
        current = bool((data["enveloppes"].get(envelope) or {}).get("ouvert"))
        answer = ask(f"{ENVELOPE_LABELS[envelope]} déjà ouvert ? (o/n) [{'o' if current else 'n'}] : ")
        if answer.strip():
            data["enveloppes"].setdefault(envelope, {})["ouvert"] = _yes(answer)
    answer = ask(f"Épargne de précaution constituée ? (o/n) [{'o' if data['epargne_precaution_ok'] else 'n'}] : ")
    if answer.strip():
        data["epargne_precaution_ok"] = _yes(answer)
    return profile_from_dict(data, "questionnaire")

"""Pilotage patrimonial local et autonome (Projet 7)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Mapping

import yaml

from src.taxes import pea_net_value, tax_config_from

_TYPES = ("actions", "liquidites", "mixte")
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "patrimoine.yaml"
DEFAULT_INFLATION_PCT = 2.0


def load_patrimoine_config(config_path: str | Path) -> dict:
    """Charge et valide la configuration patrimoniale YAML."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration patrimoniale introuvable : {path}")
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError("La configuration patrimoniale doit être un dictionnaire YAML.")
    profil = config.get("profil")
    if not isinstance(profil, dict):
        raise ValueError("Champ obligatoire manquant ou invalide : profil.")
    if config.get("profile_source"):
        from src.investor_profile import load_profile

        personal = load_profile(path.parent / config["profile_source"])
        if personal is None:
            raise FileNotFoundError("Profil personnel requis par profile_source.")
        profil["horizon_ans"] = personal.horizon_ans
        profil["versement_mensuel_eur"] = personal.versement_mensuel_eur
        config.setdefault("pea", {})["date_ouverture"] = (personal.enveloppes.get("pea") or {}).get("date_ouverture")
    for field in ("horizon_ans", "versement_mensuel_eur", "tolerance_derivation_pct"):
        if field not in profil:
            raise ValueError(f"Champ obligatoire manquant : profil.{field}.")
    if not isinstance(profil["horizon_ans"], int) or isinstance(profil["horizon_ans"], bool) or profil["horizon_ans"] <= 0:
        raise ValueError("profil.horizon_ans doit être un entier strictement positif.")
    for field in ("versement_mensuel_eur", "tolerance_derivation_pct"):
        if not isinstance(profil[field], (int, float)) or isinstance(profil[field], bool) or profil[field] < 0:
            raise ValueError(f"profil.{field} doit être un nombre positif ou nul.")
    frequency = profil.get("frequence_achat_mois", 1)
    if not isinstance(frequency, int) or isinstance(frequency, bool) or not 1 <= frequency <= 12:
        raise ValueError("profil.frequence_achat_mois doit être un entier entre 1 et 12.")
    first = profil.get("premier_mois_achat")
    if first is not None:
        import re

        if not isinstance(first, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", first):
            raise ValueError("profil.premier_mois_achat doit être au format AAAA-MM (ex. 2026-10).")
    inflation = profil.get("inflation_pct", DEFAULT_INFLATION_PCT)
    if not isinstance(inflation, (int, float)) or isinstance(inflation, bool) or not -5 <= inflation <= 20:
        raise ValueError("profil.inflation_pct doit être un nombre entre -5 et 20.")
    enveloppes = config.get("enveloppes")
    if not isinstance(enveloppes, list) or not enveloppes:
        raise ValueError("Champ obligatoire invalide : enveloppes doit être une liste non vide.")
    ids: set[str] = set()
    for index, envelope in enumerate(enveloppes):
        prefix = f"enveloppes[{index}]"
        if not isinstance(envelope, dict):
            raise ValueError(f"{prefix} doit être un dictionnaire.")
        for field in ("id", "label", "type", "actif", "notes"):
            if field not in envelope:
                raise ValueError(f"Champ obligatoire manquant : {prefix}.{field}.")
        if not isinstance(envelope["id"], str) or not envelope["id"].strip():
            raise ValueError(f"{prefix}.id doit être une chaîne non vide.")
        if envelope["id"] in ids:
            raise ValueError(f"Identifiant d'enveloppe dupliqué : {envelope['id']}.")
        ids.add(envelope["id"])
        if not isinstance(envelope["label"], str) or not envelope["label"].strip():
            raise ValueError(f"{prefix}.label doit être une chaîne non vide.")
        if envelope["type"] not in _TYPES:
            raise ValueError(f"{prefix}.type doit être l'un de : {', '.join(_TYPES)}.")
        if not isinstance(envelope["actif"], bool):
            raise ValueError(f"{prefix}.actif doit être un booléen.")
        if not isinstance(envelope["notes"], str):
            raise ValueError(f"{prefix}.notes doit être une chaîne.")
    target = config.get("allocation_cible_pct")
    if not isinstance(target, dict) or set(target) != set(_TYPES):
        raise ValueError("allocation_cible_pct doit définir actions, liquidites et mixte.")
    if any(not isinstance(target[k], (int, float)) or isinstance(target[k], bool) or target[k] < 0 for k in _TYPES):
        raise ValueError("Les cibles d'allocation doivent être des pourcentages positifs ou nuls.")
    if abs(sum(float(target[k]) for k in _TYPES) - 100.0) > 1e-9:
        raise ValueError("La somme de allocation_cible_pct doit être égale à 100.")
    if not isinstance(config.get("commentaire"), str):
        raise ValueError("Champ obligatoire manquant ou invalide : commentaire.")
    tax_config_from(config)  # valide la section fiscalite (optionnelle)
    return config


def compute_allocation(enveloppes_valeurs: Mapping[str, float], config: dict | None = None) -> dict:
    """Calcule l'allocation active, la cible et la dérive par type."""
    if not isinstance(enveloppes_valeurs, Mapping):
        raise ValueError("enveloppes_valeurs doit être un dictionnaire {id: valeur_eur}.")
    config = load_patrimoine_config(_DEFAULT_CONFIG_PATH) if config is None else config
    known = {item["id"]: item for item in config["enveloppes"]}
    unknown = set(enveloppes_valeurs) - set(known)
    if unknown:
        raise ValueError(f"Enveloppe inconnue : {sorted(unknown)[0]}.")
    values: dict[str, float] = {}
    for envelope_id, value in enveloppes_valeurs.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"La valeur de {envelope_id} doit être numérique.")
        if float(value) < 0:
            raise ValueError(f"La valeur de {envelope_id} ne peut pas être négative.")
        values[envelope_id] = float(value)
    amounts = {kind: 0.0 for kind in _TYPES}
    for envelope in known.values():
        if envelope["actif"]:
            amounts[envelope["type"]] += values.get(envelope["id"], 0.0)
    total = sum(amounts.values())
    current = {kind: (amounts[kind] / total * 100.0 if total else 0.0) for kind in _TYPES}
    target = {kind: float(config["allocation_cible_pct"][kind]) for kind in _TYPES}
    # Sans aucune valeur renseignée, la répartition n'a pas de sens : pas de dérive.
    drift = {kind: (current[kind] - target[kind] if total else 0.0) for kind in _TYPES}
    tolerance = float(config["profil"]["tolerance_derivation_pct"])
    drift_types = [kind for kind in _TYPES if abs(drift[kind]) > tolerance]
    return {"total_eur": total, "amounts_eur": amounts, "current_pct": current, "target_pct": target,
            "drift_pct": drift, "max_abs_drift_pct": max(abs(v) for v in drift.values()),
            "drift_detected": bool(drift_types), "drift_types": drift_types, "empty": total == 0}


def _future_value(principal: float, monthly_payment: float, annual_rate_pct: float, months: int) -> float:
    rate = annual_rate_pct / 100.0 / 12.0
    if rate == 0:
        return principal + monthly_payment * months
    factor = (1.0 + rate) ** months
    return principal * factor + monthly_payment * (factor - 1.0) / rate


def compute_projection(valeur_actuelle_eur: float, versement_mensuel_eur: float,
                       rendement_annuel_pct: float, horizon_ans: int, *,
                       scenario_rates_pct: Mapping[str, float] | None = None,
                       inflation_pct: float | None = None) -> dict:
    """Projette le capital par capitalisation mensuelle avec versements réguliers.

    Avec ``inflation_pct``, chaque scénario indique aussi la valeur finale en
    euros d'aujourd'hui : ``valeur_finale / (1 + inflation) ** horizon``.
    """
    for name, value in (("valeur_actuelle_eur", valeur_actuelle_eur), ("versement_mensuel_eur", versement_mensuel_eur), ("rendement_annuel_pct", rendement_annuel_pct)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} doit être numérique.")
    if valeur_actuelle_eur < 0 or versement_mensuel_eur < 0:
        raise ValueError("La valeur actuelle et le versement mensuel ne peuvent pas être négatifs.")
    if not isinstance(horizon_ans, int) or isinstance(horizon_ans, bool) or horizon_ans <= 0:
        raise ValueError("horizon_ans doit être un entier strictement positif.")
    rates = dict(scenario_rates_pct or {"pessimiste": float(rendement_annuel_pct) - 3.0,
                                         "central": float(rendement_annuel_pct),
                                         "optimiste": float(rendement_annuel_pct) + 3.0})
    if set(rates) != {"pessimiste", "central", "optimiste"}:
        raise ValueError("scenario_rates_pct doit définir pessimiste, central et optimiste.")
    if any(not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= -100 for rate in rates.values()):
        raise ValueError("Les taux annuels de scénario doivent être numériques et supérieurs à -100.")
    months = horizon_ans * 12
    total_paid = float(valeur_actuelle_eur) + float(versement_mensuel_eur) * months
    scenarios = {}
    for name, rate in rates.items():
        final = _future_value(float(valeur_actuelle_eur), float(versement_mensuel_eur), float(rate), months)
        scenarios[name] = {"rendement_annuel_pct": float(rate), "valeur_finale_eur": final,
                           "total_verse_eur": total_paid, "plus_value_eur": final - total_paid,
                           "rendement_total_pct": ((final / total_paid - 1.0) * 100.0) if total_paid else 0.0}
        if inflation_pct is not None:
            deflator = (1.0 + float(inflation_pct) / 100.0) ** horizon_ans
            scenarios[name]["valeur_finale_reelle_eur"] = final / deflator
    return {**scenarios["central"], "horizon_ans": horizon_ans, "scenarios": scenarios}


def _recommendation(config: dict, allocation: dict, values: Mapping[str, float]) -> str:
    active_actions = [item for item in config["enveloppes"] if item["actif"] and item["type"] == "actions"]
    if not active_actions:
        return "Aucune enveloppe actions active. Revoir la configuration."
    if allocation.get("empty"):
        return ("Aucune valeur renseignée : compléter config/holdings.yaml (modèle : "
                f"config/holdings.example.yaml). Versement du mois : {active_actions[0]['label']} par défaut.")
    if not allocation["drift_detected"]:
        destination = min(active_actions, key=lambda item: values.get(item["id"], 0.0))
        return f"Allocation en ligne avec la cible. Diriger le versement vers {destination['label']}."
    underweight = [kind for kind in _TYPES if allocation["drift_pct"][kind] < 0]
    kind = min(underweight, key=lambda item: allocation["drift_pct"][item]) if underweight else allocation["drift_types"][0]
    candidates = [item for item in config["enveloppes"] if item["actif"] and item["type"] == kind]
    if not candidates:
        return f"Dérive détectée sur {kind}. Aucune enveloppe active ne permet de rééquilibrer cette classe."
    destination = min(candidates, key=lambda item: values.get(item["id"], 0.0))
    return f"Dérive détectée sur {kind}. Diriger le versement vers {destination['label']}."


def load_holdings(holdings_path: str | Path) -> tuple[dict[str, float], str | None]:
    """Charge les valeurs personnelles des enveloppes (fichier non versionné).

    Format ::

        date: 2026-09-23          # optionnel, date des valeurs
        valeurs_eur:
          pea: 12500
          livret_a: 22950

    Un fichier absent renvoie des valeurs vides (le rapport l'indique).
    """
    path = Path(holdings_path)
    if not path.exists():
        return {}, None
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict) or not isinstance(raw.get("valeurs_eur", {}), dict):
        raise ValueError(f"{path} doit contenir un dictionnaire valeurs_eur.")
    values = {str(k): v for k, v in (raw.get("valeurs_eur") or {}).items()}
    for key, value in values.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"La valeur de {key} dans {path.name} doit être numérique.")
    as_of = raw.get("date")
    return {k: float(v) for k, v in values.items()}, (str(as_of) if as_of is not None else None)


def generate_patrimoine_report(config: dict, enveloppes_valeurs: Mapping[str, float], output_path: Path,
                               *, values_date: str | None = None) -> dict:
    """Génère un rapport Markdown idempotent et retourne les résultats structurés."""
    required = {"profil", "enveloppes", "allocation_cible_pct", "commentaire"}
    if not isinstance(config, dict) or not required.issubset(config):
        raise ValueError("Configuration patrimoniale invalide ou incomplète.")
    allocation = compute_allocation(enveloppes_valeurs, config)
    values = {key: float(value) for key, value in enveloppes_valeurs.items()}
    inflation = float(config["profil"].get("inflation_pct", DEFAULT_INFLATION_PCT))
    projection = compute_projection(allocation["total_eur"], float(config["profil"]["versement_mensuel_eur"]),
                                    7.0, int(config["profil"]["horizon_ans"]),
                                    scenario_rates_pct={"pessimiste": 4.0, "central": 7.0, "optimiste": 10.0},
                                    inflation_pct=inflation)
    taxes = tax_config_from(config)
    horizon = int(config["profil"]["horizon_ans"])
    for item in projection["scenarios"].values():
        item["valeur_finale_nette_eur"] = pea_net_value(item["valeur_finale_eur"], item["total_verse_eur"],
                                                        horizon, taxes)
    recommendation = _recommendation(config, allocation, values)
    lines = ["# Rapport patrimonial global", "", f"Date de génération : {date.today().isoformat()}",
             f"Valeurs au : {values_date or 'non précisé'}", "", "## Enveloppes", "", "| Enveloppe | Type | Valeur | Active |", "| --- | --- | ---: | :---: |"]
    for item in config["enveloppes"]:
        lines.append(f"| {item['label']} | {item['type']} | {values.get(item['id'], 0.0):,.2f} € | {'Oui' if item['actif'] else 'Non'} |")
    lines += ["", "## Répartition actuelle vs cible", "", "| Type | Actuelle | Cible | Dérive |", "| --- | ---: | ---: | ---: |"]
    for kind in _TYPES:
        lines.append(f"| {kind} | {allocation['current_pct'][kind]:.2f} % | {allocation['target_pct'][kind]:.2f} % | {allocation['drift_pct'][kind]:+.2f} pts |")
    if allocation["empty"]:
        status_line = "**Aucune valeur renseignée** : compléter config/holdings.yaml pour calculer la répartition."
    elif allocation["drift_detected"]:
        status_line = "**Alerte : dérive supérieure au seuil.**"
    else:
        status_line = "Allocation dans la tolérance de dérive."
    lines += ["", status_line, "", "## Projection à horizon", "",
              f"Hypothèse d'inflation : {inflation:.1f} % par an (valeur réelle = euros d'aujourd'hui).",
              f"Valeur nette : retrait total à l'horizon, prélèvements sociaux {taxes.prelevements_sociaux_pct:.1f} % "
              "sur le gain (hypothèse : tout en PEA de plus de 5 ans ; simplification).", "",
              "| Scénario | Taux annuel | Valeur finale | Valeur nette | Valeur réelle | Total versé | Plus-value | "
              "Rendement total |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name in ("pessimiste", "central", "optimiste"):
        item = projection["scenarios"][name]
        lines.append(f"| {name.capitalize()} | {item['rendement_annuel_pct']:.1f} % | {item['valeur_finale_eur']:,.2f} € | {item['valeur_finale_nette_eur']:,.2f} € | {item['valeur_finale_reelle_eur']:,.2f} € | {item['total_verse_eur']:,.2f} € | {item['plus_value_eur']:,.2f} € | {item['rendement_total_pct']:.2f} % |")
    lines += ["", "## Recommandation mensuelle", "", recommendation, "", "## Notes", "", config["commentaire"], ""]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return {"allocation": allocation, "projection": projection, "recommendation": recommendation, "report_path": str(output_path)}

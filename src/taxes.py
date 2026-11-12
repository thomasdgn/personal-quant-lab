"""Fiscalité simplifiée des gains (France) pour les projections et simulations.

Simplifications documentées (aucun conseil fiscal) :

- **PEA** : au retrait après 5 ans, seuls les prélèvements sociaux
  (``prelevements_sociaux_pct``, 18,6 % par défaut depuis le 1er janvier 2026) s'appliquent
  au gain ; avant 5 ans, le gain supporte le prélèvement forfaitaire unique
  (``flat_tax_pct``, 31,4 % = 12,8 % d'impôt + 18,6 % de prélèvements sociaux).
- **Assurance-vie** (v5) : épargnée par la hausse de 2026, prélèvements sociaux
  à 17,2 % (``av_prelevements_sociaux_pct``). Après 8 ans : prélèvements sociaux
  sur tout le gain, plus l'impôt sur le revenu (``av_ir_pct``, 7,5 %) sur la part
  du gain qui dépasse l'abattement annuel (``av_abattement_eur``, 4 600 € pour une
  personne seule) ; avant 8 ans : impôt forfaitaire de 12,8 % + prélèvements
  sociaux de l'assurance-vie.
- **Compte-titres (CTO)** et **crypto (compte hors PEA)** : prélèvement
  forfaitaire unique (31,4 % depuis 2026) sur la plus-value, calculé une fois à
  la sortie.

Taux vérifiés le 2026-09-25 (loi de financement de la Sécurité sociale pour 2026 :
CSG portée de 9,2 % à 10,6 % sur les revenus du capital, assurance-vie, PEL et
CEL exclus).
- Une moins-value n'est pas imposée (valeur nette = valeur brute).

Les calculs supposent un retrait total unique à l'horizon (hypothèse prudente :
un retrait étalé paie souvent moins). Les taux évoluent avec les lois de
finances : les vérifier et les renseigner dans ``config/patrimoine.yaml >
fiscalite`` (optionnelle).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

PEA_HOLDING_YEARS = 5
AV_HOLDING_YEARS = 8
ENVELOPES = ("pea", "assurance_vie", "cto", "crypto")
_KEYS = ("prelevements_sociaux_pct", "flat_tax_pct", "av_prelevements_sociaux_pct", "av_ir_pct", "av_abattement_eur")


@dataclass(frozen=True)
class TaxConfig:
    prelevements_sociaux_pct: float = 18.6
    flat_tax_pct: float = 31.4
    av_prelevements_sociaux_pct: float = 17.2
    av_ir_pct: float = 7.5
    av_abattement_eur: float = 4600.0

    def __post_init__(self) -> None:
        for name in _KEYS[:-1]:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 100:
                raise ValueError(f"fiscalite.{name} doit être un pourcentage entre 0 et 100.")
        value = self.av_abattement_eur
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError("fiscalite.av_abattement_eur doit être un montant positif ou nul.")


def tax_config_from(patrimoine_config: dict | None) -> TaxConfig:
    """Construit la configuration fiscale depuis patrimoine.yaml (section optionnelle)."""
    section = (patrimoine_config or {}).get("fiscalite") or {}
    if not isinstance(section, dict):
        raise ValueError("fiscalite doit être un dictionnaire.")
    unknown = set(section) - set(_KEYS)
    if unknown:
        raise ValueError(f"Clés inconnues dans fiscalite : {', '.join(sorted(unknown))}.")
    return TaxConfig(**section)


def _net(final_value: float, invested: float, rate_pct: float) -> float:
    gain = final_value - invested
    return final_value - max(gain, 0.0) * rate_pct / 100.0


def pea_net_value(final_value: float, invested: float, years_held: float, taxes: TaxConfig | None = None) -> float:
    """Valeur nette d'un retrait total du PEA après ``years_held`` années."""
    taxes = taxes or TaxConfig()
    rate = taxes.prelevements_sociaux_pct if years_held >= PEA_HOLDING_YEARS else taxes.flat_tax_pct
    return _net(final_value, invested, rate)


def crypto_net_value(final_value: float, invested: float, taxes: TaxConfig | None = None) -> float:
    """Valeur nette après prélèvement forfaitaire unique sur la plus-value crypto."""
    taxes = taxes or TaxConfig()
    return _net(final_value, invested, taxes.flat_tax_pct)


def envelope_net_values(envelope: str, final_value, invested, years_held: float,
                        taxes: TaxConfig | None = None) -> np.ndarray:
    """Valeurs nettes (vectorisées) d'un retrait total d'une enveloppe.

    ``envelope`` : ``pea``, ``assurance_vie``, ``cto`` ou ``crypto``.
    ``final_value`` et ``invested`` : scalaires ou tableaux de même forme.
    """
    taxes = taxes or TaxConfig()
    value = np.asarray(final_value, dtype=float)
    gain = np.maximum(value - np.asarray(invested, dtype=float), 0.0)
    if envelope == "pea":
        rate = taxes.prelevements_sociaux_pct if years_held >= PEA_HOLDING_YEARS else taxes.flat_tax_pct
        return value - gain * rate / 100.0
    if envelope == "assurance_vie":
        if years_held < AV_HOLDING_YEARS:
            # Impôt forfaitaire (part hors prélèvements sociaux du PFU) + prélèvements sociaux de l'assurance-vie.
            income_part = max(taxes.flat_tax_pct - taxes.prelevements_sociaux_pct, 0.0)
            return value - gain * (income_part + taxes.av_prelevements_sociaux_pct) / 100.0
        income_tax = np.maximum(gain - taxes.av_abattement_eur, 0.0) * taxes.av_ir_pct / 100.0
        return value - gain * taxes.av_prelevements_sociaux_pct / 100.0 - income_tax
    if envelope in ("cto", "crypto"):
        return value - gain * taxes.flat_tax_pct / 100.0
    raise ValueError(f"Enveloppe inconnue : {envelope}. Possibles : {', '.join(ENVELOPES)}.")


ENVELOPE_RULES = {
    "pea": "Actions européennes et ETF éligibles ; plafond de 150 000 € de versements ; après 5 ans, seuls les "
           "prélèvements sociaux sur le gain ; retrait avant 5 ans : prélèvement forfaitaire et clôture.",
    "assurance_vie": "Fonds euros (capital garanti, rendement modeste) et unités de compte ; frais de gestion "
                     "annuels ; après 8 ans, abattement de 4 600 € de gain par an (personne seule) ; utile pour "
                     "une poche sécurisée et la transmission.",
    "cto": "Tous les titres (ETF américains, ETN crypto…) ; aucun plafond ; prélèvement forfaitaire de 31,4 % sur "
           "les gains et les dividendes ; utile au-delà du plafond du PEA.",
    "crypto": "Plateforme agréée (PSAN/CASP) ou ETN sur CTO ; prélèvement forfaitaire de 31,4 % sur la plus-value "
              "à la vente ; volatilité extrême : poche limitée.",
}

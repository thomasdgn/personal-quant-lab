"""Profil investisseur (questionnaire, validation, repères) et fiscalité des enveloppes."""

from pathlib import Path

import numpy as np
import pytest
import yaml

import main
from src.investor_profile import (
    InvestorProfile,
    assess_profile,
    load_profile,
    profile_from_dict,
    profile_lines,
    run_questionnaire,
    save_profile,
)
from src.taxes import TaxConfig, envelope_net_values, pea_net_value, tax_config_from

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config" / "profil.example.yaml"


def _raw(**changes):
    raw = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    raw.update(changes)
    return raw


def test_example_profile_is_valid_and_round_trips(tmp_path):
    profile = load_profile(EXAMPLE)
    assert profile is not None and profile.zones == ("monde",)
    path = save_profile(profile, tmp_path / "profil.yaml")
    assert load_profile(path) == profile
    assert "PERSONNEL" in path.read_text(encoding="utf-8")
    assert load_profile(tmp_path / "absent.yaml") is None


@pytest.mark.parametrize("changes, message", [
    ({"objectif": "lune"}, "objectif"),
    ({"horizon_ans": 0}, "horizon_ans"),
    ({"zones": ["mars"]}, "zones"),
    ({"zones": []}, "zones"),
    ({"options": {"crypto": "oui"}}, "options.crypto"),
    ({"options": {"part_crypto_max_pct": 50}}, "part_crypto_max_pct"),
    ({"enveloppes": {"livret": {"ouvert": True}}}, "enveloppes"),
    ({"versement_mensuel_eur": -5}, "versement_mensuel_eur"),
    ({"inconnu": 1}, "clés inconnues"),
])
def test_invalid_profiles_have_explicit_errors(changes, message):
    with pytest.raises(ValueError, match=message):
        profile_from_dict(_raw(**changes))


def test_assessment_beginner_margin_and_notes():
    profile = profile_from_dict(_raw(reaction_baisse="acheter_plus", temps_mensuel="hobby", versement_mensuel_eur=150,
                                     horizon_ans=15, options={"crypto": True, "esg": True}))
    assessment = assess_profile(profile)
    assert assessment.declared_drawdown == 0.45 and assessment.drawdown_tolerance == pytest.approx(0.40)
    assert assessment.risk_class == "Dynamique" and assessment.max_complexity == 4
    text = " ".join(assessment.notes)
    assert "Petit versement" in text and "Crypto" in text and "ESG" in text and "débutant" in text
    lines = profile_lines(profile, assessment)
    assert any("classe Dynamique" in line for line in lines)


def test_assessment_prudent_short_horizon():
    profile = profile_from_dict(_raw(reaction_baisse="tout_vendre", horizon_ans=3, experience="intermediaire",
                                     epargne_precaution_ok=False, objectif="projet"))
    assessment = assess_profile(profile)
    assert assessment.risk_class == "Prudent" and assessment.horizon_class == "court"
    assert assessment.drawdown_tolerance == 0.15 and assessment.max_equity_share == 0.3
    assert any("précaution" in note for note in assessment.notes)


def test_questionnaire_uses_answers_and_defaults():
    answers = iter(["800", "150", "2", "15", "", "9", "1", "4", "1,4", "1", "o", "o", "", "", "n", "", ""])
    shown = []
    profile = run_questionnaire(lambda prompt: next(answers), shown.append)
    assert profile.capital_initial_eur == 800 and profile.versement_mensuel_eur == 150
    assert profile.objectif == "independance" and profile.horizon_ans == 15
    assert profile.reaction_baisse == "acheter_plus"  # "9" invalide puis "1"
    assert profile.temps_mensuel == "hobby" and profile.zones == ("monde", "emergents")
    assert profile.options.crypto and profile.options.esg and not profile.options.securite
    assert not profile.envelope_open("assurance_vie")
    assert "Réponse invalide, recommence." in shown


def test_profile_cli(tmp_path, capsys):
    path = tmp_path / "profil.yaml"
    assert main.main(["profile", "--profile", str(path)]) == 1
    assert main.main(["profile", "--profile", str(path), "--init"]) == 0
    assert path.exists() and "Repères" in capsys.readouterr().out


def test_envelope_taxes():
    assert envelope_net_values("pea", 150.0, 100.0, 6) == pytest.approx(pea_net_value(150.0, 100.0, 6))
    assert envelope_net_values("pea", 150.0, 100.0, 2) == pytest.approx(150 - 50 * 0.314)
    # Assurance-vie après 8 ans : PS sur tout le gain + 7,5 % au-delà de l'abattement.
    av = envelope_net_values("assurance_vie", 20_000.0, 10_000.0, 10)
    assert av == pytest.approx(20_000 - 10_000 * 0.172 - (10_000 - 4600) * 0.075)
    assert envelope_net_values("assurance_vie", 12_000.0, 10_000.0, 10) == pytest.approx(12_000 - 2000 * 0.172)
    # Avant 8 ans : 12,8 % d'impôt + 17,2 % de prélèvements sociaux (assurance-vie épargnée par la hausse de 2026).
    assert envelope_net_values("assurance_vie", 12_000.0, 10_000.0, 5) == pytest.approx(12_000 - 2000 * 0.30)
    values = envelope_net_values("cto", np.array([90.0, 200.0]), 100.0, 20)
    assert values.tolist() == pytest.approx([90.0, 200 - 100 * 0.314])
    with pytest.raises(ValueError, match="Enveloppe inconnue"):
        envelope_net_values("livret", 1.0, 1.0, 1)
    assert tax_config_from({"fiscalite": {"av_ir_pct": 12.8}}).av_ir_pct == 12.8
    with pytest.raises(ValueError, match="av_abattement_eur"):
        TaxConfig(av_abattement_eur=-1)


def test_default_profile_dataclass():
    profile = InvestorProfile()
    assert profile.envelope_open("pea") and not profile.envelope_open("cto")

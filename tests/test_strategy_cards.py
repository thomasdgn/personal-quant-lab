"""Fiches des stratégies : complétude, fusion avec les mesures, rapport et CLI."""

import json

import pytest

import main
from src.strategies import REGISTRY
from src.strategy_cards import CARDS, card_markdown, card_view, generate_cards_report

FIELDS = {"titre", "resume", "principe", "regles", "temps", "complexite", "lignes", "forces", "faiblesses",
          "pour_qui", "erreurs"}


def test_every_registry_strategy_has_a_complete_card():
    assert set(CARDS) == set(REGISTRY)
    for name, card in CARDS.items():
        assert FIELDS <= set(card), name
        assert 1 <= card["complexite"] <= 4 and card["regles"] and card["forces"] and card["faiblesses"]


def _fake_measures():
    stats = {"cagr": 0.08, "volatility": 0.12, "sharpe": 0.7, "max_drawdown": -0.2, "worst_year": -0.1,
             "best_year": 0.2, "worst_5y_cagr": 0.02, "avg_exposure": 0.8, "turnover_per_year": 1.5}
    item = {"label": "X", "stats": stats, "verdict": "robuste", "score": 1.0, "criteria": [], "subperiods": [],
            "edge": {"verdict": "possible", "text": ""}, "protection": {"verdict": "forte", "text": ""}}
    robustness = {"start": "2008-02-29", "end": "2026-08-31", "strategies": {"momentum_vt": item}}
    stress = {"windows": [
        {"fenêtre": "Covid 2020", "stratégie": "momentum_vt", "actif": True, "rendement": -0.05,
         "drawdown_max": -0.09, "mois_recuperation": 3, "part_synthetique": 0.0},
        {"fenêtre": "Covid 2020", "stratégie": "benchmark", "actif": True, "rendement": -0.15,
         "drawdown_max": -0.19, "mois_recuperation": 5, "part_synthetique": 0.0}]}
    return robustness, stress


def test_card_view_merges_measures_and_crises():
    robustness, stress = _fake_measures()
    view = card_view("momentum_vt", robustness, stress)
    assert view["mesures"]["fiabilite"] == "robuste" and view["crises"][0]["drawdown_benchmark"] == -0.19
    text = "\n".join(card_markdown(view))
    assert "Covid 2020 : -9% (-19%)" in text and "protection **forte**" in text
    assert card_view("benchmark")["mesures"] is None
    with pytest.raises(ValueError, match="Pas de fiche"):
        card_view("inconnue")


def test_cards_report_and_cli(tmp_path, capsys):
    robustness, stress = _fake_measures()
    (tmp_path / "rob.json").write_text(json.dumps(robustness), encoding="utf-8")
    (tmp_path / "stress.json").write_text(json.dumps(stress), encoding="utf-8")
    report = generate_cards_report(tmp_path / "cards.md", tmp_path / "rob.json", tmp_path / "stress.json")
    text = report.read_text(encoding="utf-8")
    assert "Ce ne sont pas des recommandations" in text and text.count("\n## ") == len(CARDS)
    out = tmp_path / "cards2.md"
    assert main.main(["strategies", "--robustness", str(tmp_path / "absent.json"), "--stress",
                      str(tmp_path / "absent.json"), "--output", str(out)]) == 0
    assert "Mesures absentes" in out.read_text(encoding="utf-8")
    assert "momentum_vt" in capsys.readouterr().out

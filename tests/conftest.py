"""Options et isolation partagées des tests.

Les tests ne dépendent jamais des choix personnels faits dans ``config/`` (stratégie
suivie, frais du courtier, versement) : les chemins par défaut de la CLI et du
tableau de bord pointent vers des copies figées dans ``tests/fixtures/config/``.
"""

from pathlib import Path

import pytest

FIXTURE_CONFIG = Path(__file__).resolve().parent / "fixtures" / "config"
_DEFAULTS = {"DEFAULT_CONFIG": "strategy_params.yaml", "DEFAULT_POLICY": "policy.yaml",
             "DEFAULT_PATRIMOINE": "patrimoine.yaml"}
_CLI_MODULES = ("src.cli.common", "src.cli.parser", "src.cli.report_cmds", "src.cli.research_cmds",
                "src.cli.wealth_cmds", "src.cli.paper_cmds", "src.cli.plan_cmds")


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden", action="store_true", default=False,
        help="Régénère les fichiers de référence de tests/golden/ (changement volontaire uniquement).",
    )


@pytest.fixture(autouse=True)
def frozen_project_config(monkeypatch):
    """Redirige les configurations par défaut vers les copies figées des tests."""
    import importlib

    for module_name in _CLI_MODULES:
        module = importlib.import_module(module_name)
        for name, filename in _DEFAULTS.items():
            if hasattr(module, name):
                monkeypatch.setattr(module, name, FIXTURE_CONFIG / filename)
    import app.data as app_data

    for name, filename in (("PATRIMOINE_CONFIG", "patrimoine.yaml"), ("STRATEGY_CONFIG", "strategy_params.yaml"),
                           ("POLICY", "policy.yaml")):
        monkeypatch.setattr(app_data, name, FIXTURE_CONFIG / filename)
    yield

"""Interface CLI du personal-quant-lab (Projet 4).

Commande principale : produire le rapport mensuel (Markdown + snapshot JSON) à
partir des données **locales** par défaut. Le téléchargement réseau est explicite
via ``--refresh-data``. Aucun ordre n'est exécuté.

Exemples
--------
    python main.py status                      # état du lab et prochaine action
    python main.py run-month --refresh-data    # routine mensuelle complète
    python main.py monthly-report --report-date 2026-06-30
    python main.py refresh-data
    python main.py patrimoine
    python main.py dca
    python main.py regime
    python main.py validate

Guide complet : docs/USAGE.md
"""

from __future__ import annotations

from src.cli.common import (  # noqa: F401 - noms historiques ré-exportés
    DEFAULT_DATA,
    DOWNLOAD_START,
    LEGACY_DATA,
    PROJECT_ROOT,
    _resolve_data_path,
)
from src.cli.parser import build_parser, main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())

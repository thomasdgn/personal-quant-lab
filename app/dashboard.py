"""Tableau de bord local du personal-quant-lab.

Lancement depuis la racine du projet :

    streamlit run app/dashboard.py

Le tableau de bord lit les fichiers produits par le moteur (snapshots JSON,
journal, études, plans, portefeuille réel) et simule les plans en direct. Il
n'écrit qu'un seul fichier, ton profil (``config/profil.yaml``, personnel), et
n'offre aucun bouton d'achat ou de vente : les ordres se passent à la main,
chez le courtier. Nouveau mois : ``python main.py run-month --refresh-data``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app.data import lab_status, load_snapshots  # noqa: E402

APP_DIR = Path(__file__).resolve().parent

st.set_page_config(page_title="Personal Quant Lab", page_icon=":material/monitoring:", layout="wide",
                   initial_sidebar_state="auto")


@st.cache_data(ttl=60, show_spinner=False)
def cached_status() -> dict:
    return lab_status()


@st.cache_data(ttl=60, show_spinner=False)
def cached_months() -> list[str]:
    return [snapshot["metadata"]["report_month"] for _, snapshot in load_snapshots()]


pages_dir = APP_DIR / "app_pages"


def page(name: str, title: str, icon: str, **kwargs) -> st.Page:
    return st.Page(pages_dir / f"{name}.py", title=title, icon=f":material/{icon}:", url_path=name, **kwargs)


navigation = st.navigation(
    {
        "": [page("home", "Accueil", "home", default=True)],
        "Ce mois-ci": [
            page("month", "Rapport du mois", "today"),
            page("plan", "Plan de versement", "shopping_cart"),
            page("journal", "Journal de décision", "edit_note"),
        ],
        "Mon argent": [
            page("pea", "Mon PEA Bourso", "account_balance"),
            page("portfolio", "Portefeuille réel", "account_balance_wallet"),
            page("patrimoine", "Patrimoine", "account_balance"),
            page("performance", "Performance paper", "trending_up"),
        ],
        "Construire mon plan": [
            page("profile", "Mon profil", "person"),
            page("plans", "Plans d'investissement", "route"),
            page("strategies", "Stratégies", "menu_book"),
            page("optimization", "Frais et rendement", "speed"),
        ],
        "Laboratoire": [
            page("robustness", "Robustesse", "verified"),
            page("research", "Recherche", "science"),
            page("stress", "Stress tests", "thunderstorm"),
            page("history", "Historique", "history"),
            page("policy", "Politique", "policy"),
        ],
    },
    position="sidebar",
    expanded=True,
)

with st.sidebar:
    st.markdown("### :material/monitoring: Personal Quant Lab")
    try:
        status = cached_status()
        data = status["data"]
        if data.get("exists"):
            fresh = data["age_days"] <= 7
            st.badge(f"Données au {data['last_observation']}", icon=":material/database:",
                     color="green" if fresh else "orange")
        else:
            st.badge("Aucune donnée locale", icon=":material/database:", color="red")
        todo = [s for s in status["next_steps"] if not s.startswith("Rien à faire")]
        st.badge(f"{len(todo)} action(s) à faire" if todo else "Routine du mois terminée",
                 icon=":material/pending_actions:" if todo else ":material/task_alt:",
                 color="orange" if todo else "green")
    except (ValueError, FileNotFoundError) as exc:
        st.badge("État indisponible", icon=":material/error:", color="red", help=str(exc))
    months = cached_months()
    if months:
        st.selectbox("Rapport mensuel affiché", months[::-1], key="month")
    with st.expander(":material/terminal: Commandes utiles"):
        st.code("python main.py run-month --refresh-data --html\n"
                "python main.py plan-contribution --record\n"
                "python main.py plans\n"
                "python main.py robustness", language="bash")
    st.caption("Éducatif et paper trading. Aucun ordre n'est passé ; la décision reste la tienne.")

navigation.run()

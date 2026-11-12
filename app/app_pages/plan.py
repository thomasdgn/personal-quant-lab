"""Page « Plan de versement » : affiche la dernière proposition (lecture seule)."""

import streamlit as st

from app import ui
from app.data import latest_plan, positions_table

ui.page_header("Plan de versement", "Achats proposés pour ce mois (parts entières, sans vente). **Aucun ordre n'est passé** : à saisir toi-même chez le courtier.", icon=":material/shopping_cart:")


plan = latest_plan()
if plan is None:
    st.info("Aucun plan de versement. Lance `python main.py plan-contribution` après avoir renseigné "
            "`config/positions.yaml` (modèle : `config/positions.example.yaml`).", icon=":material/info:")
else:
    st.warning("Document enregistré : vérifier sa date et l'état du compte dans « Mon PEA Bourso » avant toute utilisation.")
    with st.container(border=True):
        st.markdown(plan.read_text(encoding="utf-8"))
    st.caption(f"Fichier : {plan.name}")

try:
    positions = positions_table()
except ValueError as exc:
    st.error(f"Positions illisibles : {exc}")
    positions = None
if positions is not None and not positions.empty:
    with st.expander("Positions actuelles (config/positions.yaml)"):
        st.dataframe(positions, hide_index=True,
                     column_config={"prix": st.column_config.NumberColumn(format="%.2f €"),
                                    "valeur": st.column_config.NumberColumn(format="%.2f €")})

"""Page « Patrimoine » : répartition actuelle vs cible (valeurs locales)."""

import pandas as pd
import streamlit as st

from app import ui
from app.data import patrimoine_summary

ui.page_header("Patrimoine", "Répartition actuelle entre enveloppes, comparée à ta cible.", icon=":material/account_balance:")

summary = patrimoine_summary()
if summary is None:
    st.write("Configuration patrimoniale absente.")
elif summary["allocation"]["empty"]:
    st.info("Aucune valeur renseignée : copier `config/holdings.example.yaml` en `config/holdings.yaml` "
            "(ou renseigner `config/positions.yaml`) — fichiers non versionnés.", icon=":material/info:")
else:
    allocation = summary["allocation"]
    with st.container(horizontal=True):
        st.metric("Total suivi", f"{allocation['total_eur']:,.0f} €".replace(",", " "),
                  help=f"Valeurs au {summary['as_of'] or 'non précisé'}", border=True)
        st.metric("Versement mensuel", f"{summary['monthly_contribution']:,.0f} €".replace(",", " "), border=True)
        st.metric("Dérive max", f"{allocation['max_abs_drift_pct']:.1f} pts", border=True)
    st.dataframe(summary["values"], hide_index=True,
                 column_config={"valeur (€)": st.column_config.NumberColumn(format="%.0f €")})
    mix = pd.DataFrame({"actuelle": allocation["current_pct"], "cible": allocation["target_pct"]}) / 100
    st.dataframe(mix, column_config={c: st.column_config.NumberColumn(format="percent") for c in mix.columns})
    if allocation["drift_detected"]:
        st.warning(f"Dérive au-delà de la tolérance sur : {', '.join(allocation['drift_types'])}.")
st.caption("Rapport détaillé : `python main.py patrimoine` → reports/patrimoine_report.md")

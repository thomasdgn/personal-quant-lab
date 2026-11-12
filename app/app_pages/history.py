"""Page « Historique » : un rapport par mois et évolution de l'exposition proposée."""

import altair as alt
import streamlit as st

from app import ui
from app.data import load_snapshots, snapshot_history

ui.page_header("Historique", "Un rapport par mois : ce que proposait la stratégie suivie, et avec quelle exposition.", icon=":material/history:")

history = snapshot_history(load_snapshots())
if history.empty:
    st.info("Aucun rapport mensuel.")
    st.stop()

st.dataframe(
    history, hide_index=True,
    column_config={
        "exposition": st.column_config.ProgressColumn("exposition", format="percent", min_value=0, max_value=1),
        "cash": st.column_config.NumberColumn("cash", format="percent"),
        "volatilité réalisée": st.column_config.NumberColumn("volatilité réalisée", format="percent"),
    },
)
chart = history.dropna(subset=["exposition"])
if not chart.empty:
    with st.container(border=True):
        st.markdown("**Exposition proposée d'un mois sur l'autre**")
        st.altair_chart(
            alt.Chart(chart).mark_line(point=True).encode(
                x=alt.X("mois:O", title=None),
                y=alt.Y("exposition:Q", title=None, axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
                tooltip=["mois", "sélection", alt.Tooltip("exposition:Q", format=".0%"), "statut"],
            )
        )

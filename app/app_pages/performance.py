"""Page « Performance paper » : mes décisions vs proposition du système vs benchmark."""

import altair as alt
import pandas as pd
import streamlit as st

from app import ui
from app.data import paper_ledger
from src.paper_ledger import PORTFOLIO_LABELS, PORTFOLIOS

ui.page_header("Performance paper", "Ce qu'auraient donné tes décisions de paper trading, comparées au système et au Buy & Hold.", icon=":material/trending_up:")


@st.cache_data(ttl=300, show_spinner="Reconstitution du portefeuille fictif…")
def cached_ledger() -> dict | None:
    ledger = paper_ledger()
    if ledger is None:
        return None
    return {key: ledger[key] for key in ("start", "end", "n_months", "monthly", "metrics", "value_added", "warnings")}


st.caption("Portefeuilles fictifs reconstitués à partir du journal de décisions (commande `paper-performance`).")
try:
    ledger = cached_ledger()
except ValueError as exc:
    st.error(f"Performance indisponible : {exc}")
    st.stop()
if ledger is None:
    st.info("Pas de prix locaux : lance `python main.py refresh-data`.")
    st.stop()
for warning in ledger["warnings"]:
    st.info(warning, icon=":material/info:")
if not ledger["n_months"]:
    st.stop()

st.markdown(f"Période suivie : **{ledger['start']} → {ledger['end']}** ({ledger['n_months']} mois complets)")
with st.container(horizontal=True):
    for name in PORTFOLIOS:
        metrics = ledger["metrics"][name]
        st.metric(PORTFOLIO_LABELS[name], f"{metrics['total_return']:+.2%}",
                  help=f"Max drawdown {metrics['max_drawdown']:.2%} · frais {metrics['costs']:.2%}", border=True)
    st.metric("Valeur ajoutée de mes choix", f"{ledger['value_added']:+.2%}", help="Mes décisions − proposition du système",
              border=True)

monthly = ledger["monthly"]
values = pd.DataFrame({PORTFOLIO_LABELS[name]: monthly[f"{name}_value"] for name in PORTFOLIOS})
data = values.reset_index(names="date").melt(id_vars="date", var_name="portefeuille", value_name="valeur")
with st.container(border=True):
    st.markdown("**Valeur de 1 € investi au début du suivi**")
    st.altair_chart(
        alt.Chart(data).mark_line(point=True).encode(
            x=alt.X("yearmonth(date):T", title=None, axis=alt.Axis(format="%Y-%m", tickCount="month")),
            y=alt.Y("valeur:Q", title=None, scale=alt.Scale(zero=False)),
            color=alt.Color("portefeuille:N", title=None),
            tooltip=["date:T", "portefeuille:N", alt.Tooltip("valeur:Q", format=".4f")],
        )
    )
table = monthly[[f"{name}_return" for name in PORTFOLIOS] + ["paper_selection", "system_selection"]].copy()
table.columns = [PORTFOLIO_LABELS[name] for name in PORTFOLIOS] + ["détenu (paper)", "détenu (système)"]
st.dataframe(table.style.format({PORTFOLIO_LABELS[n]: "{:+.2%}" for n in PORTFOLIOS}))
st.caption("Quelques mois ne suffisent pas à juger une stratégie : lecture indicative.")

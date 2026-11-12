"""Page « Recherche » : tableau de preuves de `python main.py research` (lecture seule)."""

import altair as alt
import pandas as pd
import streamlit as st

from app import ui
from app.data import load_research

ui.page_header("Recherche", "Tableau de preuves sur données réelles (2019-2026) : écart de Sharpe avec le Buy & Hold et intervalles de confiance.", icon=":material/science:")

research = load_research()
if research is None:
    st.info("Aucune étude. Lance `python main.py research`.", icon=":material/info:")
    st.stop()

st.caption(f"Fenêtre commune {research['start']} → {research['end']} ({research['n_months']} mois) · "
           f"{research['n_strategies_tested']} variantes testées · étude du {research['generated']}. "
           "Elle ne change pas la stratégie suivie.")

strategies = pd.DataFrame(research["strategies"]).set_index("label")
table = strategies[["cagr", "volatility", "sharpe", "sharpe_diff", "sharpe_diff_low", "sharpe_diff_high",
                    "prob_positive", "max_drawdown", "turnover_per_year", "cagr_high_cost"]]
st.dataframe(
    table.sort_values("sharpe", ascending=False),
    column_config={
        "cagr": st.column_config.NumberColumn("CAGR", format="percent"),
        "volatility": st.column_config.NumberColumn("volatilité", format="percent"),
        "sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
        "sharpe_diff": st.column_config.NumberColumn("écart vs B&H", format="%+.2f"),
        "sharpe_diff_low": st.column_config.NumberColumn("IC 90 % bas", format="%+.2f"),
        "sharpe_diff_high": st.column_config.NumberColumn("IC 90 % haut", format="%+.2f"),
        "prob_positive": st.column_config.NumberColumn("P(écart > 0)", format="percent"),
        "max_drawdown": st.column_config.NumberColumn("max DD", format="percent"),
        "turnover_per_year": st.column_config.NumberColumn("turnover / an", format="percent"),
        "cagr_high_cost": st.column_config.NumberColumn(f"CAGR à {research['high_cost']:.2%}", format="percent"),
    },
)

ci = strategies.dropna(subset=["sharpe_diff"]).reset_index()
with st.container(border=True):
    st.markdown("**Écart de Sharpe avec le Buy & Hold (intervalle de confiance à 90 %)**")
    base = alt.Chart(ci).encode(y=alt.Y("label:N", title=None, axis=alt.Axis(labelLimit=320)))
    st.altair_chart(
        base.mark_rule(strokeWidth=2).encode(x=alt.X("sharpe_diff_low:Q", title="écart de Sharpe"),
                                             x2="sharpe_diff_high:Q")
        + base.mark_point(filled=True, size=70).encode(
            x="sharpe_diff:Q", tooltip=["label", alt.Tooltip("sharpe_diff:Q", format="+.2f"),
                                        alt.Tooltip("prob_positive:Q", format=".0%")])
        + alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(strokeDash=[4, 4], color="gray").encode(x="x:Q")
    )

with st.container(border=True):
    st.markdown("**Conclusion factuelle**")
    for line in research["conclusion"]:
        st.markdown(line)

with st.expander("Paramètres choisis en walk-forward"):
    st.dataframe(pd.DataFrame(research["walk_forward"]), hide_index=True)
    st.caption(f"Corrélation de rang des Sharpe entre les deux moitiés : {research['rank_correlation']:.2f}")

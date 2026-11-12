"""Page « Stress » : crises historiques et distribution des versements (partiellement synthétique)."""

import altair as alt
import pandas as pd
import streamlit as st

from app import ui
from app.data import load_stress

ui.page_header("Stress tests", "Comportement des stratégies dans les grandes crises et distribution des versements sur longue période.", icon=":material/thunderstorm:")

stress = load_stress()
if stress is None:
    st.info("Aucune étude : lance `python main.py refresh-data --long` puis `python main.py stress`.")
    st.stop()
st.warning("Données **partiellement synthétiques** : avant la cotation des ETF PEA, les prix proviennent de proxys "
           "de même exposition (`config/long_history.yaml`). Résultats indicatifs.", icon=":material/science:")
st.caption(f"Historique {stress['start']} → {stress['end']} · étude du {stress['generated']} · "
           f"stratégie suivie : {stress['followed']} · limite de drawdown {stress['drawdown_limit']:.0%}")

all_windows = pd.DataFrame(stress["windows"])
windows = all_windows[all_windows["actif"].astype(bool)].copy()
windows["stratégie"] = windows["stratégie"].map(stress["labels"])
windows["drawdown_max"] = windows["drawdown_max"].astype(float)
pivot = windows.pivot(index="stratégie", columns="fenêtre", values="drawdown_max")
order = [w for w in dict.fromkeys(all_windows["fenêtre"]) if w in pivot.columns]
with st.container(border=True):
    st.markdown("**Drawdown maximal par crise**")
    st.dataframe(pivot[order], column_config={c: st.column_config.NumberColumn(c, format="percent") for c in order})
    shares = all_windows.drop_duplicates("fenêtre").set_index("fenêtre")["part_synthetique"]
    st.caption("Part synthétique par fenêtre : " + " · ".join(
        f"{w} {0.0 if s is None or pd.isna(s) else float(s):.0%}" for w, s in shares.items()))

rows = []
for name, item in stress["outcomes"].items():
    rows.append({"stratégie": stress["labels"][name], "p5": item["final_net"]["p5"], "p50": item["final_net"]["p50"],
                 "p95": item["final_net"]["p95"], "P(DD > limite)": item["prob_drawdown_beyond_limit"],
                 "P(perte)": item["prob_loss"]})
outcomes = pd.DataFrame(rows)
first = next(iter(stress["outcomes"].values()))
with st.container(border=True):
    st.markdown(f"**Versements de {first['monthly_contribution']:,.0f} € par mois sur {first['horizon_months'] // 12} "
                "ans — valeur nette (frais et impôts)**")
    base = alt.Chart(outcomes).encode(y=alt.Y("stratégie:N", title=None, sort="-x", axis=alt.Axis(labelLimit=320)))
    st.altair_chart(base.mark_rule().encode(x=alt.X("p5:Q", title="euros (p5 à p95, point = médiane)"), x2="p95:Q")
                    + base.mark_point(filled=True, size=70).encode(x="p50:Q", tooltip=list(outcomes.columns)))
    st.dataframe(outcomes, hide_index=True, column_config={
        "p5": st.column_config.NumberColumn(format="%.0f €"), "p50": st.column_config.NumberColumn(format="%.0f €"),
        "p95": st.column_config.NumberColumn(format="%.0f €"),
        "P(DD > limite)": st.column_config.NumberColumn(format="percent"),
        "P(perte)": st.column_config.NumberColumn(format="percent")})
for line in stress["conclusion"]:
    st.markdown(line)

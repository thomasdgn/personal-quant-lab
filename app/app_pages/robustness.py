"""Page « Robustesse » : verdicts de fiabilité, surperformance et protection (historique long)."""

import altair as alt
import pandas as pd
import streamlit as st

from app import ui
from app.planning import load_robustness

ui.page_header("Robustesse", "Les stratégies sont-elles fiables, ou juste chanceuses ? Tests sur près de 20 ans, "
                             "corrigés du nombre de variantes essayées.", icon=":material/verified:")
study = load_robustness()
if study is None:
    ui.empty_state("Aucune étude de robustesse.", "python main.py robustness")
    st.stop()

st.info("Étude historique enregistrée : les anciens résultats doivent être recalculés avec le moteur corrigé. "
        "Le score indique la proportion de critères satisfaits, sans garantie de performance.")

st.warning(f"Historique {study['start'][:7]} → {study['end'][:7]} ({study['n_months']} mois), part synthétique "
           f"moyenne {ui.pct(study['synthetic_share'])} (proxys avant la cotation des ETF PEA). "
           f"{study['n_trials']} variantes évaluées.", icon=":material/science:")

items = study["strategies"]
rows = [{"stratégie": v["label"] + (" (suivie)" if k == study["followed"] else ""), "fiabilité": v["verdict"],
         "score": v["score"], "surperformance": (v.get("edge") or {}).get("verdict", "référence"),
         "protection": (v.get("protection") or {}).get("verdict", "référence"),
         "rendement / an": v["stats"]["cagr"], "Sharpe": v["stats"]["sharpe"], "pire baisse": v["stats"]["max_drawdown"],
         "PSR": v["psr"], "DSR": v["dsr"]} for k, v in items.items()]
st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
    "score": st.column_config.ProgressColumn("Critères satisfaits", format="percent", min_value=0, max_value=1),
    "rendement / an": st.column_config.NumberColumn(format="percent"),
    "Sharpe": st.column_config.NumberColumn(format="%.2f"),
    "pire baisse": st.column_config.NumberColumn(format="percent"),
    "PSR": st.column_config.NumberColumn(help="Probabilité que le vrai Sharpe soit positif", format="percent"),
    "DSR": st.column_config.NumberColumn(help="Idem, corrigé du nombre de variantes essayées", format="percent")})

with st.container(border=True):
    st.markdown("**:material/summarize: Conclusion**")
    for line in study["conclusion"]:
        st.markdown(line)

ui.section("Surplus de rendement sur 5 ans glissants", "Au-dessus de zéro : la stratégie a fait mieux que le Buy & "
                                                        "Hold sur les 5 années qui précèdent.")
choices = [k for k in items if k != "benchmark"]
selected = st.pills("Stratégies", choices, selection_mode="multi", default=[study["followed"]] if study["followed"]
                    in choices else choices[:1], format_func=lambda k: items[k]["label"], key="rob_choice")
frames = []
for key in selected or []:
    rolling = items[key].get("rolling")
    if rolling:
        frames.append(pd.DataFrame({"date": pd.to_datetime(list(rolling["excess_series"])),
                                    "surplus / an": list(rolling["excess_series"].values()),
                                    "stratégie": items[key]["label"]}))
if frames:
    data = pd.concat(frames)
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(strokeDash=[4, 4], color="#64748b").encode(y="y:Q")
    st.altair_chart(ui.line_chart(data, x="date", y="surplus / an", color="stratégie", percent=True) + zero)

meta = study.get("meta_selection")
if meta:
    ui.section("Et si l'on changeait de stratégie chaque année ?")
    ui.kpis([
        {"label": "Méta-sélection (Sharpe)", "value": f"{meta['sharpe']:.2f}",
         "help": "Chaque année, la stratégie au meilleur Sharpe passé"},
        {"label": "Buy & Hold (Sharpe)", "value": f"{meta['benchmark_sharpe']:.2f}"},
        {"label": "Méta-sélection (rendement)", "value": ui.pct(meta["cagr"], 1)},
        {"label": "Buy & Hold (rendement)", "value": ui.pct(meta["benchmark_cagr"], 1)},
    ])
    st.caption("Courir après la stratégie qui a le mieux marché l'an dernier n'améliore pas le résultat : c'est un "
               "argument pour choisir une politique et s'y tenir.")
ui.disclaimer("Étude de recherche : elle ne modifie ni les réglages ni la stratégie suivie.")

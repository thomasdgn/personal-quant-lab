"""Page « Stratégies » : fiches pédagogiques et mesures de chaque stratégie du registre."""

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from app import ui
from app.planning import load_robustness, load_stress_study
from src.strategy_cards import CARDS, card_view

SHORT = {"benchmark": "Buy & Hold", "momentum": "Momentum", "momentum_vt": "Momentum + VT",
         "inverse_vol": "Inverse volatilité", "static_80_20": "80/20", "static_60_40": "60/40",
         "dual_momentum": "Dual momentum", "top3_trend": "Top 3 tendance", "core_satellite": "Cœur / satellite",
         "allocation_fixe": "Allocation fixe"}

ui.page_header("Stratégies", "Comment fonctionne chaque stratégie, ce qu'elle demande, et ce qu'elle a donné sur "
                             "près de 20 ans (historique long, partiellement synthétique).", icon=":material/menu_book:")

robustness, stress = load_robustness(), load_stress_study()
if robustness is None:
    st.info("Mesures absentes : les fiches s'affichent sans chiffres.", icon=":material/info:")
    st.code("python main.py robustness\npython main.py stress", language="bash")

views = {name: card_view(name, robustness, stress) for name in CARDS}
rows = []
for name, view in views.items():
    m = view["mesures"] or {}
    stats = m.get("stats") or {}
    rows.append({"stratégie": SHORT[name], "temps": view["temps"], "complexité": view["complexite"],
                 "fiabilité": m.get("fiabilite", "n/a"),
                 "surperformance": (m.get("surperformance") or {}).get("verdict", "référence" if name == "benchmark" else "n/a"),
                 "protection": (m.get("protection") or {}).get("verdict", "référence" if name == "benchmark" else "n/a"),
                 "rendement / an": stats.get("cagr"), "pire baisse": stats.get("max_drawdown"),
                 "pire 5 ans (/an)": stats.get("worst_5y_cagr")})
with st.container(border=True):
    st.markdown("**Vue d'ensemble**")
    st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
        "complexité": st.column_config.ProgressColumn(format="%d / 4", min_value=0, max_value=4),
        "rendement / an": st.column_config.NumberColumn(format="percent"),
        "pire baisse": st.column_config.NumberColumn(format="percent"),
        "pire 5 ans (/an)": st.column_config.NumberColumn(format="percent")})
    st.caption("Fiabilité : tient-elle quand on change de période, de réglage ou de frais ? Surperformance : bat-elle "
               "le Buy & Hold de façon prouvée ? Protection : limite-t-elle les baisses ?")

choice = st.pills("Stratégie", list(CARDS), format_func=SHORT.get, default="momentum_vt", key="strategy_choice") \
    or "momentum_vt"
view = views[choice]
m = view["mesures"]

with st.container(horizontal=True, vertical_alignment="center"):
    st.markdown(f"### {view['titre']}")
    if m:
        ui.badge(f"fiabilité : {m['fiabilite']}", color=ui.VERDICT_COLORS.get(m["fiabilite"]))
st.markdown(f"_{view['resume']}_")
with st.container(horizontal=True, gap="small"):
    st.badge(view["temps"], icon=":material/schedule:", color="gray")
    st.badge(f"complexité {view['complexite']}/4", icon=":material/tune:", color="gray")
    st.badge(f"{view['lignes']} ligne(s)", icon=":material/stacks:", color="gray")
    if m and m["surperformance"]:
        ui.badge(f"surperformance : {m['surperformance']['verdict']}",
                 color=ui.VERDICT_COLORS.get(m["surperformance"]["verdict"]))
        ui.badge(f"protection : {m['protection']['verdict']}", color=ui.VERDICT_COLORS.get(m["protection"]["verdict"]))
if m:
    s = m["stats"]
    ui.kpis([
        {"label": "Rendement annuel", "value": ui.pct(s["cagr"], 1)},
        {"label": "Sharpe", "value": "n/a" if s["sharpe"] is None else f"{s['sharpe']:.2f}",
         "help": "Rendement par unité de risque (plus haut = mieux)"},
        {"label": "Pire baisse", "value": ui.pct(s["max_drawdown"])},
        {"label": "Pire année", "value": ui.pct(s["worst_year"])},
        {"label": "Pire période de 5 ans", "value": f"{ui.pct(s.get('worst_5y_cagr'), 1)} / an"},
        {"label": "Part investie en moyenne", "value": ui.pct(s.get("avg_exposure"))},
    ])

tabs = st.tabs([":material/school: Comment ça marche", ":material/show_chart: Performances",
                ":material/thunderstorm: Crises", ":material/verified: Robustesse"])
with tabs[0]:
    st.markdown(f"**Principe.** {view['principe']}")
    st.markdown("**Règles exactes**")
    for i, rule in enumerate(view["regles"], 1):
        st.markdown(f"{i}. {rule}")
    left, right = st.columns(2)
    with left, st.container(border=True, height="stretch"):
        st.markdown("**:material/thumb_up: Forces**")
        for x in view["forces"]:
            st.markdown(f"- {x}")
    with right, st.container(border=True, height="stretch"):
        st.markdown("**:material/thumb_down: Faiblesses**")
        for x in view["faiblesses"]:
            st.markdown(f"- {x}")
    st.markdown(f"**Pour qui ?** {view['pour_qui']}")
    st.markdown("**Erreurs fréquentes** : " + " ; ".join(view["erreurs"]))
    if m and m["surperformance"]:
        st.caption(f"Surperformance : {m['surperformance']['text']}  \nProtection : {m['protection']['text']}")

series = (robustness or {}).get("series")
with tabs[1]:
    if not series or choice not in series:
        st.info("Séries absentes : `python main.py robustness`.")
    else:
        frame = pd.DataFrame({k: v for k, v in series.items() if k != "dates"},
                             index=pd.to_datetime(series["dates"]))[[choice, "benchmark"]].astype(float)
        frame = frame.rename(columns={choice: SHORT[choice], "benchmark": "Buy & Hold"})
        frame = frame.loc[:, ~frame.columns.duplicated()]
        growth = (1 + frame.fillna(0)).cumprod()
        drawdown = growth / growth.cummax() - 1
        st.markdown("**Valeur de 100 € investis** (frais inclus)")
        st.altair_chart(ui.line_chart((growth * 100).reset_index(names="date").melt("date", var_name="stratégie",
                                                                                  value_name="valeur"),
                                      x="date", y="valeur", color="stratégie", euros=True))
        st.markdown("**Baisse depuis le plus haut**")
        dd = drawdown.reset_index(names="date").melt("date", var_name="stratégie", value_name="baisse")
        st.altair_chart(alt.Chart(dd).mark_area(opacity=0.35, line=True).encode(
            x=alt.X("date:T", title=None), y=alt.Y("baisse:Q", title=None, axis=alt.Axis(format="%"), stack=None),
            color=alt.Color("stratégie:N", title=None, legend=alt.Legend(orient="bottom")),
            tooltip=["date:T", "stratégie:N", alt.Tooltip("baisse:Q", format=".1%")]).properties(height=220))
        yearly = (1 + frame.fillna(0)).groupby(frame.index.year).prod() - 1
        years = yearly.reset_index(names="année").melt("année", var_name="stratégie", value_name="rendement")
        st.markdown("**Rendement par année civile**")
        st.altair_chart(alt.Chart(years).mark_bar().encode(
            x=alt.X("année:O", title=None), xOffset="stratégie:N",
            y=alt.Y("rendement:Q", title=None, axis=alt.Axis(format="%")),
            color=alt.Color("stratégie:N", title=None, legend=alt.Legend(orient="bottom")),
            tooltip=["année:O", "stratégie:N", alt.Tooltip("rendement:Q", format=".1%")]).properties(height=240))
        st.caption(f"Historique {robustness['start'][:7]} → {robustness['end'][:7]} ; première année partielle.")
with tabs[2]:
    crises = [c for c in view["crises"] if c["actif"]]
    if not crises:
        st.info("Données de crise absentes : `python main.py stress`.")
    else:
        frame = pd.DataFrame(crises)
        long = pd.concat([frame.assign(série=SHORT[choice], baisse=frame["drawdown_max"]),
                          frame.assign(série="Buy & Hold", baisse=frame["drawdown_benchmark"])])
        long["baisse"] = long["baisse"].astype(float)
        st.altair_chart(alt.Chart(long).mark_bar().encode(
            y=alt.Y("fenêtre:N", title=None, sort=list(frame["fenêtre"]), axis=alt.Axis(labelLimit=260)),
            yOffset="série:N", x=alt.X("baisse:Q", title="pire baisse pendant la crise", axis=alt.Axis(format="%")),
            color=alt.Color("série:N", title=None, legend=alt.Legend(orient="bottom")),
            tooltip=["fenêtre", "série", alt.Tooltip("baisse:Q", format=".1%")]).properties(height=360))
        synthetic = [c["fenêtre"] for c in crises if (c["part_synthetique"] or 0) > 0.5]
        if synthetic:
            st.caption("Données majoritairement synthétiques (proxys) : " + ", ".join(synthetic) + ".")
with tabs[3]:
    if not m:
        st.info("Mesures absentes : `python main.py robustness`.")
    else:
        ui.check_list([{"niveau": "ok" if c["ok"] else ("reserve" if c["ok"] is None else "ko"),
                        "message": f"{c['critère']} — {c['détail']}"} for c in m["criteres"]])
        st.markdown("**Par sous-période de 5 ans**")
        st.dataframe(pd.DataFrame(m["sous_periodes"]), hide_index=True, column_config={
            "cagr": st.column_config.NumberColumn("rendement / an", format="percent"),
            "sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
            "max_drawdown": st.column_config.NumberColumn("pire baisse", format="percent"),
            "n_months": st.column_config.NumberColumn("mois"),
            "part_synthetique": st.column_config.ProgressColumn("part synthétique", format="percent", min_value=0,
                                                                max_value=1)})
        grid = m.get("grille")
        if grid:
            st.markdown(f"**Réglages testés ({grid['n_configs']})** — défaut `{grid['default']}` classé "
                        f"{grid['default_rank']}/{grid['n_configs']} ; centre du plateau `{grid['plateau']}`.")
            table = pd.DataFrame(grid["table"])
            table["défaut"] = np.where(table["params"] == grid["default"], "◀ défaut", "")
            st.dataframe(table, hide_index=True, height=260, column_config={
                "sharpe": st.column_config.NumberColumn(format="%.2f"),
                "cagr": st.column_config.NumberColumn("rendement / an", format="percent"),
                "max_drawdown": st.column_config.NumberColumn("pire baisse", format="percent")})
            wf = grid.get("walk_forward") or {}
            if wf.get("sharpe") is not None:
                st.caption(f"Walk-forward (réglage choisi chaque année sur le passé seulement) depuis {wf['start'][:7]} : "
                           f"Sharpe {wf['sharpe']:.2f} contre {wf['default_sharpe_same_months']:.2f} pour le défaut. "
                           "Aucun réglage n'est modifié automatiquement.")
ui.disclaimer("Fiches pédagogiques : elles décrivent des mécanismes, pas des recommandations.")

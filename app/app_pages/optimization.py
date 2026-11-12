"""Page « Frais et rendement » : audit des frais et gains / pertes des options plus risquées."""

import altair as alt
import pandas as pd
import streamlit as st

from app import ui
from app.planning import fee_audit_view, max_return_view
from src.max_return import conclusion_lines

ui.page_header("Frais et rendement", "Ce que te coûtent vraiment les frais, et ce que rapporterait (ou coûterait) "
                                     "chaque cran de risque en plus.", icon=":material/speed:")

tab_max, tab_fees = st.tabs([":material/trending_up: Rendement maximal", ":material/receipt_long: Frais"])

with tab_max:
    try:
        study = max_return_view()
    except FileNotFoundError:
        ui.empty_state("L'historique long est nécessaire pour cette étude.", "python main.py refresh-data --long")
        study = None
    if study:
        st.warning("Étude **pédagogique**, pas une recommandation : plus de rendement espéré veut toujours dire des "
                   "baisses plus fortes. Le levier est simulé mensuellement (pertes réelles plus fortes) et la "
                   "fenêtre 2005-2026 ne contient pas le krach du Nasdaq de 2000-2002 (−80 %).",
                   icon=":material/warning:")
        keys = list(study["scenarios"])
        choice = st.segmented_control("Hypothèse de rendement", keys,
                                      format_func=lambda k: study["scenarios"][k]["label"],
                                      default="central" if "central" in keys else keys[0], required=True,
                                      key="max_scenario") or keys[0]
        rows = study["scenarios"][choice]["rows"]
        frame = pd.DataFrame([{"option": o.label, **rows[o.key]} for o in study["options"]])
        frame["risque"] = pd.cut(frame["prob_ruin"], [-0.01, 0.2, 0.5, 1.0],
                                 labels=["modéré", "élevé", "extrême"]).astype(str)
        order = frame["option"].tolist()
        colors = alt.Scale(domain=["modéré", "élevé", "extrême"], range=["#16a34a", "#f59e0b", "#dc2626"])
        base = alt.Chart(frame).encode(y=alt.Y("option:N", title=None, sort=order, axis=alt.Axis(labelLimit=300)))
        gains = alt.layer(
            base.mark_rule(strokeWidth=8, opacity=0.35, strokeCap="round").encode(
                x=alt.X("p10:Q", title="valeur nette à l'horizon (€ d'aujourd'hui)", axis=ui.euro_axis()),
                x2="p90:Q", color=alt.Color("risque:N", scale=colors, legend=alt.Legend(orient="bottom",
                                                                                       title="risque"))),
            base.mark_point(filled=True, size=140).encode(
                x="p50:Q", color=alt.Color("risque:N", scale=colors),
                tooltip=["option", alt.Tooltip("p10:Q", title="défavorable", format=",.0f"),
                         alt.Tooltip("p50:Q", title="médiane", format=",.0f"),
                         alt.Tooltip("p90:Q", title="favorable", format=",.0f")]),
            alt.Chart(pd.DataFrame({"x": [study["contributed"]]})).mark_rule(strokeDash=[4, 4], color="#64748b")
            .encode(x="x:Q"),
        ).properties(height=46 * len(frame), title="Gains possibles : 1 sur 10 défavorable, médiane, 1 sur 10 favorable")
        ruin = base.mark_bar(opacity=0.8).encode(
            x=alt.X("prob_ruin:Q", title="probabilité de perdre plus de 50 % en cours de route",
                    axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("risque:N", scale=colors, legend=None),
            tooltip=["option", alt.Tooltip("prob_ruin:Q", format=".0%"),
                     alt.Tooltip("drawdown_bad:Q", title="1 scénario sur 10 : pire baisse", format=".0%")],
        ).properties(height=46 * len(frame), title="Pertes possibles")
        with st.container(border=True):
            st.altair_chart(gains)
        with st.container(border=True):
            st.altair_chart(ruin)
        st.dataframe(frame[["option", "p10", "p50", "p90", "implied_return", "drawdown_median", "drawdown_bad",
                            "prob_ruin", "prob_loss"]], hide_index=True, column_config={
            "p10": st.column_config.NumberColumn("défavorable (1/10)", format="%.0f €"),
            "p50": st.column_config.NumberColumn("médiane", format="%.0f €"),
            "p90": st.column_config.NumberColumn("favorable (1/10)", format="%.0f €"),
            "implied_return": st.column_config.NumberColumn("rendement annuel", format="percent"),
            "drawdown_median": st.column_config.NumberColumn("pire baisse médiane", format="percent"),
            "drawdown_bad": st.column_config.NumberColumn("pire baisse (1/10)", format="percent"),
            "prob_ruin": st.column_config.ProgressColumn("P(perdre > 50 %)", format="percent", min_value=0,
                                                         max_value=1),
            "prob_loss": st.column_config.NumberColumn("P(finir sous le versé)", format="percent")})
        st.caption(f"{ui.eur(study['contributed'])} versés sur l'horizon. Scénarios central et défavorable : aucune "
                   "zone ni stratégie ne garde d'avance passée à risque égal.")
        with st.expander(":material/history: Le vrai passé de chaque option (2005-2026)"):
            hist = pd.DataFrame([{"option": o.label, **{k: v for k, v in study["history"][o.key].items()
                                                         if k != "windows"}} for o in study["options"]])
            st.dataframe(hist, hide_index=True, column_config={
                "cagr": st.column_config.NumberColumn("rendement annuel", format="percent"),
                "max_drawdown": st.column_config.NumberColumn("pire baisse", format="percent"),
                "worst_year": st.column_config.NumberColumn("pire année", format="percent"),
                "best_year": st.column_config.NumberColumn("meilleure année", format="percent")})
        ui.check_list([{"niveau": "reserve", "message": line} for line in conclusion_lines(study, choice)])

with tab_fees:
    try:
        audit = fee_audit_view()
    except (FileNotFoundError, ValueError, KeyError) as exc:
        ui.empty_state(f"Audit indisponible : {exc}")
        audit = None
    if audit:
        base_row = audit["brokers"][audit["current"]]
        ter = audit["ter"]["Ton allocation"]
        ui.kpis([
            {"label": "Frais d'ordre / an", "value": ui.eur(base_row["fees_per_year"]),
             "help": f"{base_row['orders_per_year']:.1f} ordres par an, {base_row['fee_rate']:.2%} des versements"},
            {"label": f"Valeur perdue en {audit['horizon_years']} ans (ordres)",
             "value": ui.eur(base_row["value_lost"])},
            {"label": "Frais des ETF", "value": "n/a" if ter["ter_pct"] is None else f"{ter['ter_pct']:.3f} %/an",
             "help": f"Valeur perdue sur l'horizon : {ui.eur(ter['value_lost'])}"},
            {"label": "Impôt évité par le PEA", "value": ui.eur(audit["taxes"]["saving"]),
             "help": "Face à un compte-titres, si tu gardes le PEA plus de 5 ans"},
        ])
        brokers = pd.DataFrame([{"barème": name + (" (le tien)" if name == audit["current"] else ""),
                                 "ordres / an": row["orders_per_year"], "frais / an": row["fees_per_year"],
                                 "% des versements": row["fee_rate"], "valeur perdue": row["value_lost"]}
                                for name, row in sorted(audit["brokers"].items(),
                                                        key=lambda kv: kv[1]["fees_per_year"])])
        st.dataframe(brokers, hide_index=True, column_config={
            "ordres / an": st.column_config.NumberColumn(format="%.1f"),
            "frais / an": st.column_config.NumberColumn(format="%.0f €"),
            "% des versements": st.column_config.NumberColumn(format="percent"),
            "valeur perdue": st.column_config.NumberColumn(f"valeur perdue en {audit['horizon_years']} ans",
                                                           format="%.0f €")})
        st.caption(f"Plan de versement rejoué aux prix actuels, rendement supposé {audit['annual_return']:.1%}/an. "
                   "Les barèmes de comparaison sont des tarifs types, à vérifier chez les courtiers.")
ui.disclaimer()

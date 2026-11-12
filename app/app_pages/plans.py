"""Page « Plans d'investissement » : comparaison et détail des plans simulés pour le profil."""

import altair as alt
import pandas as pd
import streamlit as st

from app import ui
from app.planning import load_profile_or_example, plan_study, scenario_options
from src.investor_profile import TIME_BUDGETS
from src.plans_report import ENVELOPE_LABELS, POCKET_LABELS, pocket_content
from src.taxes import ENVELOPE_RULES

ui.page_header("Plans d'investissement", "Plusieurs façons d'investir ton versement, simulées sur l'historique : "
                                         "ce que l'on peut attendre, dans les bons et les mauvais scénarios.",
               icon=":material/route:")

profile, is_example = load_profile_or_example()
if is_example:
    st.info("Profil d'exemple : remplis « Mon profil » pour des plans calibrés sur toi.", icon=":material/person:")

with st.container(border=True):
    st.markdown("**:material/tune: Paramètres de simulation** — modifiables ici sans toucher à ton profil")
    c1, c2, c3, c4 = st.columns([1, 1, 1.4, 1.2], vertical_alignment="bottom")
    monthly = c1.number_input("Versement / mois (€)", min_value=10, step=10, value=int(profile.versement_mensuel_eur))
    capital = c2.number_input("Départ (€)", min_value=0, step=100, value=int(profile.capital_initial_eur))
    years = c3.slider("Horizon (années)", 3, 40, int(profile.horizon_ans))
    goal = c4.number_input("Objectif (€)", min_value=0, step=5000,
                           value=int(profile.objectif_capital_eur or 0),
                           help="Capital visé en euros d'aujourd'hui ; 0 = pas d'objectif chiffré")
    try:
        scenarios, default_scenario = scenario_options()
    except FileNotFoundError:
        ui.empty_state("L'historique long sert à simuler les plans : il est absent.", "python main.py refresh-data --long")
        st.stop()
    scenario_key = st.segmented_control(
        "Hypothèse de rendement", list(scenarios), format_func=lambda k: scenarios[k].label,
        default=default_scenario, required=True, key="plan_scenario",
        help="Historique : rejoue 2005-2026 (très favorable aux actions). Central / défavorable : mêmes krachs, "
             "rendement moyen plus modeste et aucune surperformance supposée des stratégies actives.") \
        or default_scenario
    st.caption(scenarios[scenario_key].description)

data = profile.to_dict()
data.update({"versement_mensuel_eur": float(monthly), "capital_initial_eur": float(capital), "horizon_ans": int(years),
             "objectif_capital_eur": float(goal) or None})
study = plan_study(data, scenario=scenario_key)

results, ranking = study["results"], study["ranking"]
first = results[ranking[0]]["simulation"]
st.caption(f"{first['n_sims']} scénarios par plan, tirés par blocs de 12 mois dans l'historique {study['window'][0][:7]} → "
           f"{study['window'][1][:7]} (partiellement synthétique avant la cotation des ETF PEA). "
           f"Versé au total : {ui.eur(first['contributed'])}. Montants nets d'impôts, en euros d'aujourd'hui. "
           f"Scénario : **{study['scenario'].label}**.")

# --------------------------------------------------------------------------- #
# Comparaison
# --------------------------------------------------------------------------- #
ui.section("Comparaison", "Point : scénario médian. Barre : 80 % des scénarios (du défavorable au favorable).")
rows = []
for pid in ranking:
    item = results[pid]
    sim, hist = item["simulation"], item["historical"]
    final = sim["final"]
    rows.append({
        "plan": item["plan"].nom, "adéquation": item["fit"]["status"], "temps": TIME_BUDGETS[item["plan"].temps],
        "défavorable": final["net_real"]["p10"], "médiane": final["net_real"]["p50"],
        "favorable": final["net_real"]["p90"], "revenu / mois": final["income_real_monthly"]["p50"],
        "pire baisse médiane": sim["drawdown"]["p50"], "risque de dépasser ta limite": sim["drawdown"]["prob_beyond_tolerance"],
        "rendement annuel": sim["implied_return_median"],
        "vrai passé (médiane)": hist["net_real"]["median"] if hist["available"] else None,
        "modèle vs passé": (item.get("model_check") or {}).get("status", "n/a"),
    })
table = pd.DataFrame(rows)
with st.container(border=True):
    st.altair_chart(ui.range_chart(table, label="plan", low="défavorable", mid="médiane", high="favorable",
                                   color="adéquation", reference=first["contributed_real"],
                                   x_title="valeur nette à l'horizon (€ d'aujourd'hui) — pointillés : total versé"))
st.dataframe(table, hide_index=True, column_config={
    **{c: st.column_config.NumberColumn(c, format="%.0f €") for c in
       ("défavorable", "médiane", "favorable", "revenu / mois", "vrai passé (médiane)")},
    "pire baisse médiane": st.column_config.NumberColumn(format="percent"),
    "risque de dépasser ta limite": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
    "rendement annuel": st.column_config.NumberColumn(format="percent"),
})
st.caption("Tri : adéquation à ton profil, puis médiane. « Revenu / mois » : ce que le capital net permettrait de "
           "retirer chaque mois sans l'épuiser (règle des 3,5 %). « Vrai passé » : le plan lancé à chaque date de "
           "départ possible de l'historique. « Modèle vs passé » : la médiane du vrai passé tombe-t-elle au cœur de la "
           "distribution simulée sur le même historique ? Les seuils d'adéquation sont des conventions.")

sensitivity = study.get("sensitivity")
if sensitivity:
    ui.section("Sensibilité aux hypothèses", "Médiane à l'horizon selon l'hypothèse de rendement : l'écart entre les "
                                             "scénarios pèse souvent plus que le choix du plan.")
    rows = [{"plan": results[pid]["plan"].nom, "scénario": values["label"], "médiane": values["p50"],
             "défavorable": values["p10"]}
            for pid in ranking for values in sensitivity[pid].values()]
    frame = pd.DataFrame(rows)
    with st.container(border=True):
        st.altair_chart(alt.Chart(frame).mark_point(filled=True, size=120).encode(
            y=alt.Y("plan:N", title=None, sort=[results[p]["plan"].nom for p in ranking],
                    axis=alt.Axis(labelLimit=320)),
            x=alt.X("médiane:Q", title="valeur nette médiane (€ d'aujourd'hui)", axis=ui.euro_axis()),
            color=alt.Color("scénario:N", title=None, legend=alt.Legend(orient="bottom")),
            tooltip=["plan", "scénario", alt.Tooltip("médiane:Q", format=",.0f"),
                     alt.Tooltip("défavorable:Q", format=",.0f")],
        ).properties(height=max(160, 46 * len(ranking))))

# --------------------------------------------------------------------------- #
# Détail
# --------------------------------------------------------------------------- #
ui.section("Détail d'un plan")
names = {pid: results[pid]["plan"].nom for pid in ranking}
choice = st.pills("Plan", ranking, format_func=names.get, default=ranking[0], label_visibility="collapsed",
                  key="plan_choice") or ranking[0]
item = results[choice]
plan, sim, hist, fit = item["plan"], item["simulation"], item["historical"], item["fit"]
final = sim["final"]

with st.container(horizontal=True, vertical_alignment="center"):
    st.markdown(f"### {plan.nom}")
    ui.badge(fit["status"])
    st.badge(f"{TIME_BUDGETS[plan.temps]}", icon=":material/schedule:", color="gray")
    st.badge(f"complexité {plan.complexite}/4", icon=":material/tune:", color="gray")
st.markdown(f"{plan.resume}  \n**Pour qui ?** {plan.pour_qui}")
kpi_items = [
    {"label": "Scénario médian", "value": ui.eur(final["net_real"]["p50"]),
     "help": "Valeur nette à l'horizon, en euros d'aujourd'hui"},
    {"label": "Défavorable (1 sur 10)", "value": ui.eur(final["net_real"]["p10"])},
    {"label": "Favorable (1 sur 10)", "value": ui.eur(final["net_real"]["p90"])},
    {"label": "Revenu mensuel médian", "value": ui.eur(final["income_real_monthly"]["p50"]),
     "help": "Retrait soutenable : capital net × 3,5 % / 12"},
    {"label": "Pire baisse (médiane)", "value": ui.pct(sim["drawdown"]["p50"]),
     "help": f"1 scénario sur 10 pire que {ui.pct(sim['drawdown']['p10'])}"},
]
if sim["prob_goal"] is not None:
    kpi_items.append({"label": "Chance d'atteindre l'objectif", "value": ui.pct(sim["prob_goal"])})
ui.kpis(kpi_items)

check = item.get("model_check")
if check:
    (st.warning if check["status"] == "divergent" else st.info)(
        f"Contrôle du modèle — {check['status']} : {check['text']}", icon=":material/rule:")

tab_proj, tab_past, tab_fit, tab_comp = st.tabs([":material/show_chart: Projection", ":material/history: Vrai passé",
                                                  ":material/fact_check: Adéquation", ":material/pie_chart: Composition et routine"])
with tab_proj:
    st.altair_chart(ui.fan_chart(sim["fan"], goal=sim["goal_real"]))
    st.caption("Bande claire : 80 % des scénarios ; bande foncée : 50 % ; trait : médiane ; pointillés : total versé "
               "(en euros d'aujourd'hui)" + (" ; ligne rouge : objectif." if sim["goal_real"] else "."))
    if sim["goal_curve"]:
        curve = pd.DataFrame({"année": [m / 12 for m in sim["fan"]["months"]], "probabilité": sim["goal_curve"]})
        st.markdown("**Probabilité d'avoir atteint l'objectif, année après année**")
        st.altair_chart(alt.Chart(curve).mark_area(opacity=0.35, line=True).encode(
            x=alt.X("année:Q"), y=alt.Y("probabilité:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
            tooltip=[alt.Tooltip("année:Q", format=".0f"), alt.Tooltip("probabilité:Q", format=".0%")]
        ).properties(height=200))
    c1, c2, c3 = st.columns(3)
    c1.metric("Finir sous le total versé", ui.pct(sim["prob_loss"]), border=True)
    c2.metric("Perdre du pouvoir d'achat", ui.pct(sim["prob_real_loss"]), border=True)
    c3.metric("Frais d'ordre cumulés", ui.eur(sim["fees_total"]), border=True)
with tab_past:
    replay = item["replay"]
    frame = replay.reset_index(names="date").melt("date", var_name="série", value_name="euros")
    st.altair_chart(ui.line_chart(frame, x="date", y="euros", color="série", euros=True))
    st.caption(f"Le plan lancé en {replay.index[0]:%m/%Y} avec ton versement, sur les vrais rendements (euros courants).")
    if hist["available"]:
        c1, c2, c3 = st.columns(3)
        c1.metric("Pire départ", ui.eur(hist["net_real"]["min"]), help=f"départ en {hist['worst_start'][:7]}", border=True)
        c2.metric("Départ médian", ui.eur(hist["net_real"]["median"]), border=True)
        c3.metric("Meilleur départ", ui.eur(hist["net_real"]["max"]), help=f"départ en {hist['best_start'][:7]}",
                  border=True)
        st.caption(f"{hist['n_windows']} dates de départ de {hist['first_start'][:7]} à {hist['last_start'][:7]}, "
                   "chacune suivie sur tout l'horizon (valeur nette, euros d'aujourd'hui).")
    else:
        st.info(f"Relecture sur tout l'horizon impossible : {hist['reason']}")
    if plan.has_crypto:
        st.warning("Le vrai passé contient la hausse exceptionnelle du bitcoin depuis 2015 ; les projections ne "
                   "l'extrapolent volontairement pas.", icon=":material/warning:")
with tab_fit:
    ui.check_list(fit["checks"])
with tab_comp:
    left, right = st.columns([3, 2])
    with left:
        pockets = pd.DataFrame([{"poche": p.nom, "enveloppe": ENVELOPE_LABELS[p.enveloppe], "part": p.part,
                                 "contenu": f"{POCKET_LABELS[p.type]} : {pocket_content(p)}",
                                 "par mois": monthly * p.part} for p in plan.poches])
        st.dataframe(pockets, hide_index=True, column_config={
            "part": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
            "par mois": st.column_config.NumberColumn(format="%.0f €")})
        st.markdown("**Routine mensuelle**")
        for i, step in enumerate(plan.routine, 1):
            st.markdown(f"{i}. {step}")
        if plan.esg:
            st.caption(f":material/eco: {plan.esg}")
    with right:
        envelopes = pd.DataFrame([{"enveloppe": ENVELOPE_LABELS[k], "versé": v["invested"], "net médian": v["median_net"]}
                                  for k, v in sim["by_envelope"].items()])
        st.dataframe(envelopes, hide_index=True, column_config={
            c: st.column_config.NumberColumn(format="%.0f €") for c in ("versé", "net médian")})
        st.caption("Net médian en euros courants, après la fiscalité de chaque enveloppe.")
        for env in dict.fromkeys(p.enveloppe for p in plan.poches):
            st.caption(f"**{ENVELOPE_LABELS[env]}** — {ENVELOPE_RULES[env]}")

with st.expander(":material/help: Méthode, hypothèses et limites"):
    hyp = study["hypotheses"]
    st.markdown(
        f"- **Bootstrap par blocs** : chaque scénario enchaîne des blocs de {hyp.bloc_mois} mois tirés au hasard dans "
        "l'historique ; les crises restent groupées et les poches gardent leurs corrélations.\n"
        f"- **Inflation** {hyp.inflation_pct:.1f} %/an ; **fonds euros** {hyp.fonds_euros_taux_pct:.1f} %/an ; frais des "
        f"unités de compte {hyp.av_frais_gestion_uc_pct:.1f} %/an ; **crypto** recentrée sur "
        f"{hyp.crypto_rendement_annuel_pct:.0f} %/an (la hausse passée n'est pas extrapolée).\n"
        "- **Fiscalité** : retrait total à l'horizon (hypothèse prudente) ; PEA après 5 ans : prélèvements sociaux ; "
        "assurance-vie après 8 ans : abattement ; CTO et crypto : prélèvement forfaitaire. Plafond PEA : le surplus "
        "bascule sur un CTO.\n"
        "- **Limites** : le passé récent a été favorable aux actions mondiales ; données partiellement synthétiques ; "
        "versements supposés constants. Hypothèses modifiables dans `config/plans.yaml`.")
    for note in study["notes"]:
        st.caption(note)
ui.disclaimer()

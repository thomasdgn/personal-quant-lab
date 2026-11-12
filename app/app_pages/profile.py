"""Page « Mon profil » : questionnaire investisseur et repères déduits."""

import streamlit as st

from app import ui
from app.planning import PROFILE, load_profile_or_example, plan_study
from src.investor_profile import (
    ENVELOPE_LABELS,
    EXPERIENCES,
    OBJECTIVES,
    REACTIONS,
    TIME_BUDGETS,
    ZONES,
    assess_profile,
    profile_from_dict,
    save_profile,
)

ui.page_header("Mon profil", "Tes réponses servent uniquement à confronter les plans simulés à tes préférences. "
                             "Elles restent sur ton ordinateur (config/profil.yaml, jamais versionné).",
               icon=":material/person:")

profile, is_example = load_profile_or_example()
if is_example:
    st.info("Aucun profil enregistré : les valeurs ci-dessous sont celles du modèle.", icon=":material/info:")

assessment = assess_profile(profile)
ui.kpis([
    {"label": "Classe de risque", "value": assessment.risk_class},
    {"label": "Baisse supportable retenue", "value": f"{assessment.drawdown_tolerance:.0%}",
     "help": f"Déclarée : {assessment.declared_drawdown:.0%}"},
    {"label": "Complexité acceptable", "value": f"{assessment.max_complexity}/4"},
    {"label": "Horizon", "value": f"{profile.horizon_ans} ans", "help": f"horizon {assessment.horizon_class}"},
])
if assessment.notes:
    with st.container(border=True):
        st.markdown("#### :material/lightbulb: Ce que ton profil implique")
        for note in assessment.notes:
            st.markdown(f"- {note}")

ui.section("Questionnaire", "Modifie tes réponses puis enregistre : les plans se recalculent aussitôt.")
with st.form("profil"):
    c1, c2, c3 = st.columns(3)
    capital = c1.number_input("Capital de départ (€)", min_value=0, step=100, value=int(profile.capital_initial_eur),
                              help="Hors épargne de précaution.")
    monthly = c2.number_input("Versement mensuel (€)", min_value=0, step=10, value=int(profile.versement_mensuel_eur))
    horizon = c3.slider("Horizon (années)", 1, 40, int(profile.horizon_ans))
    objective = st.radio("Objectif principal", list(OBJECTIVES), format_func=OBJECTIVES.get, horizontal=True,
                         index=list(OBJECTIVES).index(profile.objectif))
    goal = st.number_input("Capital visé à l'horizon, en euros d'aujourd'hui (0 = pas de cible)", min_value=0,
                           step=1000, value=int(profile.objectif_capital_eur or 0))
    reaction = st.radio("Ton portefeuille perd 30 % en quelques mois. Que fais-tu ?", list(REACTIONS),
                        format_func=REACTIONS.get, horizontal=True, index=list(REACTIONS).index(profile.reaction_baisse))
    time_budget = st.segmented_control("Temps consacré chaque mois", list(TIME_BUDGETS), format_func=TIME_BUDGETS.get,
                                       default=profile.temps_mensuel, required=True)
    zones = st.pills("Zones à privilégier", list(ZONES), format_func=ZONES.get, selection_mode="multi",
                     default=list(profile.zones))
    c1, c2, c3 = st.columns(3)
    crypto = c1.toggle("Petite poche crypto", value=profile.options.crypto)
    crypto_max = c1.slider("Plafond crypto (%)", 0, 20, int(profile.options.part_crypto_max_pct))
    esg = c2.toggle("Privilégier l'ESG / ISR", value=profile.options.esg)
    safety = c2.toggle("Poche sécurisée (obligations / fonds euros)", value=profile.options.securite)
    experience = c3.selectbox("Expérience", list(EXPERIENCES), format_func=EXPERIENCES.get,
                              index=list(EXPERIENCES).index(profile.experience))
    precaution = c3.toggle("Épargne de précaution constituée", value=profile.epargne_precaution_ok)
    st.markdown("**Enveloppes déjà ouvertes**")
    cols = st.columns(len(ENVELOPE_LABELS))
    envelopes = {}
    for col, (key, label) in zip(cols, ENVELOPE_LABELS.items(), strict=True):
        current = profile.enveloppes.get(key) or {}
        envelopes[key] = {**current, "ouvert": col.toggle(label, value=bool(current.get("ouvert")))}
    submitted = st.form_submit_button("Enregistrer mon profil", type="primary", icon=":material/save:")

if submitted:
    data = profile.to_dict()
    data.update({"capital_initial_eur": float(capital), "versement_mensuel_eur": float(monthly), "horizon_ans": horizon,
                 "objectif": objective, "objectif_capital_eur": float(goal) or None, "reaction_baisse": reaction,
                 "temps_mensuel": time_budget or profile.temps_mensuel, "zones": zones or ["monde"],
                 "options": {"crypto": crypto, "part_crypto_max_pct": float(crypto_max), "esg": esg, "securite": safety},
                 "experience": experience, "enveloppes": envelopes, "epargne_precaution_ok": precaution})
    try:
        new_profile = profile_from_dict(data, "questionnaire")
    except ValueError as exc:
        st.error(str(exc))
    else:
        save_profile(new_profile, PROFILE)
        plan_study.clear()
        st.toast("Profil enregistré.", icon=":material/check_circle:")
        st.rerun()

st.page_link("app_pages/plans.py", label="Voir les plans calculés pour ce profil", icon=":material/arrow_forward:")
ui.disclaimer("Repères indicatifs tirés de tes réponses, pas un conseil en investissement.")

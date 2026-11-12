"""Page « Accueil » : l'essentiel en un coup d'œil et la prochaine action."""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from app import ui
from app.data import POLICY, crash_rule_view, lab_status, load_snapshots, real_portfolio, target_allocation
from app.planning import load_profile_or_example, plan_study
from src.investor_profile import assess_profile

MONTHS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre")
today = date.today()
ui.page_header("Accueil", f"{today.day} {MONTHS_FR[today.month - 1]} {today.year} · l'essentiel de ton "
                          "investissement, sans jargon.", icon=":material/home:")

snapshots = load_snapshots()
snapshot = snapshots[-1][1] if snapshots else None
profile, is_example = load_profile_or_example()
assessment = assess_profile(profile)

try:
    status = lab_status()
except (ValueError, FileNotFoundError):
    status = None
try:
    portfolio = real_portfolio()
except ValueError:
    portfolio = {"perf": None, "has_transactions": False, "pea": {"alerts": []}}

# --------------------------------------------------------------------------- #
# Chiffres clés
# --------------------------------------------------------------------------- #
perf = portfolio["perf"]
policy = (snapshot or {}).get("policy") or {}
allocation = target_allocation(snapshot) if snapshot else pd.DataFrame()
invested = allocation.loc[allocation["actif"] != "CASH", "poids"].sum() if not allocation.empty else None
items = [
    {"label": "Portefeuille réel", "value": ui.eur(perf["final_value"]) if perf else "—",
     "delta": None if not perf or perf.get("mwr") is None else f"{perf['mwr']:+.1%} / an",
     "help": "Valeur de ton journal de transactions ; variation = rendement annuel de ton argent (TRI)."
     if perf else "Aucun journal : config/transactions.csv (modèle : transactions.example.csv)."},
    {"label": f"Allocation {snapshot['metadata']['report_month']}" if snapshot else "Allocation du mois",
     "value": "n/a" if invested is None else f"{invested:.0%} investi",
     "help": f"Stratégie suivie : {policy.get('label', 'n/a')} ; le reste attend en cash."},
    {"label": "Profil", "value": assessment.risk_class,
     "help": f"{ui.eur(profile.versement_mensuel_eur)} par mois · {profile.horizon_ans} ans · baisse supportable "
             f"retenue {assessment.drawdown_tolerance:.0%}" + (" (profil d'exemple)" if is_example else "")},
]
if status and status["data"].get("exists"):
    items.append({"label": "Données", "value": f"{status['data']['age_days']} j",
                  "help": f"Dernière séance : {status['data']['last_observation']}"})
regularity = portfolio.get("regularity")
if regularity:
    items.append({"label": "Mois versés", "value": f"{regularity['months_paid']}/{regularity['months']}",
                  "help": "Le seul indicateur qui compte la première année : as-tu versé chaque mois, y compris "
                          f"pendant les baisses ? Mois de baisse versés : {regularity['stress_months_paid']}/"
                          f"{regularity['stress_months']}."})
ui.kpis(items)

try:
    crash = crash_rule_view()
except ValueError:
    crash = None
if crash:
    box = st.error if crash["triggered"] else st.info
    drawdown = crash["current_drawdown"]
    state = (f"Baisse actuelle de ta stratégie : {drawdown:.0%} (seuil {-crash['threshold']:.0%})."
             if drawdown is not None else f"Seuil : baisse de {crash['threshold']:.0%} depuis le plus haut.")
    box(f"**Ta règle de krach{' — DÉCLENCHÉE, relis-la avant toute décision' if crash['triggered'] else ''}** : "
        f"« {crash['text']} »  \n{state}", icon=":material/anchor:")

if is_example:
    st.info("Profil d'exemple affiché : réponds au questionnaire pour des plans calibrés sur toi.",
            icon=":material/person:")
    st.page_link("app_pages/profile.py", label="Remplir mon profil", icon=":material/arrow_forward:")

# --------------------------------------------------------------------------- #
# À faire + allocation
# --------------------------------------------------------------------------- #
left, right = st.columns([3, 2], gap="medium")
with left, st.container(border=True, height="stretch"):
    st.markdown("#### :material/checklist: À faire")
    steps = [s for s in (status or {}).get("next_steps", []) if not s.startswith("Rien à faire")]
    if status is None:
        st.warning("État du lab indisponible.")
    elif not steps:
        st.success("Routine du mois terminée. Prochain rendez-vous : début du mois prochain.",
                   icon=":material/task_alt:")
    for step in steps:
        title, _, detail = step.partition(" : ")
        st.markdown(f":material/radio_button_unchecked: **{title}**" + (f" — `{detail}`" if detail else ""))
    st.markdown("**Routine mensuelle (≈ 30 min)**")
    st.markdown("1. `python main.py run-month --refresh-data --html`\n"
                "2. Lire le rapport du mois et noter ta décision dans le journal\n"
                "3. `python main.py plan-contribution --record`, puis passer les ordres **toi-même**\n"
                "4. Reporter les ordres exécutés dans `config/transactions.csv`")
with right, st.container(border=True, height="stretch"):
    st.markdown("#### :material/donut_large: Allocation proposée")
    if allocation.empty:
        ui.empty_state("Aucun rapport mensuel.", "python main.py run-month --refresh-data")
    else:
        st.caption(f"{policy.get('label', 'Stratégie suivie')} · à valider manuellement")
        try:
            from src.policy import load_policy

            current = load_policy(POLICY).strategie_suivie
        except ValueError:
            current = None
        if current and policy.get("followed") and current != policy.get("followed"):
            st.warning(f"Rapport produit avec l'ancienne politique ({policy.get('followed')}). Ta politique actuelle "
                       f"({current}) s'appliquera dès le prochain `run-month`.", icon=":material/update:")
        chart = allocation.assign(label=allocation["poids"].map(lambda v: f"{v:.0%}"))
        base = alt.Chart(chart).encode(theta=alt.Theta("poids:Q", stack=True),
                                       color=alt.Color("actif:N", title=None, legend=alt.Legend(orient="bottom")),
                                       tooltip=["actif", alt.Tooltip("poids:Q", format=".0%")])
        st.altair_chart(base.mark_arc(innerRadius=55, padAngle=0.02, cornerRadius=4).properties(height=220))

# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #
ui.section("Tes plans d'investissement", "Simulés pour ton profil (hypothèse de rendement centrale) : valeur nette "
                                        "à l'horizon, en euros d'aujourd'hui.")
try:
    study = plan_study(profile.to_dict())
except FileNotFoundError:
    study = None
    ui.empty_state("Historique long absent : il sert à simuler les plans.", "python main.py refresh-data --long")
if study:
    columns = st.columns(3, gap="small")
    for column, pid in zip(columns, study["ranking"][:3], strict=False):
        item = study["results"][pid]
        final = item["simulation"]["final"]["net_real"]
        with column, st.container(border=True, height="stretch"):
            st.markdown(f"**{item['plan'].nom}**")
            ui.badge(item["fit"]["status"])
            st.metric("Médiane à l'horizon", ui.eur(final["p50"]),
                      help=f"1 scénario sur 10 sous {ui.eur(final['p10'])}, 1 sur 10 au-dessus de {ui.eur(final['p90'])}.")
            st.caption(item["plan"].resume)
    st.page_link("app_pages/plans.py", label="Comparer tous les plans", icon=":material/arrow_forward:")

ui.disclaimer()

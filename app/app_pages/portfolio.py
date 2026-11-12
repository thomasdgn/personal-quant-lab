"""Page « Portefeuille réel » : performance, frais, jalons du PEA (données personnelles)."""

import altair as alt
import streamlit as st

from app import ui
from app.data import real_portfolio

ui.page_header("Portefeuille réel", "Ton argent réel, d'après ton journal de transactions (personnel, jamais versionné).", icon=":material/account_balance_wallet:")


def _eur(value: float) -> str:
    return f"{value:,.0f} €".replace(",", " ")


@st.cache_data(ttl=300, show_spinner="Valorisation du portefeuille réel…")
def cached_portfolio() -> dict:
    data = real_portfolio()
    perf = data["perf"]
    if perf is not None:
        perf = {k: v for k, v in perf.items() if k != "twr_monthly"}
    return {**data, "perf": perf}


try:
    data = cached_portfolio()
except ValueError as exc:
    st.error(f"Journal de transactions illisible : {exc}")
    st.stop()
perf, pea = data["perf"], data["pea"]
if data.get("empty_journal"):
    st.info("Journal créé mais encore vide : ajoute ton premier VERSEMENT puis tes ACHAT réels dans "
            "`config/transactions.csv` (format : `config/transactions.example.csv`).", icon=":material/info:")
elif not data["has_transactions"]:
    st.info("Aucun journal : copie `config/transactions.example.csv` en `config/transactions.csv` et reporte-y "
            "tes opérations réelles (versements, achats, frais).", icon=":material/info:")
elif perf is not None:
    mwr, twr = perf["mwr"], perf["comparison"].get("real_twr")
    with st.container(horizontal=True):
        st.metric("Valeur", _eur(perf["final_value"]), border=True)
        st.metric("Versé net", _eur(perf["net_contributions"]), border=True)
        st.metric("TRI annualisé", "n/a" if mwr is None else f"{mwr:+.2%}", border=True,
                  help="Rendement de ton argent, calendrier des versements compris")
        st.metric("TWR cumulé", "n/a" if twr is None else f"{twr:+.2%}", border=True,
                  help="Performance de la gestion, indépendante des versements")
        st.metric("Frais payés", f"{perf['fees_total']:,.2f} €".replace(",", " "), border=True)
    valuation = perf["valuation"].copy()
    valuation["versé cumulé"] = valuation["flux"].cumsum()
    chart = valuation[["valeur", "versé cumulé"]].reset_index(names="date").melt("date", var_name="série",
                                                                                   value_name="euros")
    with st.container(border=True):
        st.markdown("**Valeur vs versements cumulés**")
        st.altair_chart(alt.Chart(chart).mark_line(point=True).encode(
            x=alt.X("yearmonth(date):T", title=None), y=alt.Y("euros:Q", title="€"),
            color=alt.Color("série:N", title=None)))
    if perf.get("benchmark_same_flows_value") is not None:
        st.caption(f"Buy & Hold avec les mêmes versements : {_eur(perf['benchmark_same_flows_value'])}")

regularity = data.get("regularity")
if regularity:
    with st.container(border=True):
        st.markdown("**Régularité des versements**")
        c1, c2, c3 = st.columns(3)
        c1.metric("Mois versés", f"{regularity['months_paid']}/{regularity['months']}", border=True)
        c2.metric("Série en cours", f"{regularity['current_streak']} mois", border=True)
        c3.metric(f"Mois de baisse (> {regularity['stress_threshold']:.0%}) versés",
                  f"{regularity['stress_months_paid']}/{regularity['stress_months']}", border=True)
        if regularity["missed"]:
            st.caption("Mois sans versement : " + ", ".join(regularity["missed"]))

with st.container(border=True):
    st.markdown("**PEA**")
    used = pea.get("ceiling_used") or 0.0
    st.progress(min(used, 1.0), text=f"Versements {_eur(pea['contributions'])} / plafond {_eur(pea['ceiling'])}")
    if pea.get("five_year_date"):
        st.write(f"Ouvert le {pea['opening_date']} — 5 ans le **{pea['five_year_date']}** "
                 f"({pea['years_held']} ans d'ancienneté).")
    for alert in pea["alerts"]:
        st.warning(alert)

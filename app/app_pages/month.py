"""Page « Mois » : statut, allocation cible, alertes, performances et graphiques."""

import altair as alt
import pandas as pd
import streamlit as st

from app import ui
from app.data import _main_strategy as main_strategy
from app.data import alerts_table, figure_paths, load_snapshots, long_series, series_frame, target_allocation


def _pct(value: float | None, digits: int = 0) -> str:
    return "n/a" if value is None else f"{value:.{digits}%}"


snapshots = load_snapshots()
if not snapshots:
    st.warning("Aucun rapport mensuel. Lance d'abord : `python main.py run-month --refresh-data`.")
    st.stop()

months = [snapshot["metadata"]["report_month"] for _, snapshot in snapshots]
month = st.session_state.get("month", months[-1])
snapshot_path, snapshot = snapshots[months.index(month) if month in months else -1]
meta = snapshot["metadata"]
vt = snapshot.get("volatility_targeted_strategy") or {}
momentum = snapshot.get("momentum_strategy") or {}
risk = snapshot.get("risk") or {}

status = meta["pipeline_status"]
ui.page_header(f"Rapport {meta['report_month']}", f"Signal du {meta['signal_date']} · dernière séance "
               f"{meta['last_observation']} · généré le {meta['generated_at']} · schéma v{meta['schema_version']}",
               icon=":material/today:")
ui.badge(status)

with st.container(horizontal=True):
    st.metric("Actif Momentum", ", ".join(momentum.get("selected_assets") or []) or "cash", border=True)
    followed = main_strategy(snapshot)
    st.metric("Exposition proposée", _pct(followed.get("invested_exposure")), border=True,
              help=f"Stratégie suivie : {(snapshot.get('policy') or {}).get('label', 'Momentum + VT')}")
    st.metric("Volatilité réalisée", _pct(risk.get("realized_volatility"), 1),
              help=f"Cible : {_pct(risk.get('target_volatility'))}", border=True)
    st.metric("Drawdown courant VT", _pct(risk.get("vt_current_drawdown"), 1), border=True)

left, right = st.columns([1, 2])
with left, st.container(border=True):
    policy = snapshot.get("policy") or {}
    st.markdown("**Allocation cible (à valider manuellement)**")
    if policy:
        st.caption(f"Politique : {policy['label']} · drawdown max accepté {policy['max_drawdown_limit']:.0%}")
    allocation = target_allocation(snapshot)
    if allocation.empty:
        st.write("Aucune allocation.")
    else:
        st.dataframe(allocation, hide_index=True,
                     column_config={"poids": st.column_config.ProgressColumn("poids", format="percent",
                                                                             min_value=0, max_value=1)})
with right, st.container(border=True):
    st.markdown("**Alertes**")
    alerts = alerts_table(snapshot)
    if alerts.empty:
        st.success("Aucune alerte.")
    else:
        st.dataframe(alerts, hide_index=True)

series = series_frame(snapshot)
if not series.empty:
    equity = long_series(series, "equity")
    drawdown = long_series(series, "drawdown")
    selection = alt.selection_point(fields=["stratégie"], bind="legend")
    with st.container(border=True):
        st.markdown("**Capital théorique (frais inclus)**")
        st.altair_chart(
            alt.Chart(equity).mark_line().encode(
                x=alt.X("date:T", title=None), y=alt.Y("valeur:Q", title="€"),
                color=alt.Color("stratégie:N", title=None),
                opacity=alt.condition(selection, alt.value(1), alt.value(0.15)),
                tooltip=["date:T", "stratégie:N", alt.Tooltip("valeur:Q", format=",.0f")],
            ).add_params(selection).interactive(bind_y=False)
        )
    col1, col2 = st.columns(2)
    with col1, st.container(border=True):
        st.markdown("**Drawdown**")
        st.altair_chart(
            alt.Chart(drawdown).mark_line().encode(
                x=alt.X("date:T", title=None), y=alt.Y("valeur:Q", title=None, axis=alt.Axis(format="%")),
                color=alt.Color("stratégie:N", title=None),
                tooltip=["date:T", "stratégie:N", alt.Tooltip("valeur:Q", format=".1%")],
            )
        )
    with col2, st.container(border=True):
        st.markdown("**Exposition investie de la stratégie suivie**")
        exposure = series[["exposure", "held"]].reset_index()
        st.altair_chart(
            alt.Chart(exposure).mark_area(opacity=0.6, interpolate="step-after").encode(
                x=alt.X("date:T", title=None), y=alt.Y("exposure:Q", title=None, axis=alt.Axis(format="%"),
                                                       scale=alt.Scale(domain=[0, 1])),
                tooltip=["date:T", alt.Tooltip("exposure:Q", format=".0%"), alt.Tooltip("held:N", title="détenu")],
            )
        )
else:
    figures = figure_paths(snapshot, snapshot_path)
    if figures:
        st.caption("Snapshot antérieur au schéma 1.2 : graphiques statiques.")
        for path in figures.values():
            st.image(str(path))
    else:
        st.info("Pas de graphiques pour ce mois (rapport antérieur à leur introduction).")

with st.container(border=True):
    st.markdown("**Performances historiques (backtest, frais inclus)**")
    perf = pd.DataFrame([
        {"stratégie": s.get("name"), "CAGR": s.get("cagr"), "volatilité": s.get("annualized_volatility"),
         "Sharpe": s.get("sharpe"), "max drawdown": s.get("max_drawdown")}
        for s in (snapshot.get("benchmark"), momentum, vt) if s and s.get("enabled", True)
    ])
    st.dataframe(perf.style.format({"CAGR": "{:.2%}", "volatilité": "{:.2%}", "Sharpe": "{:.2f}",
                                    "max drawdown": "{:.2%}"}, na_rep="n/a"), hide_index=True)

markdown_path = snapshot_path.with_name(snapshot_path.name.replace("-report.json", "-report.md"))
if markdown_path.exists():
    with st.expander("Rapport Markdown complet"):
        st.markdown(markdown_path.read_text(encoding="utf-8").split("## Graphiques")[0])

strategies = snapshot.get("strategies") or {}
if strategies:
    with st.expander("Toutes les stratégies du registre (comparaison)"):
        rows = [{"stratégie": item["label"] + (" (suivie)" if name == (snapshot.get("policy") or {}).get("followed") else ""),
                 "exposition": item.get("invested_exposure"), "CAGR": item.get("cagr"), "Sharpe": item.get("sharpe"),
                 "max drawdown": item.get("max_drawdown"), "drawdown courant": item.get("current_drawdown")}
                for name, item in strategies.items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
            c: st.column_config.NumberColumn(c, format="percent") for c in
            ("exposition", "CAGR", "max drawdown", "drawdown courant")} | {
            "Sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f")})

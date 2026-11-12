"""Page « Politique » : stratégie suivie, garde-fous et contrôles (lecture seule)."""

import pandas as pd
import streamlit as st

from app import ui
from app.data import policy_view

ui.page_header("Politique d'investissement", "La stratégie que tu as choisi de suivre (`config/policy.yaml`) et ses garde-fous. Le laboratoire ne la modifie jamais.", icon=":material/policy:")

view = policy_view()
policy = view["policy"]
with st.container(horizontal=True):
    st.metric("Stratégie suivie", policy.strategie_suivie, border=True)
    st.metric("Drawdown max accepté", f"{policy.drawdown_max_accepte:.0%}", border=True)
    st.metric("Horizon", f"{policy.horizon_ans} ans", border=True)
    st.metric("Rééquilibrage", policy.reequilibrage, border=True)
if policy.strategie_suivie == "core_satellite":
    st.info(f"Cœur / satellite : {policy.part_coeur:.0%} benchmark + {1 - policy.part_coeur:.0%} {policy.satellite}.")
st.markdown(f"**Objectif** : {policy.objectif}")
if policy.allocation_fixe:
    st.markdown("**Allocation fixe** : " + " · ".join(f"{t} {w:.0%}" for t, w in policy.allocation_fixe.items())
                + (f" (plan « {policy.plan_suivi} »)" if policy.plan_suivi else ""))
if policy.regle_krach:
    st.info(f"**Règle de krach** (seuil {policy.seuil_krach:.0%}) : « {policy.regle_krach} »", icon=":material/anchor:")

for check in view["checks"]:
    (st.warning if check["level"] == "WARNING" else st.info)(check["message"])

snapshot = view["snapshot"]
strategies = (snapshot or {}).get("strategies") or {}
if strategies:
    followed = strategies.get(policy.strategie_suivie)
    if followed:
        with st.container(border=True):
            st.markdown(f"**Allocation proposée ({snapshot['metadata']['report_month']})** — {followed['label']}")
            weights = pd.DataFrame([{"actif": k, "poids": v} for k, v in followed["target_weights"].items() if v > 1e-9])
            st.dataframe(weights, hide_index=True, column_config={
                "poids": st.column_config.ProgressColumn("poids", format="percent", min_value=0, max_value=1)})
    rows = [{"stratégie": s["label"], "clé": name, "CAGR": s.get("cagr"), "Sharpe": s.get("sharpe"),
             "max drawdown": s.get("max_drawdown"),
             "dans la limite": None if s.get("max_drawdown") is None
             else abs(s["max_drawdown"]) <= policy.drawdown_max_accepte}
            for name, s in strategies.items()]
    st.markdown("**Stratégies du registre face à la limite de drawdown (backtest du rapport)**")
    st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
        "CAGR": st.column_config.NumberColumn(format="percent"),
        "Sharpe": st.column_config.NumberColumn(format="%.2f"),
        "max drawdown": st.column_config.NumberColumn(format="percent")})
else:
    st.info("Aucun rapport au schéma 1.3 : lance `python main.py run-month`.")

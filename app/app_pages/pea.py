"""État vérifiable du PEA, recherche et veille (lecture seule)."""
import json

import pandas as pd
import streamlit as st
import yaml

from app import ui
from app.data import PROJECT_ROOT
from src.broker import load_broker_profile
from src.data_loader import load_prices
from src.macro import load_observations, macro_context
from src.patrimoine import load_patrimoine_config
from src.pea_account import readiness
from src.policy import load_policy
from src.positions import last_prices
from src.provenance import code_revision, project_revision
from src.universe import load_universe
from src.vehicles import map_target_to_vehicles

ui.page_header("Mon PEA Bourso", "Compte, données et propositions vérifiables. Objectif tactique en recherche ; décisions humaines.",
               icon=":material/account_balance:")
root = PROJECT_ROOT
broker = load_broker_profile(root / "config/broker.yaml")
personal = load_patrimoine_config(root / "config/patrimoine.yaml")
risk = yaml.safe_load((root / "config/tactical.yaml").read_text(encoding="utf-8"))
ui.kpis([{"label": "Versement mensuel", "value": f"{personal['profil']['versement_mensuel_eur']:.0f} €"},
                {"label": "Offre", "value": broker.offer.capitalize()},
                {"label": "Objectif de baisse", "value": f"{risk['drawdown_objective']:.0%}",
                 "help": "Critère de recherche ; aucune garantie de perte maximale."}])

try:
    prices = load_prices(root / "data/processed/universe_prices.csv")
    quotes = last_prices(prices)["prix"].to_dict()
    policy = load_policy(root / "config/policy.yaml")
    assets = load_universe(root / "config/assets.yaml")
    mapped, _ = map_target_to_vehicles(policy.allocation_fixe, {}, quotes, assets,
                                       personal["profil"]["versement_mensuel_eur"])
    tickers = [t for t in mapped if t != "CASH"]
    checks = readiness(prices, tickers, transactions_path=root / "config/transactions.csv",
                        receipt_path=root / "config/reconciliation.json")
    for ticker in tickers:
        checks["issues"].extend(broker.check_product(ticker, assets))
    if checks["issues"]:
        st.warning("Propositions actuelles en attente de vérification.")
        for issue in checks["issues"]:
            st.markdown(f"- {issue}")
    else:
        st.success("Cours, produits et rapprochement disponibles pour la politique actuelle.")
    st.caption(f"Derniers cours locaux : {prices.index[-1]:%d/%m/%Y}. Politique conservée : {policy.strategie_suivie}.")
except (ValueError, FileNotFoundError) as exc:
    st.error(str(exc))

ui.section("Recherche tactique", "Comparaisons avec parts entières, frais et cash résiduel.")
report = root / "reports/tactical/latest.json"
if report.exists():
    study = json.loads(report.read_text(encoding="utf-8"))
    provenance = study.get("provenance") or {}
    if provenance.get("inputs_sha256") != project_revision(root) or provenance.get("code_sha256") != code_revision(root):
        st.warning("Les données ou le code ont changé depuis cette campagne : ses résultats sont une archive à recalculer.")
    st.warning("Résultats exploratoires sur prix ajustés. Aucune nouvelle stratégie approuvée automatiquement.")
    st.caption(f"{study['variants']} variantes ; {study['cumulative_unique_trials']} essais cumulés ; {study['start']} → {study['end']}.")
    rows = [{"variante": r["name"], "capital final (€)": r["final_value"],
             "baisse quotidienne": r["max_drawdown"], "frais (€)": r["fees"], "ordres": r["orders"]}
            for r in study["results"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
        "baisse quotidienne": st.column_config.NumberColumn(format="percent"),
        "capital final (€)": st.column_config.NumberColumn(format="%.2f"),
        "frais (€)": st.column_config.NumberColumn(format="%.2f")})
    with st.expander("Hypothèses et limites"):
        for limitation in study["limitations"]:
            st.markdown(f"- {limitation}")
else:
    st.info("La campagne de recherche n'a pas encore produit de résultat.")

ui.section("Contexte macro", "Publications datées et versionnées ; pas de signal macro validé.")
macro = macro_context(load_observations(root / "data/macro/observations.csv"), pd.Timestamp.now(tz="UTC"))
if macro["observations"]:
    st.dataframe(pd.DataFrame(macro["observations"]), hide_index=True)
else:
    st.info("Aucune observation économique réelle importée.")

ui.section("Veille", "Préparation locale uniquement ; aucun envoi externe activé.")
watch = root / "reports/watch/latest.json"
if watch.exists():
    state = json.loads(watch.read_text(encoding="utf-8"))
    st.caption(f"Dernier contrôle : {state['as_of']} · {state['mode']}")
    for event in state["current_events"]:
        st.info(event["message"])
else:
    st.info("Le contrôle de veille n'a pas encore été exécuté.")

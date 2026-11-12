"""Page « Journal » : décisions de paper trading (lecture seule)."""

import streamlit as st

from app import ui
from app.data import journal_table

ui.page_header("Journal de décision", "Tes décisions de paper trading, mois par mois. Pour décider : `python main.py paper-decision`.", icon=":material/edit_note:")

journal = journal_table()
if journal.empty:
    st.info("Journal vide : lance `python main.py run-month`.")
    st.stop()

pending = journal.loc[journal["décision"] == "PENDING", "mois"].tolist()
decided = int((journal["décision"] != "PENDING").sum())
with st.container(horizontal=True):
    st.metric("Mois de journal renseignés", f"{decided} / 3", help="Règle du guide : au moins 3 mois", border=True)
    st.metric("Décisions en attente", len(pending), border=True)
if pending:
    st.warning(f"Décisions en attente : {', '.join(pending)}. Renseigner avec "
               "`python main.py paper-decision --month YYYY-MM --status ... --confidence 1-5`.",
               icon=":material/pending_actions:")
st.dataframe(journal, hide_index=True,
             column_config={"confiance": st.column_config.NumberColumn("confiance", format="%d / 5")})

"""Journal de transactions : positions, performance réelle, PEA, ordres proposés."""

from pathlib import Path

import pandas as pd
import pytest

import main
from src.ledger import (
    compare_with_positions_file,
    load_transactions,
    monthly_valuation,
    money_weighted_return,
    pea_status,
    portfolio_performance,
    record_pending_orders,
    state_at,
    time_weighted_returns,
    to_positions,
)

ROOT = Path(__file__).resolve().parents[1]
HEADER = "date,enveloppe,type,ticker,parts,prix,montant,frais,commentaire\n"


def _write(tmp_path, body, name="transactions.csv"):
    path = tmp_path / name
    path.write_text(HEADER + body, encoding="utf-8")
    return path


BODY = ("2026-01-02,pea,VERSEMENT,,,,1000,0,\n"
        "2026-01-05,pea,ACHAT,A.PA,10,50,,1,\n"
        "2026-02-02,pea,VERSEMENT,,,,500,0,\n"
        "2026-02-03,pea,ACHAT,A.PA,5,60,,1,\n"
        "2026-03-10,pea,VENTE,A.PA,3,70,,1,\n"
        "2026-03-15,pea,FRAIS,,,,2,0,garde\n")


@pytest.fixture
def prices():
    index = pd.to_datetime(["2026-01-30", "2026-02-27", "2026-03-31"])
    return pd.DataFrame({"A.PA": [55.0, 60.0, 70.0], "CW8.PA": [100.0, 110.0, 121.0]}, index=index)


def test_state_positions_and_cash(tmp_path):
    tx = load_transactions(_write(tmp_path, BODY))
    state = state_at(tx)
    pea = state["enveloppes"]["pea"]
    assert pea["parts"] == {"A.PA": 12}
    # 1000 - 501 + 500 - 301 + 209 - 2
    assert pea["liquidites"] == pytest.approx(905.0)
    assert state_at(tx, "2026-01-31")["enveloppes"]["pea"]["parts"] == {"A.PA": 10}
    positions = to_positions(state)
    assert positions["lignes"] == [{"enveloppe": "pea", "ticker": "A.PA", "parts": 12}]
    assert compare_with_positions_file(positions, positions) == []
    other = {"lignes": [{"enveloppe": "pea", "ticker": "A.PA", "parts": 11}], "liquidites_eur": {}}
    assert "journal 12 parts" in compare_with_positions_file(positions, other)[0]


@pytest.mark.parametrize("body, message", [
    ("2026-01-02,pea,CADEAU,,,,10,0,\n", "type 'CADEAU'"),
    ("2026-01-02,pea,ACHAT,A.PA,0,50,,0,\n", "parts > 0"),
    ("02/01/2026,pea,VERSEMENT,,,,10,0,\n", "date invalide"),
    ("2026-01-02,pea,VERSEMENT,,,,,0,\n", "montant > 0"),
])
def test_validation_errors_cite_the_line(tmp_path, body, message):
    with pytest.raises(ValueError, match=message):
        load_transactions(_write(tmp_path, body))
    assert load_transactions(tmp_path / "absent.csv") is None


def test_overselling_is_rejected_and_negative_cash_warned(tmp_path):
    tx = load_transactions(_write(tmp_path, "2026-01-02,pea,VENTE,A.PA,1,10,,0,\n"))
    with pytest.raises(ValueError, match="Vente"):
        state_at(tx)
    tx = load_transactions(_write(tmp_path, "2026-01-02,pea,ACHAT,A.PA,1,10,,0,\n"))
    assert "Liquidités négatives" in state_at(tx)["warnings"][0]


def test_valuation_twr_and_mwr(tmp_path, prices):
    tx = load_transactions(_write(tmp_path, BODY))
    valuation = monthly_valuation(tx, prices)
    assert valuation.loc["2026-01-31", "valeur"] == pytest.approx(10 * 55 + 499)
    assert valuation["flux"].tolist() == [1000.0, 500.0, 0.0]
    assert valuation.loc["2026-03-31", "frais"] == pytest.approx(3.0)
    twr = time_weighted_returns(valuation)
    assert twr.iloc[0] == pytest.approx((10 * 55 + 499) / 1000 - 1)
    assert twr.iloc[1] == pytest.approx(valuation["valeur"].iloc[1] / (valuation["valeur"].iloc[0] + 500) - 1)
    constant = pd.DataFrame({"valeur": [101.0, 203.01], "flux": [100.0, 100.0], "frais": [0.0, 0.0]})
    assert money_weighted_return(constant) == pytest.approx(1.01 ** 12 - 1, rel=1e-6)


def test_missing_price_is_explicit(tmp_path, prices):
    tx = load_transactions(_write(tmp_path, BODY.replace("A.PA", "ZZ.PA")))
    with pytest.raises(ValueError, match="ZZ.PA"):
        monthly_valuation(tx, prices)


def test_performance_vs_benchmark_and_paper(tmp_path, prices):
    tx = load_transactions(_write(tmp_path, BODY))
    paper = pd.DataFrame({"paper_return": [0.01, 0.02], "system_return": [0.0, 0.01]},
                         index=pd.to_datetime(["2026-02-28", "2026-03-31"]))
    perf = portfolio_performance(tx, prices, benchmark="CW8.PA", paper_monthly=paper)
    assert perf["net_contributions"] == 1500 and perf["fees_total"] == pytest.approx(5.0)
    # Buy & Hold avec les mêmes flux : 1000 en janvier (rendement inconnu -> 0), +500 en février (+10 %), mars +10 %.
    assert perf["benchmark_same_flows_value"] == pytest.approx((1000 * 1.1 + 500 * 1.1) * 1.1)
    assert perf["comparison"]["common_months"] == 2
    assert perf["comparison"]["paper_twr_common"] == pytest.approx(1.01 * 1.02 - 1)


def test_pea_status_rules():
    tx = pd.DataFrame({"date": pd.to_datetime(["2020-01-01"]), "enveloppe": ["pea"], "type": ["VERSEMENT"],
                       "montant": [140_000.0]})
    status = pea_status(tx, "2022-06-15", today="2026-09-24")
    assert status["five_year_date"] == "2027-06-15" and not status["five_years_reached"]
    assert status["remaining_capacity"] == 10_000 and len(status["alerts"]) == 2
    assert pea_status(None, "2019-01-01", today="2026-09-24")["five_years_reached"]
    assert "non renseignée" in pea_status(None, None)["alerts"][0]


def test_pending_orders_are_only_proposals(tmp_path):
    table = pd.DataFrame({"parts_a_acheter": [3, 0], "prix": [7.1, 40.0], "montant": [21.3, 0.0], "frais": [0.02, 0.0]},
                         index=pd.Index(["WPEA.PA", "PAASI.PA"], name="ticker"))
    path = tmp_path / "pending.csv"
    assert record_pending_orders(table, path, when="2026-09-24") == 1
    assert record_pending_orders(table, path, when="2026-10-02") == 1
    pending = pd.read_csv(path)
    assert len(pending) == 2 and set(pending["statut"]) == {"PROPOSE"}
    # Un ordre proposé n'est jamais compté comme exécuté : ce fichier n'est pas un journal de transactions.
    with pytest.raises(ValueError):
        load_transactions(path)


def test_example_file_is_valid():
    tx = load_transactions(ROOT / "config" / "transactions.example.csv")
    assert state_at(tx)["enveloppes"]["pea"]["parts"]["WPEA.PA"] == 111


def test_portfolio_command_and_planner_use_ledger(tmp_path, prices, capsys):
    data = tmp_path / "prices.csv"
    prices.rename_axis("Date").to_csv(data)
    transactions = _write(tmp_path, BODY)
    output = tmp_path / "portfolio.md"
    assert main.main(["portfolio", "--transactions", str(transactions), "--data", str(data),
                      "--paper-dir", str(tmp_path / "paper"), "--output", str(output)]) == 0
    out = capsys.readouterr().out
    assert "TRI" in out and "PEA" in out and output.exists()
    out.encode("cp1252")
    assert main.main(["portfolio", "--transactions", str(tmp_path / "none.csv"), "--data", str(data),
                      "--output", str(output)]) == 0
    assert "Aucun journal" in capsys.readouterr().out


def test_plan_record_writes_pending_orders_from_ledger_positions(tmp_path, prices, capsys):
    import json

    data = tmp_path / "prices.csv"
    prices.rename_axis("Date").to_csv(data)
    paper = tmp_path / "paper"
    paper.mkdir()
    entry = {"schema_version": "1.0", "report_month": "2026-03", "signal_date": "2026-02-28",
             "manual_decision_status": "APPROVED_PAPER", "manual_selected_strategy": "momentum",
             "target_weights": {"momentum": {"A.PA": 1.0, "CASH": 0.0}}}
    (paper / "2026-03-paper-entry.json").write_text(json.dumps(entry), encoding="utf-8")
    pending = tmp_path / "pending.csv"
    assert main.main(["plan-contribution", "--amount", "400", "--transactions", str(_write(tmp_path, BODY)),
                      "--positions", str(tmp_path / "none.yaml"), "--paper-dir", str(paper), "--data", str(data),
                      "--output-dir", str(tmp_path / "plans"), "--record", "--pending", str(pending)]) == 0
    out = capsys.readouterr().out
    assert "Positions issues du journal" in out and "PROPOSE" in out
    rows = pd.read_csv(pending)
    assert rows["ticker"].tolist() == ["A.PA"] and rows["statut"].tolist() == ["PROPOSE"]


def test_empty_journal_is_handled_gracefully(tmp_path, capsys):
    import main
    from app.data import real_portfolio

    journal = tmp_path / "transactions.csv"
    journal.write_text("date,enveloppe,type,ticker,parts,prix,montant,frais,commentaire\n", encoding="utf-8")
    assert main.main(["portfolio", "--transactions", str(journal), "--output", str(tmp_path / "p.md")]) == 0
    assert "Journal vide" in capsys.readouterr().out
    data = real_portfolio(transactions_path=journal)
    assert data["empty_journal"] and data["perf"] is None and not data["has_transactions"]

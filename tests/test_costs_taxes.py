"""Fiscalité simplifiée, frais réels dans le DCA et sensibilité aux frais."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import main
from src.cost_sensitivity import cost_scenarios, generate_cost_report, run_cost_sensitivity
from src.costs import FeeModel
from src.crypto_signals import BTC, ETH, generate_crypto_report, run_crypto_study, sleeve_comparison
from src.dca import run_dca_comparison, simulate_dca
from src.monthly_pipeline import MonthlyPipelineConfig
from src.patrimoine import generate_patrimoine_report, load_patrimoine_config
from src.taxes import TaxConfig, crypto_net_value, pea_net_value, tax_config_from
from tests.conftest import FIXTURE_CONFIG

ROOT = Path(__file__).resolve().parents[1]


def test_pea_and_crypto_net_values():
    before_2026 = TaxConfig(prelevements_sociaux_pct=17.2, flat_tax_pct=30.0)
    assert pea_net_value(150.0, 100.0, 6, before_2026) == pytest.approx(150 - 50 * 0.172)
    assert pea_net_value(150.0, 100.0, 3, before_2026) == pytest.approx(150 - 50 * 0.30)
    # Taux par défaut = loi de 2026 (prélèvements sociaux 18,6 %, prélèvement forfaitaire 31,4 %).
    assert pea_net_value(150.0, 100.0, 6) == pytest.approx(150 - 50 * 0.186)
    assert pea_net_value(150.0, 100.0, 3) == pytest.approx(150 - 50 * 0.314)
    assert pea_net_value(80.0, 100.0, 10) == 80.0  # moins-value non imposée
    assert crypto_net_value(3.0, 1.0, TaxConfig(flat_tax_pct=30)) == pytest.approx(3 - 2 * 0.3)


def test_tax_config_validation():
    assert tax_config_from({}).prelevements_sociaux_pct == 18.6  # LFSS 2026
    assert tax_config_from({}).av_prelevements_sociaux_pct == 17.2  # assurance-vie épargnée
    assert tax_config_from({"fiscalite": {"flat_tax_pct": 31.4}}).flat_tax_pct == 31.4
    with pytest.raises(ValueError):
        tax_config_from({"fiscalite": {"impot": 10}})
    with pytest.raises(ValueError):
        TaxConfig(flat_tax_pct=120)


def _returns(n=24):
    return pd.Series([0.01] * n, index=pd.date_range("2020-01-31", periods=n, freq="ME"))


def test_dca_fixed_fee_weighs_on_small_contribution():
    fixed = FeeModel(proportional=0.0, fixed_per_order=2.0)
    sim = simulate_dca(_returns(1), 100.0, fee_model=fixed)
    assert sim["Contribution Fees"].iloc[0] == pytest.approx(2.0)
    assert sim["Value"].iloc[0] == pytest.approx(98.0 * 1.01)
    orders = pd.Series(2, index=_returns(1).index)
    two = simulate_dca(_returns(1), 100.0, fee_model=fixed, orders_per_month=orders)
    assert two["Contribution Fees"].iloc[0] == pytest.approx(4.0)
    cash = simulate_dca(_returns(1), 100.0, fee_model=fixed, invested_exposure=pd.Series(0.0, index=orders.index))
    assert cash["Contribution Fees"].iloc[0] == 0.0


def test_dca_summary_reports_net_value_and_fees():
    result = run_dca_comparison({"buy_and_hold": _returns(72)}, 100.0, fee_model=FeeModel(proportional=0.001))
    summary = result["strategies"]["buy_and_hold"]
    assert summary["years"] == 6
    gain = summary["final_value_eur"] - summary["total_contributed_eur"]
    rate = TaxConfig().prelevements_sociaux_pct / 100
    assert summary["final_value_net_eur"] == pytest.approx(summary["final_value_eur"] - gain * rate)
    assert summary["contribution_fees_eur"] == pytest.approx(72 * 0.1)


def test_patrimoine_projection_net_column(tmp_path):
    config = load_patrimoine_config(FIXTURE_CONFIG / "patrimoine.yaml")
    result = generate_patrimoine_report(config, {"pea": 1000.0}, tmp_path / "p.md")
    central = result["projection"]["scenarios"]["central"]
    gain = central["valeur_finale_eur"] - central["total_verse_eur"]
    rate = tax_config_from(config).prelevements_sociaux_pct / 100
    assert central["valeur_finale_nette_eur"] == pytest.approx(central["valeur_finale_eur"] - gain * rate)
    assert "Valeur nette" in (tmp_path / "p.md").read_text(encoding="utf-8")


def test_crypto_report_has_after_tax_column(tmp_path):
    index = pd.date_range("2016-01-01", "2021-12-31", freq="D")
    rng = np.random.default_rng(2)
    daily = pd.DataFrame({BTC: 1000 * np.cumprod(1 + rng.normal(0.002, 0.03, len(index))),
                          ETH: 100 * np.cumprod(1 + rng.normal(0.002, 0.04, len(index)))}, index=index)
    study = run_crypto_study(daily)
    sleeves = sleeve_comparison(study["returns"]["bh_btc"] * 0.1, {"roro_basket": study["returns"]["roro_basket"]})
    text = generate_crypto_report(study, sleeves, tmp_path / "c.md").read_text(encoding="utf-8")
    assert "Cumulé net d'impôt" in text


# --- sensibilité -------------------------------------------------------------------
def test_cost_scenarios_convert_fixed_fee_to_rate():
    scenarios = cost_scenarios(FeeModel(proportional=0.0, fixed_per_order=10.0), portfolio_sizes=(1_000, 10_000))
    rates = {s["label"]: s["rate"] for s in scenarios}
    assert rates["Barème configuré, portefeuille 1,000 €"] == pytest.approx(0.01)
    assert rates["Barème configuré, portefeuille 10,000 €"] == pytest.approx(0.001)
    assert len(scenarios) == 5


def _monthly_prices():
    index = pd.date_range("2016-01-31", periods=80, freq="ME")
    rng = np.random.default_rng(4)
    return pd.DataFrame({"CW8.PA": 100 * np.cumprod(1 + rng.normal(0.008, 0.04, 80)),
                         "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.006, 0.05, 80))}, index=index)


def test_cost_sensitivity_costs_reduce_momentum_return(tmp_path):
    table = run_cost_sensitivity(_monthly_prices(), MonthlyPipelineConfig(), asset_roles=None,
                                 fee_model=FeeModel(), portfolio_sizes=(1_000,))
    momentum = table[table["stratégie"].str.startswith("Momentum défensif")].set_index("scénario")
    assert momentum.loc["0.10% proportionnel", "CAGR"] > momentum.loc["0.30% proportionnel", "CAGR"]
    assert table["stratégie"].str.startswith("Buy & Hold").sum() == 1
    text = generate_cost_report(table, FeeModel(), tmp_path / "costs.md").read_text(encoding="utf-8")
    assert "Taux équivalent" in text


@pytest.mark.slow
def test_costs_and_dca_commands(tmp_path, capsys):
    data = tmp_path / "prices.csv"
    _monthly_prices().rename_axis("Date").to_csv(data)
    assets = tmp_path / "assets.yaml"
    assets.write_text("universe:\n  - {ticker: CW8.PA, name: W, category: monde, universe_active: true, notes: ''}\n"
                      "  - {ticker: ESE.PA, name: S, category: us, universe_active: true, notes: ''}\n",
                      encoding="utf-8")
    assert main.main(["costs", "--data", str(data), "--assets", str(assets), "--output", str(tmp_path / "c.md")]) == 0
    assert main.main(["dca", "--data", str(data), "--assets", str(assets), "--output", str(tmp_path / "d.md")]) == 0
    out = capsys.readouterr().out
    assert "net" in out and "Sensibilité" in out
    out.encode("cp1252")

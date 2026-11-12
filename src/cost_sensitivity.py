"""Sensibilité des stratégies aux frais de transaction (commande ``costs``).

Le backtest mensuel applique des frais **proportionnels** au turnover. Pour
estimer l'effet d'un barème réel (forfait, minimum), on convertit le coût d'un
rééquilibrage complet d'un portefeuille de taille ``X`` en taux équivalent :
``taux(X) = frais_ordre(X) / X``. Plus le portefeuille est petit, plus un
forfait pèse lourd.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd

from src.costs import FeeModel
from src.monthly_pipeline import MonthlyPipelineConfig, run_monthly_pipeline

PROPORTIONAL_SCENARIOS = (0.001, 0.002, 0.003)
PORTFOLIO_SIZES = (2_000.0, 10_000.0, 50_000.0)


def cost_scenarios(fee_model: FeeModel, portfolio_sizes=PORTFOLIO_SIZES) -> list[dict]:
    """Scénarios : taux proportionnels fixes + barème configuré selon la taille."""
    scenarios = [{"label": f"{rate:.2%} proportionnel", "rate": rate} for rate in PROPORTIONAL_SCENARIOS]
    for size in portfolio_sizes:
        scenarios.append({"label": f"Barème configuré, portefeuille {size:,.0f} €",
                          "rate": fee_model.effective_rate(size), "portfolio": size})
    return scenarios


def run_cost_sensitivity(prices: pd.DataFrame, config: MonthlyPipelineConfig, *, asset_roles: dict | None,
                         fee_model: FeeModel, portfolio_sizes=PORTFOLIO_SIZES) -> pd.DataFrame:
    """Métriques Momentum / Momentum + VT pour chaque scénario de frais."""
    rows = []
    benchmark = None
    for scenario in cost_scenarios(fee_model, portfolio_sizes):
        cfg = replace(config, backtest=replace(config.backtest, transaction_cost=scenario["rate"]))
        report = run_monthly_pipeline(prices, cfg, asset_roles=asset_roles).report
        benchmark = report.benchmark
        for strategy in (report.momentum_strategy, report.volatility_targeted_strategy):
            if not strategy.enabled:
                continue
            rows.append({"scénario": scenario["label"], "taux équivalent": scenario["rate"],
                         "stratégie": strategy.name, "CAGR": strategy.cagr, "Sharpe": strategy.sharpe,
                         "max drawdown": strategy.max_drawdown, "frais cumulés": strategy.cumulative_cost})
    if benchmark is not None:
        rows.append({"scénario": "sans frais (achat unique)", "taux équivalent": 0.0, "stratégie": benchmark.name,
                     "CAGR": benchmark.cagr, "Sharpe": benchmark.sharpe, "max drawdown": benchmark.max_drawdown,
                     "frais cumulés": 0.0})
    return pd.DataFrame(rows)


def _pct(value) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:.2%}"


def generate_cost_report(table: pd.DataFrame, fee_model: FeeModel, output_path: str | Path) -> Path:
    lines = [
        "# Sensibilité aux frais de transaction", "",
        f"Date de génération : {date.today().isoformat()}", "",
        f"Barème configuré : {fee_model.proportional:.2%} + {fee_model.fixed_per_order:.2f} € par ordre "
        f"(minimum {fee_model.minimum_per_order:.2f} €). Les scénarios « portefeuille X € » convertissent "
        "ce barème en taux proportionnel équivalent pour un rééquilibrage complet.", "",
        "| Scénario | Taux équivalent | Stratégie | CAGR | Sharpe | Max drawdown | Frais cumulés |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for _, row in table.iterrows():
        sharpe = "n/a" if row["Sharpe"] is None or pd.isna(row["Sharpe"]) else f"{row['Sharpe']:.2f}"
        lines.append(f"| {row['scénario']} | {_pct(row['taux équivalent'])} | {row['stratégie']} | {_pct(row['CAGR'])} | "
                     f"{sharpe} | {_pct(row['max drawdown'])} | {_pct(row['frais cumulés'])} |")
    lines += [
        "", "## Lecture", "",
        "- Une stratégie qui change souvent d'ETF perd plus de rendement quand les frais augmentent ; le Buy & Hold "
        "n'en paie presque pas.",
        "- Avec un forfait par ordre, un petit portefeuille supporte un taux effectif élevé : vérifier le barème réel "
        "de ton courtier et le renseigner dans `config/strategy_params.yaml > costs`.", "",
    ]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path

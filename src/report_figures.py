"""Graphiques PNG du rapport mensuel (backend non interactif).

Quatre figures, calculées uniquement à partir du résultat du pipeline (aucune
donnée supplémentaire, aucune donnée postérieure au signal) :

- ``equity``     : capital théorique Benchmark / Momentum / Momentum + VT ;
- ``drawdown``   : drawdowns des mêmes stratégies ;
- ``allocation`` : poids exécutés de la stratégie suivie (VT sinon Momentum) ;
- ``volatility`` : volatilité réalisée de la stratégie de base vs cible VT.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import pandas as pd  # noqa: E402

from src.metrics import compute_drawdown  # noqa: E402

FIGURE_NAMES = ("equity", "drawdown", "allocation", "volatility")
FIGURE_TITLES = {
    "equity": "Capital théorique",
    "drawdown": "Drawdown",
    "allocation": "Allocation exécutée",
    "volatility": "Volatilité réalisée",
}


def _equity_curves(result) -> pd.DataFrame:
    curves = {
        f"Buy & Hold {result.report.universe['benchmark']}": result.benchmark_backtest["Equity Curve"],
        "Momentum": result.momentum_backtest["Equity Curve"],
    }
    if result.vt_backtest is not None:
        curves["Momentum + VT"] = result.vt_backtest["Equity Curve"]
    return pd.DataFrame(curves)


def _save(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def save_monthly_figures(result, output_dir: str | Path, month: str) -> dict[str, Path]:
    """Écrit les figures ``{month}-{name}.png`` et renvoie leurs chemins."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    curves = _equity_curves(result)

    fig, ax = plt.subplots(figsize=(10, 4.5))
    curves.plot(ax=ax)
    ax.set_title("Capital théorique (frais inclus)")
    ax.set_ylabel("€")
    ax.grid(True, alpha=0.3)
    paths["equity"] = _save(fig, output_dir / f"{month}-equity.png")

    fig, ax = plt.subplots(figsize=(10, 3.5))
    curves.apply(compute_drawdown).plot(ax=ax)
    ax.set_title("Drawdown")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.grid(True, alpha=0.3)
    paths["drawdown"] = _save(fig, output_dir / f"{month}-drawdown.png")

    weights = result.vt_weights if result.vt_weights is not None else result.momentum_weights
    if weights is not None:
        weights = weights.loc[:, (weights > 1e-9).any()]
        fig, ax = plt.subplots(figsize=(10, 3.5))
        weights.plot.area(ax=ax, linewidth=0)
        label = "Momentum + VT" if result.vt_weights is not None else "Momentum"
        ax.set_title(f"Allocation exécutée — {label}")
        ax.set_ylim(0, 1)
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
        ax.legend(loc="upper left", fontsize=8, ncol=4)
        paths["allocation"] = _save(fig, output_dir / f"{month}-allocation.png")

    if result.realized_volatility is not None:
        fig, ax = plt.subplots(figsize=(10, 3.5))
        result.realized_volatility.plot(ax=ax, label="Volatilité réalisée (Momentum)")
        target = result.report.risk.get("target_volatility")
        if target is not None:
            ax.axhline(target, color="grey", linestyle="--", label=f"Cible {target:.0%}")
        ax.set_title("Volatilité réalisée annualisée")
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(True, alpha=0.3)
        paths["volatility"] = _save(fig, output_dir / f"{month}-volatility.png")
    return paths

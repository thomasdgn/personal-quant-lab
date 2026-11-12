import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from src.metrics import compute_drawdown


def plot_equity_curve(
    equity_curve: pd.Series,
    title: str = "Equity Curve",
) -> tuple[Figure, Axes]:
    """
    Plot an equity curve.
    """
    fig, ax = plt.subplots(figsize=(10, 5))

    equity_curve.dropna().plot(ax=ax)
    ax.set_title(title)
    ax.set_ylabel("Capital")
    ax.grid(True)

    return fig, ax


def plot_drawdown(
    equity_curve: pd.Series,
    title: str = "Drawdown",
) -> tuple[Figure, Axes]:
    """
    Plot drawdown from an equity curve.
    """
    drawdown = compute_drawdown(equity_curve)

    fig, ax = plt.subplots(figsize=(10, 4))

    drawdown.plot(ax=ax)
    ax.axhline(0, color="red", linestyle="--")
    ax.set_title(title)
    ax.set_ylabel("Drawdown")
    ax.grid(True)

    return fig, ax

"""Recherche de robustesse : quelle stratégie suivre ? (Projet 4 bis, v3)

Produit des **preuves**, sans changer la stratégie suivie par défaut :

1. **Grille Momentum** (lookback 3/6/9/12, MA 6/10/12, top_n 1/2/3, VT on/off),
   évaluée en **walk-forward** : chaque année, les paramètres sont choisis sur
   le passé (fenêtre expansive, ≥ 36 mois) puis mesurés sur l'année suivante.
2. **Stratégies simples et explicables** : dual momentum (meilleure action vs
   obligataire vs cash), top 3 équipondéré avec filtre de tendance, allocation
   inverse-volatilité, 80/20 et 60/40 CW8/OBLI rebalancés chaque mois.
3. **Incertitude** : intervalle de confiance (bootstrap par blocs circulaires)
   de l'écart de Sharpe avec le Buy & Hold ; nombre de stratégies testées
   rapporté (risque de tests multiples) ; stabilité des Sharpe de la grille
   entre les deux moitiés de la période (corrélation de rang).

Toutes les stratégies sont comparées **sur les mêmes mois** (fenêtre commune),
avec les conventions du backtest mensuel (décalage d'un mois, frais au
turnover, cash explicite). Aucun ordre n'est exécuté.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtest import CASH_COLUMN
from src.engine import run_backtest
from src.signals import lag_weights_for_execution
from src.strategies import (
    REGISTRY,
    StrategyContext,
    available_strategies,
    build_strategy,
    dual_momentum_target,
    inverse_vol_target,
    momentum_target,
    static_target,
)

LOOKBACKS = (3, 6, 9, 12)
MA_WINDOWS = (6, 10, 12)
TOP_NS = (1, 2, 3)
MIN_TRAIN_MONTHS = 36
TEST_BLOCK_MONTHS = 12
BOOTSTRAP_BLOCK = 6
BOOTSTRAP_SAMPLES = 2000

# Libellés : ceux du registre, plus la variante walk-forward propre à l'étude.
STRATEGY_LABELS = {name: definition.label for name, definition in REGISTRY.items()}
STRATEGY_LABELS.update({
    "benchmark": "Buy & Hold {benchmark}",
    "momentum": "Momentum 12-1 MA10 top 1 (défaut)",
    "momentum_walk_forward": "Momentum, paramètres choisis en walk-forward",
})


@dataclass(frozen=True)
class GridConfig:
    lookback: int
    ma: int
    top_n: int
    vt: bool

    @property
    def key(self) -> str:
        return f"L{self.lookback}-MA{self.ma}-top{self.top_n}-{'VT' if self.vt else 'noVT'}"


def grid_configs() -> list[GridConfig]:
    return [GridConfig(lb, ma, n, vt) for lb, ma, n, vt in itertools.product(LOOKBACKS, MA_WINDOWS, TOP_NS, (False, True))]


# --------------------------------------------------------------------------- #
# Poids des stratégies (déjà décalés d'un mois) — via le registre src/strategies.py
# --------------------------------------------------------------------------- #
def momentum_weights(monthly: pd.DataFrame, cfg: GridConfig, config) -> pd.DataFrame:
    """Momentum (``cfg``) avec VT optionnel ; poids exécutés."""
    skip = 1 if cfg.lookback > 1 else 0
    target = momentum_target(monthly, config, lookback=cfg.lookback, skip=skip, ma=cfg.ma, top_n=cfg.top_n, vt=cfg.vt)
    return lag_weights_for_execution(target)


def dual_momentum_weights(monthly: pd.DataFrame, equities: list[str], bond: str) -> pd.DataFrame:
    """Meilleure action (momentum 12-1) si elle bat l'obligataire et zéro ; sinon
    obligataire si son momentum est positif ; sinon cash."""
    return lag_weights_for_execution(dual_momentum_target(monthly, equities, bond))


def inverse_vol_weights(monthly: pd.DataFrame, equities: list[str], window: int = 12) -> pd.DataFrame:
    """Poids ∝ 1 / volatilité mensuelle sur ``window`` mois (actifs disponibles)."""
    return lag_weights_for_execution(inverse_vol_target(monthly, equities, window))


def static_weights(monthly: pd.DataFrame, allocation: dict[str, float]) -> pd.DataFrame:
    """Allocation fixe rebalancée chaque mois, active quand tous les actifs cotent."""
    return lag_weights_for_execution(static_target(monthly, allocation))


# --------------------------------------------------------------------------- #
# Backtests et statistiques
# --------------------------------------------------------------------------- #
def sharpe(returns: pd.Series) -> float | None:
    returns = returns.dropna()
    std = returns.std()
    return None if len(returns) < 2 or not std or np.isnan(std) else float(returns.mean() / std * np.sqrt(12))


def summary_stats(returns: pd.Series, turnover: pd.Series | None = None) -> dict:
    returns = returns.dropna()
    growth = (1.0 + returns).cumprod()
    years = len(returns) / 12.0
    return {
        "cagr": float(growth.iloc[-1] ** (1 / years) - 1) if years else None,
        "volatility": float(returns.std() * np.sqrt(12)),
        "sharpe": sharpe(returns),
        "max_drawdown": float((growth / growth.cummax().clip(lower=1.0) - 1).min()),
        "turnover_per_year": float(turnover.mean() * 12) if turnover is not None else None,
        "n_months": int(len(returns)),
    }


def block_bootstrap_sharpe_diff(strategy: pd.Series, reference: pd.Series, *, block: int = BOOTSTRAP_BLOCK,
                                samples: int = BOOTSTRAP_SAMPLES, seed: int = 42, level: float = 0.90) -> dict:
    """Écart de Sharpe (stratégie − référence) et intervalle de confiance par
    bootstrap par blocs circulaires sur les rendements **appariés**."""
    paired = pd.concat([strategy, reference], axis=1, join="inner").dropna().to_numpy()
    n = len(paired)
    if n < 2 * block:
        raise ValueError("Historique trop court pour le bootstrap par blocs.")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    diffs = np.empty(samples)
    for i in range(samples):
        starts = rng.integers(0, n, n_blocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:n] % n
        sample = paired[idx]
        std = sample.std(axis=0, ddof=1)
        s = np.where(std > 0, sample.mean(axis=0) / np.where(std > 0, std, 1) * np.sqrt(12), 0.0)
        diffs[i] = s[0] - s[1]
    point = (sharpe(pd.Series(paired[:, 0])) or 0.0) - (sharpe(pd.Series(paired[:, 1])) or 0.0)
    alpha = (1 - level) / 2
    return {"diff": float(point), "low": float(np.quantile(diffs, alpha)), "high": float(np.quantile(diffs, 1 - alpha)),
            "prob_positive": float((diffs > 0).mean()), "level": level}


def walk_forward_selection(grid_returns: dict[str, pd.Series], test_start: pd.Timestamp, test_end: pd.Timestamp, *,
                           min_train: int = MIN_TRAIN_MONTHS, block: int = TEST_BLOCK_MONTHS) -> dict:
    """Chaque bloc de ``block`` mois : configuration au meilleur Sharpe sur tout
    le passé disponible (≥ ``min_train`` mois), puis rendements hors échantillon."""
    frame = pd.DataFrame(grid_returns)
    months = frame.loc[test_start:test_end].index
    oos, choices = [], []
    for start in range(0, len(months), block):
        block_months = months[start:start + block]
        train = frame.loc[frame.index < block_months[0]]
        raw_scores = {key: sharpe(series) for key, series in train.items() if series.dropna().size >= min_train}
        scores: dict[str, float] = {k: v for k, v in raw_scores.items() if v is not None}
        if not scores:
            raise ValueError(f"Moins de {min_train} mois d'entraînement avant {block_months[0].date()}.")
        best = max(scores, key=lambda key: scores[key])
        choices.append({"test_start": block_months[0].date().isoformat(),
                        "test_end": block_months[-1].date().isoformat(), "config": best,
                        "train_sharpe": scores[best], "train_months": int(train[best].dropna().size)})
        oos.append(frame.loc[block_months, best])
    return {"returns": pd.concat(oos), "choices": choices}


def grid_stability(grid_returns: dict[str, pd.Series], start: pd.Timestamp, end: pd.Timestamp) -> dict:
    """Sharpe de chaque configuration sur les deux moitiés de la fenêtre et
    corrélation de rang (Spearman) entre les deux classements."""
    frame = pd.DataFrame(grid_returns).loc[start:end]
    half = len(frame) // 2
    first = frame.iloc[:half].apply(sharpe)
    second = frame.iloc[half:].apply(sharpe)
    full = frame.apply(sharpe)
    table = pd.DataFrame({"sharpe_total": full, "sharpe_1re_moitie": first, "sharpe_2e_moitie": second})
    rank_corr = float(table["sharpe_1re_moitie"].rank().corr(table["sharpe_2e_moitie"].rank()))
    return {"table": table.sort_values("sharpe_total", ascending=False), "rank_correlation": rank_corr,
            "split_date": frame.index[half].date().isoformat()}


# --------------------------------------------------------------------------- #
# Étude complète
# --------------------------------------------------------------------------- #
def run_research(monthly: pd.DataFrame, config, *, roles: dict[str, str] | None = None, bond: str = "OBLI.PA",
                 cash_return: float | pd.Series = 0.0, high_cost: float = 0.003, realistic_cost: float | None = None) -> dict:
    """Exécute l'étude et renvoie tables, choix walk-forward et stabilité.

    ``monthly`` : prix mensuels complets de l'univers (``MonthlyPipelineResult.monthly_prices``).
    ``realistic_cost`` : taux équivalent du barème réel (Phase 3) ; défaut = frais du backtest.
    """
    benchmark = config.benchmark_ticker
    base_cost = config.backtest.transaction_cost
    roles = roles or {}
    equities = [c for c in monthly.columns if roles.get(c, "candidate") == "candidate" and c != bond]
    has_bond = bond in monthly.columns

    grid, grid_high = {}, {}
    for cfg in grid_configs():
        weights = momentum_weights(monthly, cfg, config)
        grid[cfg.key] = run_backtest(monthly, weights, base_cost, cash_return)
        grid_high[cfg.key] = run_backtest(monthly, weights, high_cost, cash_return)
        # Pas de rendement tant que la configuration n'a pas assez d'historique
        # (période de chauffe en cash) : sinon le walk-forward serait biaisé.
        warmup = max(cfg.lookback, cfg.ma) + (config.volatility_targeting.volatility_window if cfg.vt else 0) + 1
        active = monthly.index[min(warmup, len(monthly.index) - 1)]
        for frame in (grid[cfg.key], grid_high[cfg.key]):
            frame.loc[frame.index < active, ["Net Return", "Turnover"]] = np.nan

    # Stratégies du registre (sauf cœur/satellite, qui dépend de la politique).
    ctx = StrategyContext(config=config, equities=tuple(equities), bond=bond if has_bond else None)
    named = [n for n in available_strategies(monthly, ctx) if n != "core_satellite"]
    named_weights = {name: build_strategy(name, monthly, ctx)["executed_weights"] for name in named}

    # Fenêtre commune : chaque stratégie « active » (poids non-cash possible) et
    # rendement défini ; les stratégies statiques avec obligataire imposent le début.
    starts = []
    for weights in named_weights.values():
        invested = weights.drop(columns=CASH_COLUMN).sum(axis=1) > 0
        starts.append(invested[invested].index.min())
    start = max(s for s in starts if pd.notna(s))
    first_grid = min(bt["Net Return"].dropna().index.min() for bt in grid.values())
    end = monthly.index[-1]
    # Assez d'historique pour entraîner le walk-forward avant la fenêtre.
    wf_min_start = pd.Timestamp(first_grid) + pd.offsets.MonthEnd(MIN_TRAIN_MONTHS)
    start = max(start, wf_min_start)

    walk_forward = walk_forward_selection({k: bt["Net Return"] for k, bt in grid.items()}, start, end)

    results = {}
    for name, weights in named_weights.items():
        bt = run_backtest(monthly, weights, base_cost, cash_return)
        bt_high = run_backtest(monthly, weights, high_cost, cash_return)
        stats = summary_stats(bt["Net Return"].loc[start:end], bt["Turnover"].loc[start:end])
        stats["cagr_high_cost"] = summary_stats(bt_high["Net Return"].loc[start:end])["cagr"]
        if realistic_cost is not None:
            bt_real = run_backtest(monthly, weights, realistic_cost, cash_return)
            stats["cagr_realistic_cost"] = summary_stats(bt_real["Net Return"].loc[start:end])["cagr"]
        results[name] = {"returns": bt["Net Return"].loc[start:end], "stats": stats}
    # Rejouer les poids sélectionnés sur un portefeuille continu : les coûts
    # au changement de variante dépendent de la variante réellement détenue.
    cfgs = {cfg.key: cfg for cfg in grid_configs()}
    selected_weights = pd.concat([
        momentum_weights(monthly, cfgs[c["config"]], config).loc[c["test_start"]:c["test_end"]]
        for c in walk_forward["choices"]
    ]).reindex(monthly.index, fill_value=0.0)
    selected_weights.loc[selected_weights.sum(axis=1) == 0, CASH_COLUMN] = 1.0
    wf_bt = run_backtest(monthly, selected_weights, base_cost, cash_return).loc[start:end]
    wf_returns = wf_bt["Net Return"]
    wf_turnover = wf_bt["Turnover"]
    wf_high = run_backtest(monthly, selected_weights, high_cost, cash_return)["Net Return"].loc[start:end]
    wf_stats = summary_stats(wf_returns, wf_turnover)
    wf_stats["cagr_high_cost"] = summary_stats(wf_high)["cagr"]
    results["momentum_walk_forward"] = {"returns": wf_returns, "stats": wf_stats}

    reference = results["benchmark"]["returns"]
    for name, item in results.items():
        item["vs_benchmark"] = None if name == "benchmark" else block_bootstrap_sharpe_diff(item["returns"], reference)

    return {
        "start": start.date().isoformat(), "end": end.date().isoformat(), "n_months": int(len(reference)),
        "benchmark": benchmark, "bond": bond if has_bond else None, "base_cost": base_cost, "high_cost": high_cost,
        "realistic_cost": realistic_cost, "results": results, "walk_forward": walk_forward,
        "stability": grid_stability({k: bt["Net Return"] for k, bt in grid.items()}, start, end),
        "n_strategies_tested": len(grid) + len(named_weights),
    }


# --------------------------------------------------------------------------- #
# Rapport
# --------------------------------------------------------------------------- #
def save_research_json(study: dict, output_path: str | Path) -> Path:
    """Résumé JSON de l'étude pour le tableau de bord (aucune série de rendements)."""

    def clean(value):
        if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
            return None
        return value

    rows = []
    for name, item in study["results"].items():
        vs = item["vs_benchmark"] or {}
        rows.append({"key": name, "label": _label(name, study),
                     **{k: clean(v) for k, v in item["stats"].items()},
                     "sharpe_diff": clean(vs.get("diff")), "sharpe_diff_low": clean(vs.get("low")),
                     "sharpe_diff_high": clean(vs.get("high")), "prob_positive": clean(vs.get("prob_positive"))})
    payload = {
        "generated": date.today().isoformat(), "start": study["start"], "end": study["end"],
        "n_months": study["n_months"], "benchmark": study["benchmark"], "base_cost": study["base_cost"],
        "high_cost": study["high_cost"], "realistic_cost": study["realistic_cost"],
        "n_strategies_tested": study["n_strategies_tested"], "strategies": rows,
        "walk_forward": study["walk_forward"]["choices"],
        "rank_correlation": clean(study["stability"]["rank_correlation"]),
        "conclusion": conclusion_lines(study),
    }
    from src.results import write_results_json

    return write_results_json(payload, output_path, kind="research", start=study["start"], end=study["end"],
                              notes=[study["data_note"]] if study.get("data_note") else None)


def _pct(value, digits: int = 1) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:.{digits}%}"


def _num(value, digits: int = 2) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:.{digits}f}"


def _label(name: str, study: dict) -> str:
    return STRATEGY_LABELS.get(name, name).format(benchmark=study["benchmark"], bond=study["bond"] or "obligataire")


def conclusion_lines(study: dict) -> list[str]:
    """Conclusion factuelle (aucune recommandation d'allocation)."""
    better = [n for n, r in study["results"].items() if r["vs_benchmark"] and r["vs_benchmark"]["low"] > 0]
    worse = [n for n, r in study["results"].items() if r["vs_benchmark"] and r["vs_benchmark"]["high"] < 0]
    lines = []
    if better:
        lines.append("- Sharpe supérieur au Buy & Hold avec un intervalle à 90 % entièrement positif : "
                     + ", ".join(_label(n, study) for n in better) + ".")
    else:
        lines.append(f"- Aucune stratégie ne bat le Buy & Hold {study['benchmark']} en Sharpe de façon statistiquement "
                     "robuste sur cette période (tous les intervalles à 90 % contiennent zéro ou sont négatifs).")
    if worse:
        lines.append("- Sharpe significativement inférieur au Buy & Hold : "
                     + ", ".join(_label(n, study) for n in worse) + ".")
    corr = study["stability"]["rank_correlation"]
    lines.append(f"- Stabilité de la grille Momentum : corrélation de rang {corr:.2f} entre les deux moitiés de la "
                 "période " + ("(classement plutôt stable)." if corr > 0.5 else
                               "(classement instable : les « meilleurs » paramètres d'hier ne le restent pas)."))
    lines.append(f"- {study['n_strategies_tested']} variantes testées : le meilleur résultat observé est probablement "
                 "surestimé (tests multiples) ; ne retenir que des écarts robustes et explicables.")
    lines.append("- Le choix de la stratégie à suivre reste une décision humaine (`paper-decision`).")
    return lines


def save_heatmap(study: dict, output_path: str | Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    table = study["stability"]["table"]["sharpe_total"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    for ax, vt in zip(axes, ("noVT", "VT"), strict=True):
        grid = pd.DataFrame(index=LOOKBACKS, columns=MA_WINDOWS, dtype=float)
        for lb in LOOKBACKS:
            for ma in MA_WINDOWS:
                grid.loc[lb, ma] = table.get(f"L{lb}-MA{ma}-top1-{vt}", np.nan)
        image = ax.imshow(grid.to_numpy(dtype=float), cmap="RdYlGn", vmin=0, vmax=1.2)
        ax.set_xticks(range(len(MA_WINDOWS)), [f"MA{m}" for m in MA_WINDOWS])
        ax.set_yticks(range(len(LOOKBACKS)), [f"{lb} mois" for lb in LOOKBACKS])
        for i, lb in enumerate(LOOKBACKS):
            for j, ma in enumerate(MA_WINDOWS):
                ax.text(j, i, _num(grid.loc[lb, ma]), ha="center", va="center", fontsize=9)
        ax.set_title(f"Sharpe, top 1, {'avec' if vt == 'VT' else 'sans'} VT")
    fig.colorbar(image, ax=axes, shrink=0.8)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return path


def generate_research_report(study: dict, output_path: str | Path, *, heatmap: Path | None = None,
                             data_note: str | None = None) -> Path:
    path = Path(output_path)
    realistic = study["realistic_cost"]
    lines = [
        "# Robustesse des stratégies — quelle stratégie suivre ?", "",
        f"Date de génération : {date.today().isoformat()}", "",
        "Étude de recherche : elle fournit des preuves, **elle ne change pas la stratégie suivie**. "
        "Aucun ordre n'est exécuté.", "",
        *([f"> **Données** : {data_note}", ""] if data_note else []),
        "## Méthode", "",
        f"- Fenêtre commune : {study['start']} → {study['end']} ({study['n_months']} mois), mêmes mois pour toutes "
        "les stratégies ; signal de fin de mois appliqué le mois suivant ; cash explicite.",
        f"- Frais : {study['base_cost']:.2%} par côté traité (colonne CAGR), {study['high_cost']:.2%} en "
        "sensibilité" + (f", barème réel équivalent {realistic:.2%}." if realistic is not None else "."),
        f"- Grille Momentum : {len(LOOKBACKS) * len(MA_WINDOWS) * len(TOP_NS) * 2} configurations ; walk-forward par "
        f"blocs de {TEST_BLOCK_MONTHS} mois, paramètres choisis sur tout le passé disponible (≥ {MIN_TRAIN_MONTHS} mois).",
        f"- Intervalle de confiance à 90 % de l'écart de Sharpe avec le Buy & Hold : bootstrap par blocs circulaires "
        f"de {BOOTSTRAP_BLOCK} mois ({BOOTSTRAP_SAMPLES} tirages, rendements appariés).", "",
        "## Tableau de preuves", "",
        "| Stratégie | CAGR | Volatilité | Sharpe | Écart de Sharpe vs B&H [IC 90 %] | P(écart > 0) | Max drawdown | "
        f"Turnover / an | CAGR à {study['high_cost']:.2%}" + (" | CAGR barème réel" if realistic is not None else "") + " |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---:" + (" | ---:" if realistic is not None else "") + " |",
    ]
    order = ["benchmark", "momentum_vt", "momentum", "momentum_walk_forward", "dual_momentum",
             "top3_trend", "inverse_vol", "static_80_20", "static_60_40"]
    for name in [n for n in order if n in study["results"]]:
        item = study["results"][name]
        s, vs = item["stats"], item["vs_benchmark"]
        gap = "—" if vs is None else f"{vs['diff']:+.2f} [{vs['low']:+.2f} ; {vs['high']:+.2f}]"
        prob = "—" if vs is None else f"{vs['prob_positive']:.0%}"
        row = (f"| {_label(name, study)} | {_pct(s['cagr'])} | {_pct(s['volatility'])} | {_num(s['sharpe'])} | {gap} | "
               f"{prob} | {_pct(s['max_drawdown'])} | {_pct(s.get('turnover_per_year'), 0)} | "
               f"{_pct(s.get('cagr_high_cost'))}")
        if realistic is not None:
            row += f" | {_pct(s.get('cagr_realistic_cost'))}"
        lines.append(row + " |")
    lines += ["", "## Conclusion factuelle", ""] + conclusion_lines(study)
    lines += ["", "## Paramètres choisis en walk-forward", "", "| Bloc testé | Configuration choisie | Sharpe en entraînement |",
              "| --- | --- | ---: |"]
    for choice in study["walk_forward"]["choices"]:
        lines.append(f"| {choice['test_start']} → {choice['test_end']} | {choice['config']} | {_num(choice['train_sharpe'])} |")
    stability = study["stability"]
    lines += ["", "## Stabilité de la grille Momentum", "",
              f"Corrélation de rang des Sharpe entre les deux moitiés (coupure {stability['split_date']}) : "
              f"**{stability['rank_correlation']:.2f}**.", ""]
    if heatmap is not None:
        try:
            rel = Path(heatmap).resolve().relative_to(path.parent.resolve()).as_posix()
        except ValueError:
            rel = Path(heatmap).as_posix()
        lines += [f"![Sharpe de la grille]({rel})", ""]
    lines += ["| Configuration | Sharpe total | 1re moitié | 2e moitié |", "| --- | ---: | ---: | ---: |"]
    table = stability["table"]
    for key, row in pd.concat([table.head(5), table.tail(3)]).iterrows():
        lines.append(f"| {key} | {_num(row['sharpe_total'])} | {_num(row['sharpe_1re_moitie'])} | "
                     f"{_num(row['sharpe_2e_moitie'])} |")
    lines += ["", "_5 meilleures et 3 moins bonnes configurations sur la fenêtre commune._", "",
              "## Limites", "",
              "- Historique court (≈ 7-8 ans de fenêtre commune) et univers restreint ; un seul grand krach (2020).",
              "- Données Yahoo Finance ; fiscalité non incluse (neutre dans un PEA tant qu'aucun retrait n'a lieu).",
              "- Les performances passées ne préjugent pas des performances futures.", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path

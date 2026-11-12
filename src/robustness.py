"""Robustesse des stratégies sur historique long : fiables ou chanceuses ?

Pour chaque stratégie du registre (``src/strategies.py``), sur l'historique long
en EUR (partiellement synthétique, voir ``config/long_history.yaml``) :

1. **Sharpe probabiliste** (PSR) : probabilité que le vrai Sharpe soit positif,
   en tenant compte de l'asymétrie et des queues épaisses ; **Sharpe dégonflé**
   (DSR, Bailey et López de Prado) : même test contre le meilleur Sharpe
   qu'on obtiendrait par hasard après avoir essayé ``n_trials`` variantes.
2. **Fenêtres glissantes de 5 ans** contre le Buy & Hold : part des fenêtres où
   la stratégie a un meilleur rendement, un meilleur Sharpe, une baisse
   maximale moins profonde.
3. **Sous-périodes** de 5 ans (2008-2012, 2013-2017, 2018-2022, 2023-aujourd'hui).
4. **Sensibilité aux paramètres** (grilles) : le réglage par défaut est-il sur
   un plateau (voisins proches aussi bons) ou sur un pic isolé (sur-ajustement) ?
5. **Walk-forward** : choisir chaque année les paramètres sur le passé
   seulement, puis mesurer l'année suivante ; même chose pour le choix de la
   stratégie elle-même (« méta-sélection »).
6. **Frais triplés**.

Trois verdicts distincts par stratégie :

- **fiabilité** (robuste / acceptable / fragile) : la stratégie tient-elle quand
  on change de période, de réglage ou de frais, après correction des tests
  multiples ?
- **surperformance** (démontrée / possible / non démontrée) : son avantage sur
  le Buy & Hold résiste-t-il à l'incertitude et au nombre d'essais ?
- **protection** (forte / moyenne / faible) : limite-t-elle les baisses par
  rapport au Buy & Hold ? **« Optimisée » ne veut pas dire « la meilleure sur le
passé »** : le réglage recommandé est le centre du plateau, jamais le pic, et
aucune configuration n'est modifiée automatiquement. Aucun ordre n'est passé.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import date
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

from src.backtest import CASH_COLUMN
from src.engine import net_returns, run_backtest, run_strategies
from src.research import MIN_TRAIN_MONTHS, TEST_BLOCK_MONTHS, walk_forward_selection
from src.signals import lag_weights_for_execution
from src.strategies import (
    StrategyContext,
    available_strategies,
    dual_momentum_target,
    inverse_vol_target,
    momentum_target,
)
from src.strategies import label as strategy_label

ROLLING_MONTHS = 60
COST_MULTIPLIER = 3.0
PERIODS = (("2004-2007", "2004-01-01", "2007-12-31"), ("2008-2012", "2008-01-01", "2012-12-31"),
           ("2013-2017", "2013-01-01", "2017-12-31"), ("2018-2022", "2018-01-01", "2022-12-31"),
           ("2023-auj.", "2023-01-01", "2100-12-31"))
EULER_GAMMA = 0.5772156649015329

PARAM_GRIDS: dict[str, dict[str, tuple]] = {
    "momentum": {"lookback": (6, 9, 12), "ma": (6, 10, 12), "top_n": (1, 2, 3)},
    "momentum_vt": {"target_vol": (0.08, 0.10, 0.12, 0.15), "vol_window": (3, 6, 12)},
    "top3_trend": {"lookback": (6, 9, 12), "ma": (6, 10, 12), "top_n": (2, 3, 4)},
    "dual_momentum": {"lookback": (6, 9, 12)},
    "inverse_vol": {"window": (6, 12, 24)},
}
PARAM_LABELS = {"lookback": "momentum (mois)", "ma": "moyenne mobile (mois)", "top_n": "nombre d'ETF",
                "target_vol": "volatilité cible", "vol_window": "fenêtre de volatilité (mois)",
                "window": "fenêtre de volatilité (mois)"}


# --------------------------------------------------------------------------- #
# Statistiques
# --------------------------------------------------------------------------- #
def _clean(returns: pd.Series) -> np.ndarray:
    return returns.dropna().to_numpy(dtype=float)


def monthly_sharpe(returns: pd.Series) -> float | None:
    r = _clean(returns)
    if len(r) < 2 or r.std(ddof=1) == 0:
        return None
    return float(r.mean() / r.std(ddof=1))


def annual_sharpe(returns: pd.Series) -> float | None:
    sr = monthly_sharpe(returns)
    return None if sr is None else sr * np.sqrt(12)


def probabilistic_sharpe(returns: pd.Series, sr_benchmark: float = 0.0) -> float | None:
    """Probabilité que le Sharpe (mensuel) dépasse ``sr_benchmark`` (Bailey et López de Prado, 2012)."""
    r = _clean(returns)
    if len(r) < 24 or r.std(ddof=1) == 0:
        return None
    sr = r.mean() / r.std(ddof=1)
    centered = r - r.mean()
    std_pop = r.std(ddof=0)
    skew = float((centered ** 3).mean() / std_pop ** 3)
    kurt = float((centered ** 4).mean() / std_pop ** 4)
    variance = max(1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr ** 2, 1e-12)
    return float(NormalDist().cdf((sr - sr_benchmark) * np.sqrt(len(r) - 1) / np.sqrt(variance)))


def expected_max_sharpe(n_trials: int, sr_std: float) -> float:
    """Meilleur Sharpe (mensuel) attendu par hasard parmi ``n_trials`` essais de vrai Sharpe nul."""
    if n_trials <= 1 or sr_std <= 0:
        return 0.0
    nd = NormalDist()
    return float(sr_std * ((1 - EULER_GAMMA) * nd.inv_cdf(1 - 1 / n_trials)
                           + EULER_GAMMA * nd.inv_cdf(1 - 1 / (n_trials * np.e))))


def deflated_sharpe(returns: pd.Series, n_trials: int, sr_std: float) -> float | None:
    return probabilistic_sharpe(returns, expected_max_sharpe(n_trials, sr_std))


def max_drawdown(returns: pd.Series) -> float:
    growth = (1.0 + returns.fillna(0.0)).cumprod()
    return float((growth / growth.cummax().clip(lower=1.0) - 1.0).min())


def cagr(returns: pd.Series) -> float | None:
    r = returns.dropna()
    if r.empty:
        return None
    return float((1.0 + r).prod() ** (12.0 / len(r)) - 1.0)


def describe(returns: pd.Series) -> dict:
    """Statistiques descriptives d'une série de rendements mensuels nets."""
    r = returns.dropna()
    yearly = (1.0 + r).groupby(r.index.year).prod() - 1.0
    counts = r.groupby(r.index.year).size()
    full_years = yearly[counts >= 12]
    sharpe = annual_sharpe(r)
    return {
        "cagr": cagr(r), "volatility": float(r.std() * np.sqrt(12)) if len(r) > 1 else None,
        "sharpe": sharpe, "max_drawdown": max_drawdown(r),
        "worst_year": float(full_years.min()) if not full_years.empty else None,
        "best_year": float(full_years.max()) if not full_years.empty else None,
        "positive_months": float((r > 0).mean()) if len(r) else None,
        "worst_month": float(r.min()) if len(r) else None,
        "calendar": {int(y): float(v) for y, v in yearly.items()},
        "n_months": int(len(r)),
    }


def rolling_comparison(strategy: pd.Series, benchmark: pd.Series, window: int = ROLLING_MONTHS) -> dict | None:
    """Fenêtres glissantes de ``window`` mois (pas mensuel) contre la référence."""
    paired = pd.concat([strategy, benchmark], axis=1, join="inner").dropna()
    if len(paired) < window + 1:
        return None
    rows = []
    for end in range(window, len(paired) + 1):
        chunk = paired.iloc[end - window:end]
        s, b = chunk.iloc[:, 0], chunk.iloc[:, 1]
        rows.append({"end": chunk.index[-1], "cagr_s": cagr(s), "cagr_b": cagr(b), "sharpe_s": annual_sharpe(s),
                     "sharpe_b": annual_sharpe(b), "dd_s": max_drawdown(s), "dd_b": max_drawdown(b)})
    table = pd.DataFrame(rows).set_index("end")
    excess = table["cagr_s"] - table["cagr_b"]
    return {
        "window_months": window, "n_windows": int(len(table)),
        "pct_better_return": float((excess > 0).mean()),
        "pct_better_sharpe": float((table["sharpe_s"].fillna(-9) > table["sharpe_b"].fillna(-9)).mean()),
        "pct_shallower_drawdown": float((table["dd_s"] > table["dd_b"]).mean()),
        "median_excess_cagr": float(excess.median()), "worst_excess_cagr": float(excess.min()),
        "best_excess_cagr": float(excess.max()), "worst_window_cagr": float(table["cagr_s"].min()),
        "excess_series": {d.date().isoformat(): float(v) for d, v in excess.items()},
    }


def worst_window_cagr(returns: pd.Series, window: int = ROLLING_MONTHS) -> float | None:
    """Pire rendement annualisé sur une fenêtre glissante de ``window`` mois."""
    r = returns.dropna()
    if len(r) < window:
        return None
    log_growth = np.log1p(r.to_numpy(dtype=float))
    sums = np.convolve(log_growth, np.ones(window), mode="valid")
    return float(np.expm1(sums.min() * 12.0 / window))


def subperiods(returns: pd.Series, synthetic: pd.Series | None = None, periods=PERIODS) -> list[dict]:
    rows = []
    for name, start, end in periods:
        chunk = returns.loc[start:end].dropna()
        if len(chunk) < 12:
            continue
        share = None if synthetic is None else float(synthetic.loc[start:end].mean())
        rows.append({"période": name, "cagr": cagr(chunk), "sharpe": annual_sharpe(chunk),
                     "max_drawdown": max_drawdown(chunk), "n_months": int(len(chunk)), "part_synthetique": share})
    return rows


# --------------------------------------------------------------------------- #
# Grilles de paramètres
# --------------------------------------------------------------------------- #
def _default_params(name: str, config) -> dict:
    if name == "momentum":
        m = config.momentum
        return {"lookback": m.lookback_months, "ma": m.moving_average_window, "top_n": m.top_n}
    if name == "momentum_vt":
        v = config.volatility_targeting
        return {"target_vol": v.target_volatility, "vol_window": v.volatility_window}
    return {"top3_trend": {"lookback": 12, "ma": 10, "top_n": 3}, "dual_momentum": {"lookback": 12},
            "inverse_vol": {"window": 12}}[name]


def grid_for(name: str, config) -> dict[str, tuple]:
    """Grille de la stratégie, complétée si besoin par le réglage par défaut."""
    grid = {k: tuple(v) for k, v in PARAM_GRIDS[name].items()}
    for key, value in _default_params(name, config).items():
        if value not in grid[key]:
            grid[key] = tuple(sorted((*grid[key], value)))
    return grid


def params_key(params: dict) -> str:
    return " ".join(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}" for k, v in params.items())


def build_variant(name: str, params: dict, monthly: pd.DataFrame, ctx: StrategyContext) -> pd.DataFrame:
    """Poids cibles d'une variante paramétrée (mêmes constructeurs que le registre)."""
    config = ctx.config
    equities = [c for c in ctx.equities if c in monthly.columns] or [c for c in monthly.columns if c != ctx.bond]
    if name in ("momentum", "top3_trend"):
        skip = 1 if params["lookback"] > 1 else 0
        return momentum_target(monthly, config, lookback=params["lookback"], skip=skip, ma=params["ma"],
                               top_n=params["top_n"])
    if name == "momentum_vt":
        vt = replace(config.volatility_targeting, target_volatility=params["target_vol"],  # type: ignore[attr-defined]
                     volatility_window=params["vol_window"])
        return momentum_target(monthly, replace(config, volatility_targeting=vt), vt=True)  # type: ignore[type-var]
    if name == "dual_momentum":
        if not ctx.bond:
            raise ValueError("Le dual momentum nécessite un obligataire.")
        return dual_momentum_target(monthly, equities, ctx.bond, lookback=params["lookback"])
    if name == "inverse_vol":
        return inverse_vol_target(monthly, equities, params["window"])
    raise ValueError(f"Pas de grille pour {name}.")


def _neighbors(params: dict, grid: dict[str, tuple]) -> list[dict]:
    out = []
    for key, values in grid.items():
        i = values.index(params[key])
        for j in (i - 1, i + 1):
            if 0 <= j < len(values):
                out.append({**params, key: values[j]})
    return out


def grid_study(name: str, monthly: pd.DataFrame, ctx: StrategyContext, *, cost: float, start: pd.Timestamp,
               end: pd.Timestamp, benchmark: pd.Series | None = None) -> dict:
    """Sharpe de chaque réglage, plateau, walk-forward des paramètres."""
    grid = grid_for(name, ctx.config)
    combos = [dict(zip(grid, values, strict=True)) for values in itertools.product(*grid.values())]
    returns = {params_key(p): net_returns(monthly, lag_weights_for_execution(build_variant(name, p, monthly, ctx)), cost)
               for p in combos}
    window = {k: r.loc[start:end] for k, r in returns.items()}
    sharpes = {k: annual_sharpe(r) for k, r in window.items()}
    default = _default_params(name, ctx.config)
    default_key = params_key(default)
    ranked = sorted((k for k in sharpes if sharpes[k] is not None), key=lambda k: -(sharpes[k] or 0.0))

    def plateau_score(params: dict) -> float:
        keys = [params_key(p) for p in [params, *_neighbors(params, grid)]]
        values = [v for v in (sharpes.get(k) for k in keys) if v is not None]
        return float(np.mean(values)) if values else -np.inf

    plateau = max(combos, key=plateau_score)
    neighbor_values = [v for v in (sharpes.get(params_key(p)) for p in _neighbors(default, grid)) if v is not None]
    default_sharpe = sharpes.get(default_key)
    ratio = None
    if default_sharpe and default_sharpe > 0 and neighbor_values:
        ratio = float(min(neighbor_values) / default_sharpe)
    wf = None
    test_start = start + pd.offsets.MonthEnd(MIN_TRAIN_MONTHS)
    if len(combos) > 1 and test_start < end:
        try:
            selection = walk_forward_selection(returns, test_start, end, min_train=MIN_TRAIN_MONTHS,
                                               block=TEST_BLOCK_MONTHS)
            oos = selection["returns"]
            wf = {"sharpe": annual_sharpe(oos), "default_sharpe_same_months": annual_sharpe(returns[default_key].loc[oos.index]),
                  "start": oos.index.min().date().isoformat(), "choices": selection["choices"]}
        except ValueError:
            wf = None
    table = [{"params": k, "sharpe": sharpes[k], "cagr": cagr(window[k]), "max_drawdown": max_drawdown(window[k])}
             for k in ranked]
    return {
        "grid": {k: list(v) for k, v in grid.items()}, "n_configs": len(combos), "default": default_key,
        "default_sharpe": default_sharpe, "default_rank": ranked.index(default_key) + 1 if default_key in ranked else None,
        "best": ranked[0] if ranked else None, "best_sharpe": sharpes[ranked[0]] if ranked else None,
        "plateau": params_key(plateau), "plateau_sharpe": sharpes.get(params_key(plateau)),
        "neighbors_min_ratio": ratio, "walk_forward": wf, "table": table,
        "_monthly_sharpes": [monthly_sharpe(r) for r in window.values()],
        "_excess_sharpes": [] if benchmark is None else
        [monthly_sharpe((r - benchmark).dropna()) for r in window.values()],
    }


# --------------------------------------------------------------------------- #
# Étude complète
# --------------------------------------------------------------------------- #
def _criteria(name: str, item: dict) -> list[dict]:
    """Critères de **fiabilité** (la stratégie tient-elle ?), pas de surperformance."""
    crit = []
    psr = item["psr"]
    crit.append({"critère": "Sharpe réellement positif (PSR ≥ 95 %)", "ok": None if psr is None else psr >= 0.95,
                 "détail": "n/a" if psr is None else f"PSR {psr:.0%}"})
    dsr = item["dsr"]
    crit.append({"critère": "Résiste aux tests multiples (Sharpe dégonflé ≥ 90 %)",
                 "ok": None if dsr is None else dsr >= 0.90, "détail": "n/a" if dsr is None else f"DSR {dsr:.0%}"})
    positive = [p for p in item["subperiods"] if p["sharpe"] is not None]
    ok_periods = sum(1 for p in positive if p["sharpe"] > 0)
    crit.append({"critère": "Sharpe positif dans chaque sous-période de 5 ans",
                 "ok": ok_periods == len(positive) if positive else None,
                 "détail": f"{ok_periods}/{len(positive)} sous-périodes"})
    worst = item["stats"].get("worst_5y_cagr")
    crit.append({"critère": "Aucune fenêtre de 5 ans perdante (CAGR ≥ 0)",
                 "ok": None if worst is None else worst >= 0,
                 "détail": "n/a" if worst is None else f"pire fenêtre {worst:+.1%} par an"})
    grid = item.get("grid")
    if grid is not None:
        ratio = grid["neighbors_min_ratio"]
        crit.append({"critère": "Réglage sur un plateau (voisins ≥ 80 % du Sharpe)",
                     "ok": None if ratio is None else ratio >= 0.8,
                     "détail": "n/a" if ratio is None else f"pire voisin {ratio:.0%} du Sharpe par défaut"})
        wf = grid["walk_forward"]
        if wf and wf["sharpe"] is not None and wf["default_sharpe_same_months"] is not None:
            gap = wf["sharpe"] - wf["default_sharpe_same_months"]
            crit.append({"critère": "Paramètres choisis sur le passé ≈ réglage par défaut (walk-forward, écart ≥ −0,10)",
                         "ok": gap >= -0.10, "détail": f"écart de Sharpe {gap:+.2f}"})
    drop = item["costs"]["sharpe_drop"]
    crit.append({"critère": f"Frais × {COST_MULTIPLIER:g} : Sharpe en baisse de moins de 0,10",
                 "ok": None if drop is None else drop < 0.10, "détail": "n/a" if drop is None else f"−{drop:.2f}"})
    return crit


def _verdict(criteria: list[dict]) -> tuple[float, str]:
    applicable = [c for c in criteria if c["ok"] is not None]
    if not applicable:
        return 0.0, "non évaluable"
    score = sum(1 for c in applicable if c["ok"]) / len(applicable)
    return score, "robuste" if score >= 0.8 else "acceptable" if score >= 0.6 else "fragile"


def _edge(item: dict) -> dict:
    """Surperformance vs Buy & Hold : démontrée / possible / non démontrée."""
    rolling, psr, dsr = item["rolling"], item.get("excess_psr"), item.get("excess_dsr")
    if rolling is None or psr is None:
        return {"verdict": "n/a", "text": "Comparaison impossible (historique trop court)."}
    share = rolling["pct_better_sharpe"]
    if psr >= 0.95 and (dsr or 0.0) >= 0.90 and share >= 0.6:
        verdict = "démontrée"
    elif psr >= 0.75 or share >= 0.5:
        verdict = "possible"
    else:
        verdict = "non démontrée"
    return {"verdict": verdict,
            "text": f"meilleur Sharpe que le Buy & Hold dans {share:.0%} des fenêtres de 5 ans ; probabilité d'un "
                    f"surplus de rendement réel {psr:.0%}, {_pct(dsr, 0)} après correction des "
                    f"tests multiples ; surplus médian {rolling['median_excess_cagr']:+.1%} par an."}


def _protection(item: dict, benchmark_dd: float) -> dict:
    """Protection contre les baisses vs Buy & Hold : forte / moyenne / faible."""
    rolling = item["rolling"]
    dd = item["stats"]["max_drawdown"]
    if rolling is None or benchmark_dd >= 0:
        return {"verdict": "n/a", "text": "Comparaison impossible."}
    share = rolling["pct_shallower_drawdown"]
    ratio = dd / benchmark_dd
    if share >= 0.75 and ratio <= 0.7:
        verdict = "forte"
    elif share >= 0.5 or ratio <= 0.85:
        verdict = "moyenne"
    else:
        verdict = "faible"
    return {"verdict": verdict, "text": f"baisse maximale {dd:.0%} contre {benchmark_dd:.0%} pour le Buy & Hold ; "
                                        f"baisse moins profonde dans {share:.0%} des fenêtres de 5 ans."}


def _beats_benchmark(item: dict) -> dict:
    rolling, excess_psr = item["rolling"], item.get("excess_psr")
    if rolling is None or excess_psr is None:
        return {"verdict": "n/a", "text": "Comparaison impossible (historique trop court)."}
    share = rolling["pct_better_sharpe"]
    if share >= 0.7 and excess_psr >= 0.9:
        verdict, text = "oui", "bat le Buy & Hold de façon régulière et statistiquement solide"
    elif share >= 0.4:
        verdict, text = "parfois", "bat le Buy & Hold dans certaines périodes seulement, sans preuve statistique"
    else:
        verdict, text = "rarement", "fait rarement mieux que le Buy & Hold en rendement ajusté du risque"
    return {"verdict": verdict, "text": f"{text} (meilleur Sharpe dans {share:.0%} des fenêtres de 5 ans, "
                                        f"probabilité d'un surplus positif {excess_psr:.0%})."}


def run_robustness(monthly: pd.DataFrame, ctx: StrategyContext, *, transaction_cost: float,
                   synthetic: pd.Series | None = None, followed: str | None = None) -> dict:
    """Étude de robustesse complète (voir la docstring du module)."""
    names = available_strategies(monthly, ctx)
    runs = run_strategies(monthly, ctx, cost=transaction_cost, names=names)
    executed = {n: run.executed for n, run in runs.items()}
    returns = {n: run.returns for n, run in runs.items()}
    high = {n: net_returns(monthly, w, transaction_cost * COST_MULTIPLIER) for n, w in executed.items()}
    starts = [r.dropna().index.min() for r in returns.values() if not r.dropna().empty]
    start, end = max(starts), monthly.index.max()
    bench_full = returns["benchmark"]
    grids = {n: grid_study(n, monthly, ctx, cost=transaction_cost, start=start, end=end, benchmark=bench_full)
             for n in names if n in PARAM_GRIDS}
    # Nombre d'essais et dispersion des Sharpe pour le Sharpe dégonflé.
    raw = [monthly_sharpe(r.loc[start:end]) for r in returns.values()]
    raw += [s for g in grids.values() for s in g.pop("_monthly_sharpes")]
    all_sharpes: list[float] = [s for s in raw if s is not None]
    raw = [monthly_sharpe((r - bench_full).loc[start:end].dropna()) for n, r in returns.items() if n != "benchmark"]
    raw += [s for g in grids.values() for s in g.pop("_excess_sharpes")]
    excess_sharpes: list[float] = [s for s in raw if s is not None]
    excess_std = float(np.std(excess_sharpes, ddof=1)) if len(excess_sharpes) > 1 else 0.0
    n_trials = len(all_sharpes)
    sr_std = float(np.std(all_sharpes, ddof=1)) if n_trials > 1 else 0.0
    benchmark = returns["benchmark"].loc[start:end]
    strategies: dict[str, dict[str, Any]] = {}
    for name in names:
        r = returns[name].loc[start:end]
        excess = (r - benchmark).dropna()
        base_sharpe, high_sharpe = annual_sharpe(r), annual_sharpe(high[name].loc[start:end])
        item: dict[str, Any] = {
            "label": strategy_label(name, ctx), "stats": describe(r),
            "psr": probabilistic_sharpe(r), "dsr": deflated_sharpe(r, n_trials, sr_std),
            "excess_psr": None if name == "benchmark" else probabilistic_sharpe(excess),
            "excess_dsr": None if name == "benchmark" else deflated_sharpe(excess, len(excess_sharpes), excess_std),
            "rolling": None if name == "benchmark" else rolling_comparison(r, benchmark),
            "subperiods": subperiods(r, synthetic),
            "costs": {"sharpe": base_sharpe, "sharpe_high_cost": high_sharpe,
                      "sharpe_drop": None if base_sharpe is None or high_sharpe is None else
                      max(0.0, base_sharpe - high_sharpe)},
            "grid": grids.get(name),
        }
        item["stats"]["worst_5y_cagr"] = worst_window_cagr(r)
        # Activité : rotation annuelle (aller simple), mois avec un rééquilibrage notable, part investie.
        weights = executed[name].loc[start:end]
        change = runs[name].backtest.loc[start:end, "Turnover"]
        item["stats"]["turnover_per_year"] = float(change.mean() * 12) if len(change) else None
        item["stats"]["rebalances_per_year"] = float((change > 0.025).mean() * 12) if len(change) else None
        item["stats"]["avg_exposure"] = float(1.0 - weights[CASH_COLUMN].mean())
        item["criteria"] = _criteria(name, item)
        item["score"], item["verdict"] = _verdict(item["criteria"])
        item["beats_benchmark"] = _beats_benchmark(item) if name != "benchmark" else None
        item["edge"] = _edge(item) if name != "benchmark" else None
        strategies[name] = item
    benchmark_dd = strategies["benchmark"]["stats"]["max_drawdown"]
    for name, item in strategies.items():
        item["protection"] = _protection(item, benchmark_dd) if name != "benchmark" else None
    # Méta-sélection : chaque année, la stratégie au meilleur Sharpe passé.
    meta = None
    test_start = start + pd.offsets.MonthEnd(MIN_TRAIN_MONTHS)
    if test_start < end:
        selection = walk_forward_selection({n: r.loc[start:] for n, r in returns.items()}, test_start, end,
                                           min_train=MIN_TRAIN_MONTHS, block=TEST_BLOCK_MONTHS)
        selected = pd.DataFrame(0., index=monthly.index, columns=[*monthly.columns, CASH_COLUMN])
        selected[CASH_COLUMN] = 1.
        for choice in selection["choices"]:
            block = executed[choice["config"]].loc[choice["test_start"]:choice["test_end"]]
            selected.loc[block.index] = block.reindex(columns=selected.columns, fill_value=0.)
        oos = run_backtest(monthly, selected, transaction_cost)["Net Return"].loc[selection["returns"].index]
        meta = {"sharpe": annual_sharpe(oos), "cagr": cagr(oos), "max_drawdown": max_drawdown(oos),
                "benchmark_sharpe": annual_sharpe(benchmark.loc[oos.index]),
                "benchmark_cagr": cagr(benchmark.loc[oos.index]),
                "followed_sharpe": annual_sharpe(returns[followed].loc[oos.index]) if followed in returns else None,
                "start": oos.index.min().date().isoformat(), "choices": selection["choices"]}
    series = pd.DataFrame({n: returns[n].loc[start:end] for n in names})
    return {"start": start.date().isoformat(), "end": end.date().isoformat(), "n_months": int(len(benchmark)),
            "n_trials": n_trials, "sr_std_monthly": sr_std, "followed": followed, "transaction_cost": transaction_cost,
            "synthetic_share": None if synthetic is None else float(synthetic.loc[start:end].mean()),
            "strategies": strategies, "meta_selection": meta, "series": series}


# --------------------------------------------------------------------------- #
# Sorties
# --------------------------------------------------------------------------- #
def _pct(value, digits: int = 1) -> str:
    return "n/a" if value is None or (isinstance(value, float) and np.isnan(value)) else f"{value:.{digits}%}"


def _num(value, digits: int = 2) -> str:
    return "n/a" if value is None or (isinstance(value, float) and np.isnan(value)) else f"{value:.{digits}f}"


def conclusion_lines(study: dict) -> list[str]:
    items = study["strategies"]
    robust = [v["label"] for v in items.values() if v["verdict"] == "robuste"]
    fragile = [v["label"] for v in items.values() if v["verdict"] == "fragile"]
    winners = [v["label"] for v in items.values() if (v["edge"] or {}).get("verdict") == "démontrée"]
    protective = [v["label"] for v in items.values() if (v["protection"] or {}).get("verdict") == "forte"]
    lines = [f"- Fiabilité « robuste » : {', '.join(robust) or 'aucune stratégie'} ; « fragile » : "
             f"{', '.join(fragile) or 'aucune'}."]
    lines.append("- Surperformance démontrée face au Buy & Hold (après correction des tests multiples) : "
                 + (", ".join(winners) if winners else "aucune stratégie") + ".")
    lines.append("- Protection forte contre les baisses : " + (", ".join(protective) if protective else "aucune") + ".")
    meta = study["meta_selection"]
    if meta and meta["sharpe"] is not None and meta["benchmark_sharpe"] is not None:
        lines.append(f"- Choisir chaque année la stratégie qui a le mieux marché (méta-sélection) donne un Sharpe "
                     f"hors échantillon de {meta['sharpe']:.2f}, contre {meta['benchmark_sharpe']:.2f} pour le Buy & "
                     "Hold : " + ("courir après la meilleure stratégie récente n'aide pas." if meta["sharpe"] <
                                  meta["benchmark_sharpe"] else "la méta-sélection n'a pas été pénalisante ici."))
    lines.append(f"- {study['n_trials']} variantes évaluées au total : le Sharpe dégonflé corrige ce nombre d'essais.")
    lines.append("- Aucun réglage n'est modifié automatiquement ; un réglage « plateau » différent du défaut est une "
                 "piste à suivre en paper trading, pas une consigne.")
    return lines


def generate_robustness_report(study: dict, output_path: str | Path) -> Path:
    items = study["strategies"]
    lines = [
        "# Robustesse des stratégies (historique long)", "",
        f"Date de génération : {date.today().isoformat()}", "",
        f"Fenêtre commune : {study['start']} → {study['end']} ({study['n_months']} mois). "
        f"**Part synthétique moyenne des prix : {_pct(study['synthetic_share'], 0)}** (proxys avant la cotation des "
        "ETF PEA). Frais de {:.2%} par côté traité. Aucun ordre, aucune stratégie modifiée.".format(
            study["transaction_cost"]), "",
        "## Verdicts", "",
        "| Stratégie | Fiabilité | Score | Surperformance vs B&H | Protection | CAGR | Sharpe | Max DD | PSR | DSR |",
        "| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, item in items.items():
        mark = " **(suivie)**" if name == study["followed"] else ""
        edge = (item["edge"] or {}).get("verdict", "référence")
        protection = (item["protection"] or {}).get("verdict", "référence")
        s = item["stats"]
        lines.append(f"| {item['label']}{mark} | **{item['verdict']}** | {item['score']:.0%} | {edge} | {protection} | "
                     f"{_pct(s['cagr'])} | {_num(s['sharpe'])} | {_pct(s['max_drawdown'])} | {_pct(item['psr'], 0)} | "
                     f"{_pct(item['dsr'], 0)} |")
    lines += ["", "## Conclusion", ""] + conclusion_lines(study)
    lines += ["", "## Détail des critères", ""]
    for item in items.values():
        lines += [f"### {item['label']} — {item['verdict']}", ""]
        if item["edge"]:
            lines += [f"- Surperformance **{item['edge']['verdict']}** : {item['edge']['text']}",
                      f"- Protection **{item['protection']['verdict']}** : {item['protection']['text']}", ""]
        lines += ["| Critère | Résultat | Détail |", "| --- | --- | --- |"]
        for c in item["criteria"]:
            mark = "n/a" if c["ok"] is None else ("oui" if c["ok"] else "**non**")
            lines.append(f"| {c['critère']} | {mark} | {c['détail']} |")
        lines += ["", "| Sous-période | CAGR | Sharpe | Max DD | Part synthétique |", "| --- | ---: | ---: | ---: | ---: |"]
        for p in item["subperiods"]:
            lines.append(f"| {p['période']} | {_pct(p['cagr'])} | {_num(p['sharpe'])} | {_pct(p['max_drawdown'])} | "
                         f"{_pct(p['part_synthetique'], 0)} |")
        grid = item["grid"]
        if grid:
            wf = grid["walk_forward"] or {}
            lines += ["", f"Réglages testés : {grid['n_configs']} ({', '.join(f'{PARAM_LABELS[k]} {v}' for k, v in grid['grid'].items())}). "
                          f"Défaut `{grid['default']}` : Sharpe {_num(grid['default_sharpe'])}, rang {grid['default_rank']}"
                          f"/{grid['n_configs']}. Meilleur sur le passé `{grid['best']}` ({_num(grid['best_sharpe'])}) ; "
                          f"centre du plateau `{grid['plateau']}` ({_num(grid['plateau_sharpe'])}). Walk-forward depuis "
                          f"{wf.get('start', 'n/a')} : Sharpe {_num(wf.get('sharpe'))} contre "
                          f"{_num(wf.get('default_sharpe_same_months'))} pour le défaut sur les mêmes mois."]
        lines.append("")
    meta = study["meta_selection"]
    if meta:
        lines += ["## Méta-sélection (choisir chaque année la meilleure stratégie passée)", "",
                  f"Hors échantillon depuis {meta['start']} : Sharpe {_num(meta['sharpe'])}, CAGR {_pct(meta['cagr'])}, "
                  f"max DD {_pct(meta['max_drawdown'])} ; Buy & Hold sur les mêmes mois : Sharpe "
                  f"{_num(meta['benchmark_sharpe'])}, CAGR {_pct(meta['benchmark_cagr'])}.", "",
                  "| Année testée | Stratégie choisie | Sharpe passé |", "| --- | --- | ---: |"]
        for c in meta["choices"]:
            lines.append(f"| {c['test_start'][:7]} → {c['test_end'][:7]} | {c['config']} | {_num(c['train_sharpe'])} |")
        lines.append("")
    lines += [
        "## Méthode et limites", "",
        "- Surperformance : PSR et DSR appliqués au surplus mensuel (stratégie − Buy & Hold), avec la dispersion des "
        "surplus de toutes les variantes testées.",
        "- PSR : probabilité que le vrai Sharpe soit positif, corrigée de l'asymétrie et des queues épaisses. DSR : "
        f"même test contre le meilleur Sharpe attendu par hasard après {study['n_trials']} essais.",
        f"- Fenêtres glissantes de {ROLLING_MONTHS} mois, pas mensuel (fenêtres qui se chevauchent : pas indépendantes).",
        "- Plateau : réglage dont la moyenne des Sharpe (lui et ses voisins immédiats dans la grille) est la plus haute.",
        f"- Walk-forward : paramètres choisis sur tout le passé disponible (≥ {MIN_TRAIN_MONTHS} mois), testés sur les "
        f"{TEST_BLOCK_MONTHS} mois suivants.",
        "- Données partiellement synthétiques avant la cotation des ETF PEA ; avant 2009, indice MSCI World de prix "
        "complété d'un rendement de dividende **estimé** (1,5 %/an net de frais, calibré sur CW8, `config/long_history.yaml`) ; cash non rémunéré.",
        "- Les performances passées ne préjugent pas des performances futures.", "",
    ]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def save_robustness_json(study: dict, output_path: str | Path) -> Path:
    """Résumé JSON (tableau de bord) avec les rendements mensuels nets de chaque stratégie."""
    from src.results import write_results_json

    series = study["series"]
    payload = {k: v for k, v in study.items() if k != "series"}
    payload["generated"] = date.today().isoformat()
    payload["conclusion"] = conclusion_lines(study)
    payload["series"] = {"dates": [d.date().isoformat() for d in series.index],
                         **{c: [None if pd.isna(v) else float(v) for v in series[c]] for c in series.columns}}
    return write_results_json(payload, output_path, kind="robustness", start=study["start"], end=study["end"],
                              synthetic_share=study["synthetic_share"], indent=1)

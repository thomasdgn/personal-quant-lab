"""Détection expérimentale de régimes de marché, sans exécution d'ordres.

Toutes les variables explicatives sont connues à la fin du mois observé. La
cible mesure le rendement des trois mois suivants et les splits temporels
purgent les observations dont la cible franchit une frontière d'échantillon.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

FEATURE_COLUMNS = [
    "momentum_1m",
    "momentum_3m",
    "momentum_6m",
    "momentum_12m",
    "vol_3m",
    "vol_6m",
    "vol_12m",
    "drawdown_actuel",
    "above_ma_12m",
]
TARGET_COLUMN = "target"
TARGET_END_COLUMN = "target_end"
_MONTH_END = "ME"


def _price_series(prices: pd.Series | pd.DataFrame, preferred: str = "CW8.PA") -> pd.Series:
    if not isinstance(prices, (pd.Series, pd.DataFrame)) or prices.empty:
        raise ValueError("Les prix doivent être une Series ou un DataFrame non vide.")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("L'index des prix doit être un DatetimeIndex.")
    if isinstance(prices, pd.DataFrame):
        if preferred in prices.columns:
            series = prices[preferred]
        else:
            counts = prices.notna().sum()
            if counts.empty or counts.max() == 0:
                raise ValueError("Aucun actif ne contient de prix exploitables.")
            series = prices[counts.idxmax()]
    else:
        series = prices
    series = series.sort_index()
    series = series[~series.index.duplicated(keep="last")].dropna().astype(float)
    if series.empty or (series <= 0).any():
        raise ValueError("Les prix doivent contenir des valeurs strictement positives.")
    return series


def build_feature_frame(
    prices_daily: pd.Series | pd.DataFrame,
    prices_monthly: pd.Series | pd.DataFrame,
) -> pd.DataFrame:
    """Construit features + cible forward, **sans** retirer les lignes incomplètes.

    Les derniers mois (cible encore inconnue) gardent leurs features et une
    cible ``NaN`` : ils servent à produire la probabilité de régime courante.
    Les volatilités utilisent respectivement 63, 126 et 252 rendements
    journaliers, puis leur dernière valeur disponible à la fin de chaque mois.
    """
    daily = _price_series(prices_daily)
    preferred = str(daily.name) if daily.name is not None else "CW8.PA"
    monthly = _price_series(prices_monthly, preferred=preferred)
    # Normalise toujours l'index sur les fins de mois afin d'aligner les sources.
    monthly = monthly.resample(_MONTH_END).last().dropna()
    # Une observation au milieu du dernier mois ne constitue pas une fin de mois
    # valide pour la cible M+3. Le dernier jour ouvré est l'approximation locale
    # documentée du dernier jour de cotation, sans calendrier de marché externe.
    last_daily = daily.index.max().normalize()
    expected_business_month_end = last_daily + pd.offsets.BMonthEnd(0)
    if last_daily < expected_business_month_end:
        monthly = monthly.loc[monthly.index.to_period("M") < last_daily.to_period("M")]
    daily_returns = daily.pct_change(fill_method=None)

    frame = pd.DataFrame(index=monthly.index)
    for months in (1, 3, 6, 12):
        frame[f"momentum_{months}m"] = monthly / monthly.shift(months) - 1.0
    for months, observations in ((3, 63), (6, 126), (12, 252)):
        daily_vol = daily_returns.rolling(observations, min_periods=observations).std() * math.sqrt(252)
        frame[f"vol_{months}m"] = daily_vol.resample(_MONTH_END).last().reindex(monthly.index)
    frame["drawdown_actuel"] = monthly / monthly.cummax() - 1.0
    moving_average = monthly.rolling(12, min_periods=12).mean()
    frame["above_ma_12m"] = (monthly > moving_average).astype(float).where(moving_average.notna())

    forward_return = monthly.shift(-3) / monthly - 1.0
    frame["forward_return_3m"] = forward_return
    frame[TARGET_COLUMN] = (forward_return > 0.0).astype(float).where(forward_return.notna())
    frame[TARGET_END_COLUMN] = monthly.index.to_series().shift(-3)
    return frame.dropna(subset=FEATURE_COLUMNS)


def build_ml_dataset(
    prices_daily: pd.Series | pd.DataFrame,
    prices_monthly: pd.Series | pd.DataFrame,
) -> pd.DataFrame:
    """Construit les neuf features et la cible forward trois mois.

    Le ``dropna`` final retire l'historique initial incomplet et les trois
    derniers mois, dont la cible future n'est pas encore observable.
    """
    dataset = build_feature_frame(prices_daily, prices_monthly).dropna().copy()
    dataset[TARGET_COLUMN] = dataset[TARGET_COLUMN].astype(int)
    if dataset.empty:
        raise ValueError("Historique insuffisant pour construire le dataset ML.")
    if dataset.isna().any().any():
        raise RuntimeError("Le dataset ML final ne doit contenir aucun NaN.")
    return dataset


def split_dataset(df: pd.DataFrame, train_end: str | pd.Timestamp, val_end: str | pd.Timestamp) -> tuple:
    """Effectue un split temporel strict avec purge de la cible forward."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise ValueError("Le dataset ne doit pas être vide.")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("L'index du dataset doit être un DatetimeIndex.")
    required = set(FEATURE_COLUMNS + [TARGET_COLUMN, TARGET_END_COLUMN])
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes dans le dataset : {sorted(missing)}")
    if not df.index.is_monotonic_increasing:
        raise ValueError("Le dataset doit être trié par date croissante.")
    train_end = pd.Timestamp(train_end)
    val_end = pd.Timestamp(val_end)
    if train_end >= val_end:
        raise ValueError("train_end doit précéder val_end.")

    target_end = pd.to_datetime(df[TARGET_END_COLUMN])
    train_mask = (df.index <= train_end) & (target_end <= train_end)
    val_mask = (df.index > train_end) & (df.index <= val_end) & (target_end <= val_end)
    test_mask = df.index > val_end

    def _xy(mask: pd.Series | np.ndarray) -> tuple[pd.DataFrame, pd.Series]:
        part = df.loc[mask]
        return part[FEATURE_COLUMNS].copy(), part[TARGET_COLUMN].astype(int).copy()

    X_train, y_train = _xy(train_mask)
    X_val, y_val = _xy(val_mask)
    X_test, y_test = _xy(test_mask)
    dates = {"train": X_train.index.copy(), "validation": X_val.index.copy(), "test": X_test.index.copy()}
    return X_train, y_train, X_val, y_val, X_test, y_test, dates


def train_models(X_train: pd.DataFrame, y_train: pd.Series) -> dict:
    """Entraîne les deux modèles en ajustant le scaler uniquement sur train."""
    if X_train.empty or y_train.empty or len(X_train) != len(y_train):
        raise ValueError("Les données d'entraînement sont vides ou désalignées.")
    if y_train.nunique() < 2:
        raise ValueError("L'entraînement requiert les deux classes de régime.")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    logistic = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
    logistic.fit(X_train_scaled, y_train)
    random_forest = RandomForestClassifier(n_estimators=100, max_depth=3, random_state=42)
    random_forest.fit(X_train, y_train)
    majority_class = int(y_train.value_counts().idxmax())
    return {
        "logistic": logistic,
        "random_forest": random_forest,
        "scaler": scaler,
        "majority_class": majority_class,
        "feature_names": list(X_train.columns),
    }


def _classification_metrics(y_true: pd.Series, predictions: np.ndarray, probabilities: np.ndarray) -> dict:
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, predictions, labels=[0, 1], zero_division=0
    )
    auc = float(roc_auc_score(y_true, probabilities)) if y_true.nunique() > 1 else None
    return {
        "accuracy": float(accuracy_score(y_true, predictions)),
        "risk_off": {"precision": float(precision[0]), "recall": float(recall[0]),
                     "f1": float(f1[0]), "support": int(support[0])},
        "risk_on": {"precision": float(precision[1]), "recall": float(recall[1]),
                    "f1": float(f1[1]), "support": int(support[1])},
        "confusion_matrix": confusion_matrix(y_true, predictions, labels=[0, 1]).astype(int).tolist(),
        "roc_auc": auc,
        "n_observations": int(len(y_true)),
    }


def evaluate_models(models: dict, X_val: pd.DataFrame, y_val: pd.Series,
                    X_test: pd.DataFrame, y_test: pd.Series) -> dict:
    """Évalue les modèles et la baseline majoritaire sur validation et test."""
    for label, X, y in (("validation", X_val, y_val), ("test", X_test, y_test)):
        if X.empty or y.empty or len(X) != len(y):
            raise ValueError(f"Le split {label} est vide ou désaligné.")
    result: dict = {"threshold": 0.5}
    for model_name in ("logistic", "random_forest"):
        result[model_name] = {}
        for split_name, X, y in (("validation", X_val, y_val), ("test", X_test, y_test)):
            model_input = models["scaler"].transform(X) if model_name == "logistic" else X
            probabilities = models[model_name].predict_proba(model_input)[:, 1]
            predictions = (probabilities >= 0.5).astype(int)
            result[model_name][split_name] = _classification_metrics(y, predictions, probabilities)

    majority_class = int(models["majority_class"])
    result["baseline"] = {"majority_class": majority_class}
    for split_name, y in (("validation", y_val), ("test", y_test)):
        baseline_predictions = np.full(len(y), majority_class, dtype=int)
        result["baseline"][split_name] = {
            "accuracy": float(accuracy_score(y, baseline_predictions)),
            "n_observations": int(len(y)),
        }
    importances = models["random_forest"].feature_importances_
    result["feature_importance"] = sorted(
        ({"feature": name, "importance": float(value)}
         for name, value in zip(models["feature_names"], importances, strict=True)),
        key=lambda item: item["importance"], reverse=True,
    )
    return result


def _financial_metrics(returns: pd.Series) -> dict:
    returns = returns.dropna().astype(float)
    if returns.empty:
        return {"cagr": None, "sharpe": None, "max_drawdown": None, "n_months": 0}
    growth = (1.0 + returns).cumprod()
    cagr = float(growth.iloc[-1] ** (12.0 / len(returns)) - 1.0)
    volatility = returns.std()
    sharpe = None if volatility == 0 or pd.isna(volatility) else float(returns.mean() / volatility * math.sqrt(12))
    drawdown = growth / growth.cummax() - 1.0
    return {"cagr": cagr, "sharpe": sharpe, "max_drawdown": float(drawdown.min()),
            "n_months": int(len(returns))}


def backtest_ml_strategy(models: dict, X_test: pd.DataFrame, y_test: pd.Series,
                         prices_test: pd.Series | pd.DataFrame) -> dict:
    """Backteste les signaux à M sur le rendement de marché M vers M+1."""
    if X_test.empty or len(X_test) != len(y_test):
        raise ValueError("Le test set est vide ou désaligné.")
    prices = _price_series(prices_test).resample(_MONTH_END).last().dropna()
    forward_returns = (prices.shift(-1) / prices - 1.0).reindex(X_test.index)
    result = {"threshold": 0.5, "buy_and_hold": _financial_metrics(forward_returns)}
    for model_name in ("logistic", "random_forest"):
        model_input = models["scaler"].transform(X_test) if model_name == "logistic" else X_test
        probabilities = models[model_name].predict_proba(model_input)[:, 1]
        signals = pd.Series((probabilities >= 0.5).astype(float), index=X_test.index)
        strategy_returns = signals * forward_returns
        result[model_name] = _financial_metrics(strategy_returns)
        result[model_name]["risk_on_share"] = float(signals.mean())
    return result


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def generate_regime_report(
    eval_results: dict,
    backtest_results: dict,
    output_path: str | Path,
    walk_forward: dict | None = None,
) -> None:
    """Génère le rapport Markdown de façon déterministe et idempotente.

    ``walk_forward`` (optionnel, clé ``walk_forward`` de ``run_regime_study``)
    ajoute les sections walk-forward, comparaison avec frais, verdict et régime
    courant.
    """
    dataset = eval_results.get("dataset", {})
    benchmark = dataset.get("benchmark", "CW8.PA")
    lines = [
        "# Détection ML des régimes de marché",
        "",
        "Module expérimental de contexte de marché, destiné au paper trading uniquement.",
        "",
        "## Dataset",
        "",
        f"- Période : {dataset.get('start', 'n/a')} → {dataset.get('end', 'n/a')}",
        f"- Observations : {dataset.get('n_observations', 'n/a')}",
        f"- Features : {', '.join(dataset.get('features', FEATURE_COLUMNS))}",
        f"- Splits : train={dataset.get('train_size', 'n/a')}, validation={dataset.get('validation_size', 'n/a')}, test={dataset.get('test_size', 'n/a')}",
        f"- Distribution cible : risk-off={dataset.get('risk_off', 'n/a')}, risk-on={dataset.get('risk_on', 'n/a')}",
        f"- Cible : 1 si le rendement {benchmark} de M à M+3 est strictement positif, 0 sinon.",
        "",
        "## Résultats ML",
        "",
    ]
    baseline = eval_results["baseline"]
    for model_name, title in (("logistic", "Logistic Regression"), ("random_forest", "Random Forest")):
        lines += [f"### {title}", "", "| Split | Accuracy | Precision off/on | Recall off/on | F1 off/on | ROC-AUC | Baseline |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for split in ("validation", "test"):
            metrics = eval_results[model_name][split]
            off, on = metrics["risk_off"], metrics["risk_on"]
            auc = "n/a" if metrics["roc_auc"] is None else f"{metrics['roc_auc']:.3f}"
            lines.append(f"| {split} | {metrics['accuracy']:.3f} | {off['precision']:.3f} / {on['precision']:.3f} | {off['recall']:.3f} / {on['recall']:.3f} | {off['f1']:.3f} / {on['f1']:.3f} | {auc} | {baseline[split]['accuracy']:.3f} |")
        test_accuracy = eval_results[model_name]["test"]["accuracy"]
        comparison = "bat" if test_accuracy > baseline["test"]["accuracy"] else "ne bat pas"
        val_matrix = eval_results[model_name]["validation"]["confusion_matrix"]
        test_matrix = eval_results[model_name]["test"]["confusion_matrix"]
        lines += [
            "",
            f"Matrice de confusion validation `[[TN, FP], [FN, TP]]` : `{val_matrix}`.",
            f"Matrice de confusion test `[[TN, FP], [FN, TP]]` : `{test_matrix}`.",
            f"Sur le test, ce modèle {comparison} la baseline majoritaire.",
            "",
        ]
    lines += ["## Importance des features (Random Forest)", "", "| Rang | Feature | Importance |", "| ---: | --- | ---: |"]
    for rank, item in enumerate(eval_results["feature_importance"], start=1):
        lines.append(f"| {rank} | {item['feature']} | {item['importance']:.4f} |")
    lines += ["", "## Backtest financier — split fixe, période de test (sans frais)", "", "| Stratégie | CAGR | Sharpe | Max drawdown |", "| --- | ---: | ---: | ---: |"]
    for key, title in (("logistic", "Logistic Regression"), ("random_forest", "Random Forest"), ("buy_and_hold", f"Buy & Hold {benchmark}")):
        metrics = backtest_results[key]
        sharpe = "n/a" if metrics["sharpe"] is None else f"{metrics['sharpe']:.3f}"
        lines.append(f"| {title} | {_fmt_pct(metrics['cagr'])} | {sharpe} | {_fmt_pct(metrics['max_drawdown'])} |")
    lines += [
        "", "Le seuil de classification est fixé à 0,5 et n'a pas été optimisé sur le backtest.",
        "Ce backtest à split fixe n'inclut pas de coûts de transaction ; voir la section walk-forward.", "",
    ]
    if walk_forward is not None:
        lines += _walk_forward_lines(walk_forward, benchmark)
    lines += [
        "## Limites", "",
        "- Nombre d'observations faible (~130 mois) : risque de surapprentissage.",
        "- Stationnarité non garantie des régimes de marché.",
        "- Historique court et majoritairement haussier : peu de régimes défavorables pour apprendre.",
        "- Features uniquement issues des prix du benchmark (aucune donnée macro).",
        "- Paliers d'exposition fixés a priori (guide), non optimisés.",
        "- Les résultats passés ne préjugent pas des résultats futurs.",
        "- Ce module est expérimental et ne doit pas déclencher d'ordres réels.", "",
    ]
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _walk_forward_lines(walk_forward: dict, benchmark: str) -> list[str]:
    classification = walk_forward["classification"]
    financial = walk_forward["financial"]
    current = walk_forward["current"]
    lines = [
        "## Walk-forward (fenêtre expansive, réentraînement mensuel)", "",
        f"- Période évaluée : {classification['start']} → {classification['end']} "
        f"({classification['n_observations']} mois à cible connue).",
        "- Entraînement : toutes les cibles entièrement connues à la date de décision "
        f"(purge stricte), minimum {walk_forward['min_train_size']} observations.", "",
        "| Modèle | Accuracy | ROC-AUC | Recall risk-off | Baseline |", "| --- | ---: | ---: | ---: | ---: |",
    ]
    for model_name, title in (("logistic", "Logistic Regression"), ("random_forest", "Random Forest")):
        metrics = classification[model_name]
        auc = "n/a" if metrics["roc_auc"] is None else f"{metrics['roc_auc']:.3f}"
        lines.append(f"| {title} | {metrics['accuracy']:.3f} | {auc} | {metrics['risk_off']['recall']:.3f} | "
                     f"{classification['baseline']['accuracy']:.3f} |")
    lines += [
        "", f"## Comparaison financière avec frais ({financial['transaction_cost']:.2%} par unité de turnover)", "",
        f"Mêmes mois pour toutes les stratégies : {financial['start']} → {financial['end']} "
        f"({financial['n_months']} mois). Exposition ML : >60 % → 100 %, 50–60 % → 60 %, "
        "40–50 % → 30 %, ≤40 % → cash ; décidée fin de mois M, appliquée en M+1.", "",
        "| Stratégie | CAGR | Sharpe | Max drawdown | Exposition moy. | Frais cumulés |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, metrics in financial["strategies"].items():
        sharpe = "n/a" if metrics["sharpe"] is None else f"{metrics['sharpe']:.3f}"
        label = STRATEGY_LABELS.get(key, key).replace("benchmark", benchmark)
        lines.append(f"| {label} | {_fmt_pct(metrics['cagr'])} | {sharpe} | {_fmt_pct(metrics['max_drawdown'])} | "
                     f"{metrics['avg_exposure']:.0%} | {_fmt_pct(metrics['total_cost'])} |")
    lines += ["", "## Verdict (règle fixe : Sharpe supérieur ET drawdown non dégradé)", ""]
    for overlay, verdict in financial["verdict"].items():
        label = STRATEGY_LABELS.get(overlay, overlay).replace("benchmark", benchmark)
        reference = STRATEGY_LABELS.get(verdict["reference"], verdict["reference"]).replace("benchmark", benchmark)
        state = "**utile**" if verdict["useful"] else "**non retenu**"
        lines.append(f"- {label} vs {reference} : {state} ({verdict['reason']}).")
    any_useful = any(v["useful"] for v in financial["verdict"].values())
    lines += [
        "",
        ("Conclusion : l'overlay ML améliore le profil de risque hors échantillon sur cette période ; "
         "à confirmer en paper trading avant toute utilisation."
         if any_useful else
         "Conclusion : l'overlay ML n'améliore pas le profil de risque hors échantillon. "
         "Il reste un indicateur de contexte, sans effet sur l'allocation proposée."),
        "",
        "## Régime courant (information, pas une recommandation)", "",
        f"- Date du signal : {current['signal_date']}",
        f"- Probabilité favorable (logistique) : {current['probability_logistic']:.1%}",
        f"- Probabilité favorable (random forest) : {current['probability_random_forest']:.1%}",
        f"- Exposition indicative (paliers, logistique) : {current['exposure_logistic']:.0%}", "",
    ]
    return lines


# --------------------------------------------------------------------------- #
# Walk-forward, exposition par paliers et comparaison financière avec frais
# --------------------------------------------------------------------------- #
MODEL_NAMES = ("logistic", "random_forest")
MIN_TRAIN_SIZE = 60

# Paliers fixes du guide (non optimisés) : probabilité favorable -> exposition.
EXPOSURE_BANDS = ((0.60, 1.0), (0.50, 0.60), (0.40, 0.30))

STRATEGY_LABELS = {
    "buy_and_hold": "Buy & Hold benchmark",
    "ml_benchmark": "ML (logistique) sur benchmark",
    "ml_momentum": "ML (logistique) x Momentum",
    "momentum": "Momentum défensif",
    "momentum_vt": "Momentum + VT",
}


def probability_to_exposure(probability: float) -> float:
    """Convertit une probabilité de régime favorable en exposition actions.

    ``> 60 %`` -> 100 % ; ``]50 %, 60 %]`` -> 60 % ; ``]40 %, 50 %]`` -> 30 % ;
    ``<= 40 %`` -> 0 % (cash). ``NaN`` -> ``NaN`` (pas de signal).
    """
    if probability is None or pd.isna(probability):
        return float("nan")
    probability = float(probability)
    if not 0.0 <= probability <= 1.0:
        raise ValueError("La probabilité doit être comprise entre 0 et 1.")
    for threshold, exposure in EXPOSURE_BANDS:
        if probability > threshold:
            return exposure
    return 0.0


def _fit_predict(train: pd.DataFrame, rows: pd.DataFrame) -> dict[str, np.ndarray]:
    models = train_models(train[FEATURE_COLUMNS], train[TARGET_COLUMN].astype(int))
    features = rows[FEATURE_COLUMNS]
    return {
        "logistic": models["logistic"].predict_proba(models["scaler"].transform(features))[:, 1],
        "random_forest": models["random_forest"].predict_proba(features)[:, 1],
        "baseline": np.full(len(rows), float(models["majority_class"])),
    }


def walk_forward_probabilities(frame: pd.DataFrame, min_train_size: int = MIN_TRAIN_SIZE) -> pd.DataFrame:
    """Probabilités de régime favorable en walk-forward (fenêtre expansive).

    Pour chaque mois ``t`` de ``frame`` (sortie de ``build_feature_frame``), les
    modèles sont réentraînés uniquement sur les lignes dont la cible est
    **entièrement connue en t** (``target_end <= t``) : purge stricte, aucune
    information postérieure à ``t``. Les mois sans assez d'historique
    (``< min_train_size`` cibles connues ou une seule classe) sont ignorés.

    Returns
    -------
    pd.DataFrame
        Index = mois de décision ; colonnes ``logistic``, ``random_forest``,
        ``baseline`` (classe majoritaire du train), ``target`` (NaN si inconnue),
        ``train_size``.
    """
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("Le frame de features ne doit pas être vide.")
    if min_train_size < 2:
        raise ValueError("min_train_size doit être >= 2.")
    labelled = frame.dropna(subset=[TARGET_COLUMN, TARGET_END_COLUMN])
    target_end = pd.to_datetime(labelled[TARGET_END_COLUMN])
    records = []
    for date in frame.index:
        train = labelled.loc[target_end <= date]
        if len(train) < min_train_size or train[TARGET_COLUMN].nunique() < 2:
            continue
        predictions = _fit_predict(train, frame.loc[[date]])
        records.append({
            "date": date,
            **{name: float(values[0]) for name, values in predictions.items()},
            "target": frame.at[date, TARGET_COLUMN],
            "train_size": int(len(train)),
        })
    if not records:
        raise ValueError("Historique insuffisant pour le walk-forward.")
    return pd.DataFrame.from_records(records).set_index("date")


def evaluate_walk_forward(probabilities: pd.DataFrame) -> dict:
    """Métriques de classification sur les mois walk-forward à cible connue."""
    known = probabilities.dropna(subset=["target"])
    if known.empty:
        raise ValueError("Aucune cible connue dans le walk-forward.")
    y_true = known["target"].astype(int)
    result: dict = {
        "start": known.index.min().date().isoformat(),
        "end": known.index.max().date().isoformat(),
        "n_observations": int(len(known)),
    }
    for model_name in MODEL_NAMES:
        probas = known[model_name].to_numpy()
        result[model_name] = _classification_metrics(y_true, (probas >= 0.5).astype(int), probas)
    result["baseline"] = {"accuracy": float(accuracy_score(y_true, known["baseline"].astype(int)))}
    return result


def compare_regime_strategies(
    monthly_prices: pd.DataFrame,
    probabilities: pd.DataFrame,
    benchmark_ticker: str,
    config,
) -> dict:
    """Compare, avec frais, les overlays ML aux stratégies du rapport mensuel.

    L'exposition décidée avec la probabilité de fin de mois ``t`` est appliquée
    au mois ``t+1`` (décalage d'un mois, comme le Momentum). Toutes les
    stratégies sont évaluées sur les **mêmes mois** : ceux où l'overlay ML a une
    exposition exécutée. ``config`` est un ``MonthlyPipelineConfig``.
    """
    from src.backtest import CASH_COLUMN, backtest_monthly_allocation
    from src.portfolio import apply_volatility_target, build_vol_targeted_weights
    from src.signals import build_momentum_weights

    if benchmark_ticker not in monthly_prices.columns:
        raise ValueError(f"Benchmark {benchmark_ticker} absent des prix mensuels.")
    bt_cfg = config.backtest
    m = config.momentum
    exposure = probabilities["logistic"].map(probability_to_exposure)
    executed_exposure = exposure.reindex(monthly_prices.index).shift(1)
    window = executed_exposure.dropna().index
    if window.empty:
        raise ValueError("Aucun mois commun entre le walk-forward et les prix mensuels.")

    def _run(weights: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
        return backtest_monthly_allocation(
            prices, weights, initial_capital=bt_cfg.initial_capital,
            transaction_cost=bt_cfg.transaction_cost, cash_return=bt_cfg.cash_return,
        )

    bench_prices = monthly_prices[[benchmark_ticker]]
    first_valid = bench_prices[benchmark_ticker].first_valid_index()
    # Pas d'exposition tant que le rendement du benchmark n'est pas calculable.
    not_investable = pd.Series(bench_prices.index <= first_valid, index=bench_prices.index)
    bench_exposure = pd.Series(1.0, index=bench_prices.index).where(~not_investable, 0.0)
    bench_weights = pd.DataFrame({benchmark_ticker: bench_exposure, CASH_COLUMN: 1.0 - bench_exposure})
    # Avant la fenêtre walk-forward, l'overlay est neutre (exposition 100 %) : les
    # stratégies comparées sont déjà « en place » au début de la fenêtre, sans
    # coût d'entrée artificiel pour l'overlay.
    overlay_exposure = executed_exposure.fillna(1.0)
    ml_exposure = overlay_exposure.where(~not_investable, 0.0)
    ml_weights = pd.DataFrame({benchmark_ticker: ml_exposure, CASH_COLUMN: 1.0 - ml_exposure})

    momentum = build_momentum_weights(
        monthly_prices, lookback_months=m.lookback_months, skip_months=m.skip_months,
        ma_window=m.moving_average_window, top_n=m.top_n,
        require_positive_momentum=m.require_positive_momentum, already_monthly=True,
    )
    base = momentum["executed_weights"]
    strategies = {
        "buy_and_hold": _run(bench_weights, bench_prices),
        "ml_benchmark": _run(ml_weights, bench_prices),
        "ml_momentum": _run(apply_volatility_target(base, overlay_exposure), monthly_prices),
        "momentum": _run(base, monthly_prices),
    }
    vt = config.volatility_targeting
    if vt.enabled:
        vt_bundle = build_vol_targeted_weights(
            monthly_prices, base, target_volatility=vt.target_volatility,
            vol_window=vt.volatility_window, min_exposure=vt.min_exposure,
            max_exposure=vt.max_exposure,
        )
        strategies["momentum_vt"] = _run(vt_bundle["final_weights"], monthly_prices)

    result: dict = {
        "start": window.min().date().isoformat(),
        "end": window.max().date().isoformat(),
        "n_months": int(len(window)),
        "transaction_cost": float(bt_cfg.transaction_cost),
        "strategies": {},
        "returns": {},
    }
    for name, bt in strategies.items():
        returns = bt["Net Return"].loc[window]
        metrics = _financial_metrics(returns)
        metrics["avg_exposure"] = float(bt["Invested Exposure"].loc[window].mean())
        metrics["total_cost"] = float(bt["Transaction Cost"].loc[window].sum())
        result["strategies"][name] = metrics
        result["returns"][name] = returns
    result["verdict"] = _overlay_verdict(result["strategies"])
    return result


def _overlay_verdict(strategies: dict) -> dict:
    """Règle fixe : l'overlay ML est « utile » seulement s'il améliore le Sharpe
    de la stratégie qu'il modifie **et** ne dégrade pas son max drawdown."""
    verdicts = {}
    for overlay, reference in (("ml_benchmark", "buy_and_hold"), ("ml_momentum", "momentum")):
        ov, ref = strategies.get(overlay), strategies.get(reference)
        if not ov or not ref or ov["sharpe"] is None or ref["sharpe"] is None:
            verdicts[overlay] = {"reference": reference, "useful": False, "reason": "métriques indisponibles"}
            continue
        better_sharpe = ov["sharpe"] > ref["sharpe"]
        no_worse_dd = ov["max_drawdown"] >= ref["max_drawdown"]
        verdicts[overlay] = {
            "reference": reference,
            "useful": bool(better_sharpe and no_worse_dd),
            "reason": (
                f"Sharpe {ov['sharpe']:.2f} vs {ref['sharpe']:.2f}, "
                f"max DD {ov['max_drawdown']:.1%} vs {ref['max_drawdown']:.1%}"
            ),
        }
    return verdicts


def current_regime(probabilities: pd.DataFrame) -> dict:
    """Dernière probabilité walk-forward disponible (mois le plus récent)."""
    last_date = probabilities.index.max()
    row = probabilities.loc[last_date]
    return {
        "signal_date": last_date.date().isoformat(),
        "probability_logistic": float(row["logistic"]),
        "probability_random_forest": float(row["random_forest"]),
        "exposure_logistic": probability_to_exposure(row["logistic"]),
    }


def run_regime_study(
    prices_daily: pd.DataFrame,
    monthly_prices: pd.DataFrame,
    config,
    train_end: str = "2021-12-31",
    val_end: str = "2023-12-31",
    min_train_size: int = MIN_TRAIN_SIZE,
) -> dict:
    """Étude complète : split fixe + walk-forward + comparaison avec frais.

    ``prices_daily`` : prix quotidiens (le benchmark de ``config`` sert de
    marché). ``monthly_prices`` : prix mensuels complets de l'univers retenu par
    le pipeline mensuel (``MonthlyPipelineResult.monthly_prices``).
    ``config`` est un ``MonthlyPipelineConfig``.
    """
    benchmark = config.benchmark_ticker
    daily = prices_daily[benchmark].dropna() if isinstance(prices_daily, pd.DataFrame) else prices_daily.dropna()
    monthly_bench = daily.resample(_MONTH_END).last()
    frame = build_feature_frame(daily, monthly_bench)
    dataset = frame.dropna().copy()
    dataset[TARGET_COLUMN] = dataset[TARGET_COLUMN].astype(int)

    X_train, y_train, X_val, y_val, X_test, y_test, _ = split_dataset(dataset, train_end, val_end)
    models = train_models(X_train, y_train)
    evaluation = evaluate_models(models, X_val, y_val, X_test, y_test)
    evaluation["dataset"] = {
        "start": dataset.index.min().date().isoformat(),
        "end": dataset.index.max().date().isoformat(),
        "n_observations": len(dataset),
        "features": FEATURE_COLUMNS,
        "train_size": len(X_train),
        "validation_size": len(X_val),
        "test_size": len(X_test),
        "risk_off": int((dataset[TARGET_COLUMN] == 0).sum()),
        "risk_on": int((dataset[TARGET_COLUMN] == 1).sum()),
        "benchmark": benchmark,
    }
    backtest = backtest_ml_strategy(models, X_test, y_test, monthly_bench)

    probabilities = walk_forward_probabilities(frame, min_train_size=min_train_size)
    walk_forward = {
        "classification": evaluate_walk_forward(probabilities),
        "financial": compare_regime_strategies(monthly_prices, probabilities, benchmark, config),
        "current": current_regime(probabilities),
        "min_train_size": min_train_size,
    }
    return {
        "evaluation": evaluation,
        "backtest": backtest,
        "probabilities": probabilities,
        "walk_forward": walk_forward,
    }

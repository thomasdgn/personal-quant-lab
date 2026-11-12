"""Alertes du rapport mensuel (INFO / WARNING / CRITICAL) et validation structurelle des poids.

Extrait de ``src/monthly_pipeline.py`` (v6) ; les noms restent importables depuis ce dernier.
"""

from __future__ import annotations

import pandas as pd

from src.metrics import compute_drawdown
from src.pipeline_config import MonthlyPipelineConfig
from src.pipeline_models import Alert, StrategyReport

# Seuils d'alerte de risque (documentés, non optimisés).
_REDUCED_EXPOSURE_THRESHOLD = 0.50
_HIGH_VOLATILITY_THRESHOLD = 0.20
_HIGH_DRAWDOWN_THRESHOLD = -0.15
_DIVERGENCE_THRESHOLD = 0.30
_HIGH_TURNOVER_THRESHOLD = 0.75
_HIGH_COST_THRESHOLD = 0.05

# Codes d'alerte qui font échouer le pipeline (anomalies structurelles).
_FATAL_CODES = {
    "INVALID_WEIGHTS",
    "WEIGHTS_SUM",
    "NEGATIVE_WEIGHT",
    "EXPOSURE_OVER_100",
    "FUTURE_DATE",
    "NAN_IN_FINAL",
}


def _make_alert(level: str, code: str, title: str, message: str, generated_at: str, **context) -> Alert:
    return Alert(level=level, code=code, title=title, message=message, timestamp=generated_at, context=context)


def _build_alerts(
    *,
    config: MonthlyPipelineConfig,
    generated_at: str,
    data_age_days: int,
    excluded: dict[str, str],
    n_months: int,
    partial_month: str | None,
    data_refreshed: bool,
    universe_issues: dict | None = None,
    anomalies: list[dict] | None = None,
    momentum_report: StrategyReport,
    vt_report: StrategyReport,
    momentum_bt: pd.DataFrame,
    vt_bt: pd.DataFrame | None,
    vt_enabled: bool = True,
) -> list[Alert]:
    """Construit les alertes informatives (aucune recommandation d'ordre)."""
    alerts: list[Alert] = []
    rc = config.reporting

    # --- Données ---
    if data_age_days >= rc.stale_data_days_critical:
        alerts.append(_make_alert("CRITICAL", "STALE_DATA",
            "Données très anciennes",
            f"Dernière observation il y a {data_age_days} jours. Validation humaine requise.",
            generated_at, data_age_days=data_age_days))
    elif data_age_days >= rc.stale_data_days_warning:
        alerts.append(_make_alert("WARNING", "STALE_DATA",
            "Données anciennes",
            f"Dernière observation il y a {data_age_days} jours.",
            generated_at, data_age_days=data_age_days))

    if not data_refreshed:
        alerts.append(_make_alert("INFO", "DATA_NOT_REFRESHED",
            "Données locales", "Rapport basé sur les données locales (pas de téléchargement).",
            generated_at))

    if anomalies:
        details = "; ".join(f"{a['ticker']} {a['type']} {a['date']} ({a['detail']})" for a in anomalies[:3])
        more = f" et {len(anomalies) - 3} autre(s)" if len(anomalies) > 3 else ""
        alerts.append(_make_alert("WARNING", "DATA_ANOMALY",
            "Anomalie de données",
            f"{len(anomalies)} anomalie(s) récente(s) dans les prix : {details}{more}. Vérifier la source.",
            generated_at, anomalies=anomalies))

    universe_issues = universe_issues or {}
    if universe_issues.get("missing"):
        missing = universe_issues["missing"]
        alerts.append(_make_alert("WARNING", "UNIVERSE_MISMATCH",
            "Univers incomplet",
            f"Tickers de assets.yaml absents des données locales : {', '.join(missing)}. "
            "Relancer `python main.py refresh-data`.",
            generated_at, missing=missing))
    if universe_issues.get("extra"):
        extra = universe_issues["extra"]
        alerts.append(_make_alert("INFO", "UNIVERSE_EXTRA",
            "Tickers hors univers",
            f"Tickers présents dans les données mais absents de assets.yaml (ignorés) : {', '.join(extra)}.",
            generated_at, extra=extra))

    if excluded:
        alerts.append(_make_alert("WARNING", "ASSET_EXCLUDED",
            "Actifs exclus", f"Actifs écartés faute d'historique : {', '.join(excluded)}.",
            generated_at, excluded=excluded))

    min_needed = config.momentum.lookback_months + config.momentum.moving_average_window
    if n_months < min_needed + 6:
        alerts.append(_make_alert("WARNING", "INSUFFICIENT_HISTORY",
            "Historique limité",
            f"{n_months} mois disponibles (recommandé > {min_needed + 6}).",
            generated_at, n_months=n_months))

    if partial_month is not None:
        alerts.append(_make_alert("INFO", "PARTIAL_MONTH",
            "Mois en cours incomplet",
            f"Le mois {partial_month} est incomplet et exclu du signal officiel.",
            generated_at, partial_month=partial_month))

    # --- Risque (alertes propres au Volatility Targeting) ---
    # Ignorées lorsque le VT est désactivé : aucune allocation VT n'est produite.
    if vt_enabled:
        if vt_report.cash_weight > 0.999:
            alerts.append(_make_alert("WARNING", "FULL_CASH",
                "Passage en cash total",
                "L'allocation théorique VT est entièrement en cash. Validation humaine requise.",
                generated_at))
        elif vt_report.invested_exposure < _REDUCED_EXPOSURE_THRESHOLD:
            alerts.append(_make_alert("WARNING", "REDUCED_EXPOSURE",
                "Exposition cible réduite",
                f"Exposition investie théorique de {vt_report.invested_exposure:.0%}.",
                generated_at, invested_exposure=vt_report.invested_exposure))

        if vt_report.realized_volatility is not None and vt_report.realized_volatility > _HIGH_VOLATILITY_THRESHOLD:
            alerts.append(_make_alert("WARNING", "HIGH_VOLATILITY",
                "Volatilité élevée",
                f"Volatilité réalisée de {vt_report.realized_volatility:.1%} (seuil {_HIGH_VOLATILITY_THRESHOLD:.0%}).",
                generated_at, realized_volatility=vt_report.realized_volatility))

        vt_dd = float(compute_drawdown(vt_bt["Equity Curve"]).iloc[-1])
        if vt_dd < _HIGH_DRAWDOWN_THRESHOLD:
            alerts.append(_make_alert("WARNING", "HIGH_DRAWDOWN",
                "Drawdown important",
                f"Drawdown courant de {vt_dd:.1%} (seuil {_HIGH_DRAWDOWN_THRESHOLD:.0%}).",
                generated_at, drawdown=vt_dd))

        divergence = abs(momentum_report.invested_exposure - vt_report.invested_exposure)
        if divergence > _DIVERGENCE_THRESHOLD:
            alerts.append(_make_alert("INFO", "MOMENTUM_VT_DIVERGENCE",
                "Écart Momentum / VT",
                f"Écart d'exposition de {divergence:.0%} entre Momentum et VT.",
                generated_at, divergence=divergence))

        last_turnover = float(vt_bt["Turnover"].iloc[-1])
        if last_turnover > _HIGH_TURNOVER_THRESHOLD:
            alerts.append(_make_alert("INFO", "HIGH_TURNOVER",
                "Turnover élevé",
                f"Turnover du dernier mois de {last_turnover:.0%}.",
                generated_at, turnover=last_turnover))

        if vt_report.cumulative_cost is not None and vt_report.cumulative_cost > _HIGH_COST_THRESHOLD:
            alerts.append(_make_alert("INFO", "HIGH_COST",
                "Coûts cumulés élevés",
                f"Coûts de transaction cumulés de {vt_report.cumulative_cost:.1%}.",
                generated_at, cumulative_cost=vt_report.cumulative_cost))

        # --- Pipeline (métrique VT indisponible) ---
        metrics_missing = any(
            getattr(vt_report, attr) is None for attr in ("cagr", "annualized_volatility", "sharpe", "max_drawdown")
        )
        if metrics_missing:
            alerts.append(_make_alert("WARNING", "METRIC_UNAVAILABLE",
                "Métrique indisponible", "Au moins une métrique n'a pas pu être calculée.",
                generated_at))

    return alerts


# --------------------------------------------------------------------------- #
# Validation structurelle (peut faire échouer le pipeline)
# --------------------------------------------------------------------------- #
def _validate_weights(weights: pd.DataFrame, label: str, generated_at: str) -> list[Alert]:
    values = weights.to_numpy()
    fatal: list[Alert] = []
    if (values < -1e-9).any():
        fatal.append(_make_alert("CRITICAL", "NEGATIVE_WEIGHT", "Poids négatif",
            f"Poids négatif détecté dans {label}.", generated_at))
    if (values > 1.0 + 1e-9).any():
        fatal.append(_make_alert("CRITICAL", "INVALID_WEIGHTS", "Poids > 1",
            f"Poids supérieur à 1 dans {label}.", generated_at))
    if not (abs(weights.sum(axis=1) - 1.0) < 1e-6).all():
        fatal.append(_make_alert("CRITICAL", "WEIGHTS_SUM", "Somme des poids != 1",
            f"La somme des poids de {label} n'est pas égale à 1.", generated_at))
    if pd.isna(values).any():
        fatal.append(_make_alert("CRITICAL", "NAN_IN_FINAL", "NaN dans les poids",
            f"Valeur manquante dans les poids de {label}.", generated_at))
    return fatal

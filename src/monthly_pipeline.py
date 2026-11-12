"""Orchestration du rapport mensuel (Projet 4).

Transforme les briques validées (features, signaux, volatility targeting,
backtest, métriques) en un résultat mensuel **structuré et typé**, prêt à être
formaté en Markdown ou sérialisé en JSON.

Responsabilités de ce module (configuration : ``pipeline_config`` ; modèle : ``pipeline_models`` ; alertes : ``pipeline_alerts``) :

- charger et valider la configuration (`load_config`) ;
- orchestrer le calcul mensuel (`run_monthly_pipeline`) sans données futures ;
- construire des alertes locales (INFO / WARNING / CRITICAL) ;
- valider la cohérence financière (poids, exposition, dates) avant publication.

Ce module ne formate rien et n'écrit aucun fichier : voir `src/reporting.py`.
Aucun ordre n'est exécuté ; la décision reste humaine.
"""

from __future__ import annotations


import pandas as pd

from src.backtest import CASH_COLUMN, backtest_monthly_allocation, buy_and_hold
from src.data_quality import RECENT_WINDOW_DAYS, quality_checks
from src.features import to_monthly_prices
from src.metrics import compute_drawdown, performance_summary
from src.policy import InvestmentPolicy
from src.pipeline_alerts import (  # noqa: F401 - noms historiques ré-exportés
    _DIVERGENCE_THRESHOLD,
    _FATAL_CODES,
    _HIGH_COST_THRESHOLD,
    _HIGH_DRAWDOWN_THRESHOLD,
    _HIGH_TURNOVER_THRESHOLD,
    _HIGH_VOLATILITY_THRESHOLD,
    _REDUCED_EXPOSURE_THRESHOLD,
    _build_alerts,
    _make_alert,
    _validate_weights,
)
from src.pipeline_config import (  # noqa: F401 - noms historiques ré-exportés
    BacktestConfig,
    MomentumConfig,
    MonthlyPipelineConfig,
    PipelineValidationError,
    ReportingConfig,
    UniverseConfig,
    VolTargetConfig,
    _config_section,
    load_config,
)
from src.pipeline_models import (  # noqa: F401 - noms historiques ré-exportés
    Alert,
    MonthlyPipelineResult,
    MonthlyReport,
    StrategyReport,
    _clean_float,
    _weights_to_dict,
)
from src.portfolio import apply_volatility_target, build_vol_targeted_weights
from src.signals import build_momentum_weights
from src.strategies import REGISTRY as STRATEGY_REGISTRY
from src.strategies import StrategyContext, available_strategies, build_strategy
from src.strategies import label as strategy_label

SCHEMA_VERSION = "1.4"
PERIODS_PER_YEAR = 12  # données mensuelles

def _apply_asset_roles(
    columns: list[str],
    asset_roles: dict[str, str] | None,
    config: MonthlyPipelineConfig,
) -> dict:
    """Répartit les colonnes de prix selon les rôles configurés.

    Sans ``asset_roles`` (compatibilité), toutes les colonnes sont candidates.
    Le benchmark reste toujours candidat, même s'il n'est pas configuré.
    """
    if asset_roles is None:
        return {"strategy": list(columns), "cash_proxies": [], "missing": [], "extra": [],
                "excluded_by_role": [], "roles": {}}
    roles = dict(asset_roles)
    roles.setdefault(config.benchmark_ticker, "candidate")
    allowed = {"candidate"} | ({"defensive"} if config.universe.defensive_as_candidates else set())
    strategy = [c for c in columns if roles.get(c) in allowed]
    return {
        "strategy": strategy,
        "cash_proxies": [c for c in columns if roles.get(c) == "cash_proxy"],
        "missing": [t for t in roles if t not in columns],
        "extra": [c for c in columns if c not in roles],
        "excluded_by_role": [c for c in columns if roles.get(c) == "defensive" and "defensive" not in allowed],
        "roles": {c: roles[c] for c in columns if c in roles},
    }


def _select_universe(
    prices: pd.DataFrame, min_history_months: int, benchmark_ticker: str
) -> tuple[list[str], dict[str, str]]:
    """Retient les actifs à historique suffisant ; documente les exclusions."""
    monthly = to_monthly_prices(prices)
    kept, excluded = [], {}
    for col in prices.columns:
        n_months = int(monthly[col].notna().sum())
        if n_months >= min_history_months:
            kept.append(col)
        else:
            excluded[col] = f"historique insuffisant ({n_months} mois < {min_history_months})"
    if benchmark_ticker not in kept:
        raise PipelineValidationError(
            f"Le benchmark '{benchmark_ticker}' n'a pas assez d'historique pour le rapport."
        )
    return kept, excluded


def _strategy_report_from_backtest(
    name: str,
    description: str,
    backtest_df: pd.DataFrame,
    target_weights_row: pd.Series,
    executed_weights_row: pd.Series,
    signal_date: pd.Timestamp,
    *,
    momentum_row: pd.Series | None = None,
    trend_row: pd.Series | None = None,
    realized_volatility: object = None,
    target_volatility: float | None = None,
    cash_col: str = CASH_COLUMN,
) -> StrategyReport:
    """Construit un `StrategyReport` à partir d'un backtest et des poids courants."""
    summary = performance_summary(
        backtest_df["Net Return"].dropna(),
        backtest_df["Equity Curve"],
        periods_per_year=PERIODS_PER_YEAR,
    )
    # L'exposition/cash affichés reflètent l'allocation CIBLE (actionnable), pas
    # seulement celle actuellement détenue : c'est la décision proposée.
    asset_cols = [c for c in target_weights_row.index if c != cash_col]
    selected = [c for c in asset_cols if target_weights_row[c] > 1e-9]
    cash_weight = float(target_weights_row.get(cash_col, 0.0))

    return StrategyReport(
        name=name,
        description=description,
        selected_assets=selected,
        target_weights=_weights_to_dict(target_weights_row),
        executed_weights=_weights_to_dict(executed_weights_row),
        cash_weight=cash_weight,
        invested_exposure=float(1.0 - cash_weight),
        momentum=None if momentum_row is None else {k: _clean_float(v) for k, v in momentum_row.items()},
        trend_filter=None if trend_row is None else {k: bool(v) for k, v in trend_row.items()},
        realized_volatility=_clean_float(realized_volatility),
        target_volatility=target_volatility,
        cagr=_clean_float(summary["CAGR"]),
        annualized_volatility=_clean_float(summary["Volatility"]),
        sharpe=_clean_float(summary["Sharpe"]),
        max_drawdown=_clean_float(summary["Max Drawdown"]),
        recent_return=_clean_float(backtest_df["Net Return"].iloc[-1]),
        theoretical_capital=_clean_float(backtest_df["Equity Curve"].iloc[-1]),
        turnover=_clean_float(backtest_df["Turnover"].mean()),
        cumulative_cost=_clean_float(backtest_df["Transaction Cost"].sum()),
        signal_date=signal_date.date().isoformat(),
    )


def _benchmark_report(
    ticker: str, bh: pd.DataFrame, signal_date: pd.Timestamp, cash_col: str = CASH_COLUMN
) -> StrategyReport:
    summary = performance_summary(
        bh["Returns"].dropna(), bh["Equity Curve"], periods_per_year=PERIODS_PER_YEAR
    )
    weights = {ticker: 1.0, cash_col: 0.0}
    return StrategyReport(
        name=f"Buy & Hold {ticker}",
        description="Achat et conservation du benchmark, toujours investi à 100 %.",
        selected_assets=[ticker],
        target_weights=weights,
        executed_weights=weights,
        cash_weight=0.0,
        invested_exposure=1.0,
        momentum=None,
        trend_filter=None,
        realized_volatility=None,
        target_volatility=None,
        cagr=_clean_float(summary["CAGR"]),
        annualized_volatility=_clean_float(summary["Volatility"]),
        sharpe=_clean_float(summary["Sharpe"]),
        max_drawdown=_clean_float(summary["Max Drawdown"]),
        recent_return=_clean_float(bh["Returns"].iloc[-1]),
        theoretical_capital=_clean_float(bh["Equity Curve"].iloc[-1]),
        turnover=0.0,
        cumulative_cost=0.0,
        signal_date=signal_date.date().isoformat(),
    )


def _disabled_vt_report(signal_date: pd.Timestamp) -> StrategyReport:
    """Section VT explicitement désactivée (aucune logique VT exécutée)."""
    return StrategyReport(
        name="Volatility Targeting désactivé",
        description="Volatility Targeting is disabled in configuration.",
        selected_assets=[],
        target_weights=None,
        executed_weights=None,
        cash_weight=None,
        invested_exposure=None,
        momentum=None,
        trend_filter=None,
        realized_volatility=None,
        target_volatility=None,
        cagr=None,
        annualized_volatility=None,
        sharpe=None,
        max_drawdown=None,
        recent_return=None,
        theoretical_capital=None,
        turnover=None,
        cumulative_cost=None,
        signal_date=signal_date.date().isoformat(),
        enabled=False,
        status="DISABLED",
    )


# --------------------------------------------------------------------------- #
# Alertes
# --------------------------------------------------------------------------- #
def crash_rule_block(policy: InvestmentPolicy, current_drawdown: float | None) -> dict | None:
    """Règle de krach de la politique et état courant (déclenchée si la baisse dépasse le seuil)."""
    if not policy.regle_krach:
        return None
    triggered = current_drawdown is not None and current_drawdown <= -policy.seuil_krach
    return {"text": policy.regle_krach, "threshold": policy.seuil_krach, "current_drawdown": current_drawdown,
            "triggered": bool(triggered)}


def _registry_and_policy(
    monthly: pd.DataFrame, kept: list[str], roles: dict[str, str], config: MonthlyPipelineConfig,
    policy: InvestmentPolicy | None, *, cash_return: float | pd.Series, signal_date: pd.Timestamp, generated_at: str,
    momentum_bundle: dict, momentum_bt: pd.DataFrame, vt_target_frame: pd.DataFrame | None,
    vt_bt: pd.DataFrame | None,
) -> tuple[dict[str, pd.DataFrame], dict[str, dict], str, dict]:
    """Toutes les stratégies du registre au mois du signal et bloc « politique » (schéma 1.3).

    Réutilise les cibles et backtests Momentum / VT déjà calculés par le pipeline
    (identiques au registre, prouvé par les tests).
    """
    policy = policy if policy is not None else InvestmentPolicy()
    defensive = [c for c in kept if roles.get(c) == "defensive"]
    bond = defensive[0] if defensive else ("OBLI.PA" if "OBLI.PA" in kept else None)
    # Cibles déjà calculées par le pipeline (identiques au registre, prouvé par les tests) : réutilisées.
    cache: dict[str, pd.DataFrame] = {"momentum": momentum_bundle["target_weights"]}
    reused_backtests = {"momentum": momentum_bt}
    if vt_target_frame is not None:
        cache["momentum_vt"] = vt_target_frame
        reused_backtests["momentum_vt"] = vt_bt
    ctx = StrategyContext(
        config=config, bond=bond, core_weight=policy.part_coeur, satellite=policy.satellite,
        equities=tuple(c for c in kept if c != bond and roles.get(c, "candidate") == "candidate"),
        extras={"cache": cache}, fixed_allocation=tuple(policy.allocation_fixe.items()),
    )
    strategy_backtests: dict[str, pd.DataFrame] = {}
    strategies: dict[str, dict] = {}
    for name in available_strategies(monthly, ctx):
        bundle = build_strategy(name, monthly, ctx)
        bt = reused_backtests.get(name)
        if bt is None:
            bt = backtest_monthly_allocation(
                monthly, bundle["executed_weights"], initial_capital=config.backtest.initial_capital,
                transaction_cost=config.backtest.transaction_cost, cash_return=cash_return,
            )
        strategy_backtests[name] = bt
        summary = performance_summary(bt["Net Return"].dropna(), bt["Equity Curve"], periods_per_year=PERIODS_PER_YEAR)
        target_row = bundle["target_weights"].loc[signal_date]
        strategies[name] = {
            "label": strategy_label(name, ctx),
            "description": STRATEGY_REGISTRY[name].description,
            "target_weights": _weights_to_dict(target_row),
            "executed_weights": _weights_to_dict(bundle["executed_weights"].loc[signal_date]),
            "invested_exposure": _clean_float(1.0 - float(target_row.get(CASH_COLUMN, 0.0))),
            "cash_weight": _clean_float(float(target_row.get(CASH_COLUMN, 0.0))),
            "selected_assets": [c for c in target_row.index if c != CASH_COLUMN and target_row[c] > 1e-9],
            "cagr": _clean_float(summary["CAGR"]),
            "annualized_volatility": _clean_float(summary["Volatility"]),
            "sharpe": _clean_float(summary["Sharpe"]),
            "max_drawdown": _clean_float(summary["Max Drawdown"]),
            "current_drawdown": _clean_float(compute_drawdown(bt["Equity Curve"]).iloc[-1]),
            "turnover": _clean_float(bt["Turnover"].mean()),
            "cumulative_cost": _clean_float(bt["Transaction Cost"].sum()),
        }
    followed = policy.strategie_suivie
    if followed not in strategies:
        raise PipelineValidationError(
            f"La stratégie suivie par la politique ({followed}) n'est pas calculable avec cet univers "
            f"(disponibles : {', '.join(strategies)})."
        )
    fatal = _validate_weights(pd.DataFrame([strategies[followed]["target_weights"]]), followed, generated_at)
    if fatal:
        raise PipelineValidationError(f"Validation échouée ({', '.join(a.code for a in fatal)}).")
    followed_dd = strategies[followed]["max_drawdown"]
    policy_block = {
        "followed": followed,
        "label": strategies[followed]["label"],
        "target_weights": strategies[followed]["target_weights"],
        "invested_exposure": strategies[followed]["invested_exposure"],
        "max_drawdown_limit": policy.drawdown_max_accepte,
        "historical_max_drawdown": followed_dd,
        "drawdown_within_limit": None if followed_dd is None else abs(followed_dd) <= policy.drawdown_max_accepte,
        "core_weight": policy.part_coeur if followed == "core_satellite" else None,
        "satellite": policy.satellite if followed == "core_satellite" else None,
        "rebalancing": policy.reequilibrage,
        "band_tolerance_pct": policy.bande_tolerance_pct,
        "plan": policy.plan_suivi,  # 1.4
        "crash_rule": crash_rule_block(policy, strategies[followed]["current_drawdown"]),  # 1.4
    }
    return strategy_backtests, strategies, followed, policy_block


# --------------------------------------------------------------------------- #
# Pipeline principal
# --------------------------------------------------------------------------- #
def run_monthly_pipeline(
    prices: pd.DataFrame,
    config: MonthlyPipelineConfig,
    report_date: str | pd.Timestamp | None = None,
    *,
    data_refreshed: bool = False,
    generation_time: pd.Timestamp | None = None,
    previous_snapshot: dict | None = None,
    asset_roles: dict[str, str] | None = None,
    policy=None,
) -> MonthlyPipelineResult:
    """Exécute le pipeline mensuel sans utiliser aucune donnée future.

    Parameters
    ----------
    prices:
        Prix quotidiens ou mensuels (colonnes = tickers).
    config:
        Configuration validée.
    report_date:
        Date d'arrêté. ``None`` => dernière observation disponible. Aucune donnée
        postérieure n'est utilisée (anti-look-ahead).
    data_refreshed:
        Vrai si les données ont été téléchargées lors de cette exécution.
    generation_time:
        Horodatage de génération (injectable pour des tests déterministes).
    previous_snapshot:
        Snapshot JSON du mois précédent, pour la section de comparaison.
    asset_roles:
        ``{ticker: role}`` issu de ``config/assets.yaml`` (actifs actifs). Si
        fourni, seuls les tickers configurés sont utilisés, les ``cash_proxy``
        ne sont jamais classés et rémunèrent la poche cash, et les écarts entre
        configuration et données locales sont signalés. ``None`` : toutes les
        colonnes de prix sont candidates (comportement historique).

    Returns
    -------
    MonthlyPipelineResult
        Résultat structuré + artefacts bruts.

    Raises
    ------
    PipelineValidationError
        En cas d'anomalie structurelle (poids/date invalides).
    """
    config.validate()
    generation_time = pd.Timestamp(generation_time) if generation_time is not None else pd.Timestamp.now()
    if generation_time.tzinfo is not None:
        generation_time = generation_time.tz_convert("UTC").tz_localize(None)
    generated_at = generation_time.isoformat(timespec="seconds")

    # Les trois horloges restent distinctes : generation_time (exécution),
    # report_date (replay optionnel) et last_observation (données disponibles).
    report_date = pd.Timestamp(report_date) if report_date is not None else None

    if prices is None or prices.empty:
        raise PipelineValidationError("Aucune donnée de prix fournie.")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise PipelineValidationError("L'index des prix doit être un DatetimeIndex.")

    prices = prices.sort_index()
    available_last_observation = prices.dropna(how="all").index.max()
    # La coupure de calcul est distincte de la date de replay optionnelle.
    analysis_cutoff = report_date if report_date is not None else available_last_observation

    # Référence de fraîcheur des données :
    # - replay explicite (report_date fourni) -> mesurée par rapport à report_date ;
    # - rapport courant (report_date omis) -> mesurée par rapport à la date de
    #   génération réelle, afin de détecter des données locales périmées.
    freshness_reference = report_date if report_date is not None else generation_time

    # Anti-look-ahead : on coupe strictement à report_date.
    truncated = prices.loc[prices.index <= analysis_cutoff]
    if truncated.empty:
        raise PipelineValidationError("Aucune donnée avant la date de rapport.")

    # Source de vérité UNIQUE des métadonnées : uniquement les données tronquées.
    # Aucune observation postérieure à report_date ne doit apparaître nulle part.
    last_observation = truncated.dropna(how="all").index.max()

    m = config.momentum
    min_history = m.lookback_months + m.moving_average_window + 12
    roles_info = _apply_asset_roles(list(truncated.columns), asset_roles, config)
    # Contrôles qualité sur la fenêtre récente (tickers configurés uniquement).
    checked = [c for c in truncated.columns if c not in roles_info["extra"]]
    anomalies = quality_checks(truncated[checked],
                               since=truncated.index.max() - pd.Timedelta(days=RECENT_WINDOW_DAYS))
    kept, excluded = _select_universe(truncated[roles_info["strategy"]], min_history, config.benchmark_ticker)
    universe_prices = truncated[kept]

    monthly = to_monthly_prices(universe_prices)

    # Mois partiel : le dernier mois n'est officiel que si les données atteignent
    # son dernier jour calendaire, week-end inclus.
    partial_month: str | None = None
    if len(monthly):
        last_label = monthly.index[-1].normalize()
        from src.trading_calendar import last_session_of_month

        calendar_month_end = last_session_of_month(last_label)
        if last_observation.normalize() < calendar_month_end:
            partial_month = monthly.index[-1].strftime("%Y-%m")
            monthly = monthly.iloc[:-1]
    if monthly.empty:
        raise PipelineValidationError("Pas de mois complet disponible pour le signal.")

    # Une étiquette civile du dimanche ne doit pas apparaître comme une date
    # d'information future dans un rapport arrêté après la clôture du vendredi.
    relabelled_month = None
    if monthly.index[-1] > analysis_cutoff:
        relabelled_month = monthly.index[-1]
        monthly.index = pd.DatetimeIndex([*monthly.index[:-1], last_observation.normalize()])

    signal_date = monthly.index[-1]
    from src.trading_calendar import last_session_of_month

    if last_session_of_month(signal_date) > analysis_cutoff:
        raise PipelineValidationError("FUTURE_DATE : le signal utilise une date postérieure au rapport.")

    bt_cfg = config.backtest

    # Rémunération du cash : rendement mensuel du proxy monétaire si disponible
    # (même convention que les actifs : prix(t) / prix(t-1) - 1), sinon scalaire.
    cash_return: float | pd.Series = bt_cfg.cash_return
    cash_proxy_used: str | None = None
    if config.universe.use_cash_proxy_return and roles_info["cash_proxies"]:
        cash_proxy_used = roles_info["cash_proxies"][0]
        proxy_monthly = to_monthly_prices(truncated[cash_proxy_used]).reindex(monthly.index)
        if relabelled_month is not None:
            original_proxy = to_monthly_prices(truncated[cash_proxy_used])
            if relabelled_month in original_proxy.index:
                proxy_monthly.loc[monthly.index[-1]] = original_proxy.loc[relabelled_month]
        cash_return = proxy_monthly.pct_change(fill_method=None).fillna(bt_cfg.cash_return)

    # --- Stratégie Momentum ---
    momentum_bundle = build_momentum_weights(
        monthly,
        lookback_months=m.lookback_months,
        skip_months=m.skip_months,
        ma_window=m.moving_average_window,
        top_n=m.top_n,
        use_trend_filter=True,
        require_positive_momentum=m.require_positive_momentum,
        already_monthly=True,
    )
    momentum_bt = backtest_monthly_allocation(
        monthly, momentum_bundle["executed_weights"],
        initial_capital=bt_cfg.initial_capital,
        transaction_cost=bt_cfg.transaction_cost,
        cash_return=cash_return,
    )

    # --- Stratégie Momentum + Volatility Targeting (si activé) ---
    vt_cfg = config.volatility_targeting
    if vt_cfg.enabled:
        vt_bundle = build_vol_targeted_weights(
            monthly, momentum_bundle["executed_weights"],
            target_volatility=vt_cfg.target_volatility,
            vol_window=vt_cfg.volatility_window,
            periods_per_year=PERIODS_PER_YEAR,
            min_exposure=vt_cfg.min_exposure,
            max_exposure=vt_cfg.max_exposure,
        )
        vt_bt = backtest_monthly_allocation(
            monthly, vt_bundle["final_weights"],
            initial_capital=bt_cfg.initial_capital,
            transaction_cost=bt_cfg.transaction_cost,
            cash_return=cash_return,
        )
        realized_vol_now = vt_bundle["realized_volatility"].loc[signal_date]
    else:
        # VT désactivé : aucune logique VT (vol/exposition/poids) n'est exécutée.
        vt_bundle = None
        vt_bt = None
        realized_vol_now = None

    # --- Benchmark ---
    bench_series = to_monthly_prices(universe_prices[config.benchmark_ticker]).dropna()
    bench_bt = buy_and_hold(bench_series, initial_capital=bt_cfg.initial_capital)

    # --- Validation structurelle (peut faire échouer) ---
    fatal = _validate_weights(momentum_bundle["executed_weights"], "Momentum", generated_at)
    if vt_cfg.enabled:
        fatal += _validate_weights(vt_bundle["final_weights"], "Volatility Targeting", generated_at)
    if fatal:
        codes = ", ".join(a.code for a in fatal)
        raise PipelineValidationError(f"Validation échouée ({codes}).")

    # --- Poids courants (au dernier mois complet) ---
    mom_target = momentum_bundle["target_weights"].loc[signal_date]
    mom_executed = momentum_bundle["executed_weights"].loc[signal_date]

    momentum_report = _strategy_report_from_backtest(
        "Momentum défensif 12-1 + MA10",
        "Sélection mensuelle du meilleur ETF au-dessus de sa moyenne mobile ; sinon cash.",
        momentum_bt, mom_target, mom_executed, signal_date,
        momentum_row=momentum_bundle["momentum"].loc[signal_date],
        trend_row=momentum_bundle["trend_filter"].loc[signal_date],
        realized_volatility=realized_vol_now,
        target_volatility=None,
    )
    if vt_cfg.enabled:
        # Cible VT = cible Momentum mise à l'échelle par l'exposition courante.
        vt_target_frame = apply_volatility_target(
            momentum_bundle["target_weights"], vt_bundle["target_exposure"].fillna(0.0)
        )
        vt_report = _strategy_report_from_backtest(
            "Momentum + Volatility Targeting",
            "Momentum défensif dont l'exposition est ajustée par la volatilité réalisée.",
            vt_bt, vt_target_frame.loc[signal_date], vt_bundle["final_weights"].loc[signal_date],
            signal_date,
            momentum_row=momentum_bundle["momentum"].loc[signal_date],
            trend_row=momentum_bundle["trend_filter"].loc[signal_date],
            realized_volatility=realized_vol_now,
            target_volatility=vt_cfg.target_volatility,
        )
    else:
        vt_report = _disabled_vt_report(signal_date)
    benchmark_report = _benchmark_report(config.benchmark_ticker, bench_bt, signal_date)

    # --- Registre de stratégies et politique (schéma 1.3) ---
    strategy_backtests, strategies, followed, policy_block = _registry_and_policy(
        monthly, kept, roles_info["roles"], config, policy, cash_return=cash_return, signal_date=signal_date,
        generated_at=generated_at, momentum_bundle=momentum_bundle, momentum_bt=momentum_bt,
        vt_target_frame=vt_target_frame if vt_cfg.enabled else None, vt_bt=vt_bt,
    )

    # --- Qualité des données ---
    # Un rapport courant est comparé à son heure de génération ; un replay reste
    # ancré sur sa date demandée. Dans les deux modes, STALE_DATA utilise cet âge.
    data_age_days = int((freshness_reference.normalize() - last_observation.normalize()).days)
    last_dates = {c: universe_prices[c].dropna().index.max().date().isoformat() for c in kept}
    missing_values = {c: int(monthly[c].isna().sum()) for c in kept}

    data_quality = {
        "requested_assets": list(prices.columns),
        "n_requested": len(prices.columns),
        "kept_assets": kept,
        "n_kept": len(kept),
        "excluded_assets": excluded,
        "last_date_per_asset": last_dates,
        "missing_values_monthly": missing_values,
        "data_age_days": data_age_days,
        "partial_month": partial_month,
        "anomalies": anomalies,
        "warnings": [],
    }

    alerts = _build_alerts(
        config=config, generated_at=generated_at, data_age_days=data_age_days,
        excluded=excluded, n_months=len(monthly), partial_month=partial_month,
        data_refreshed=data_refreshed, universe_issues=roles_info, anomalies=anomalies,
        momentum_report=momentum_report,
        vt_report=vt_report, momentum_bt=momentum_bt, vt_bt=vt_bt,
        vt_enabled=vt_cfg.enabled,
    )
    data_quality["warnings"] = [a.message for a in alerts if a.code in {
        "STALE_DATA", "ASSET_EXCLUDED", "INSUFFICIENT_HISTORY", "PARTIAL_MONTH", "UNIVERSE_MISMATCH",
        "DATA_ANOMALY"}
        and a.level != "INFO"]

    crash = policy_block.get("crash_rule") or {}
    if crash.get("triggered"):
        alerts.append(_make_alert(
            "WARNING", "CRASH_RULE", "Règle de krach : relis ton engagement",
            f"La stratégie suivie est à {crash['current_drawdown']:.0%} de son plus haut (seuil "
            f"{-crash['threshold']:.0%}). Ta règle, écrite à froid : « {crash['text']} »", generated_at,
            current_drawdown=crash["current_drawdown"], threshold=crash["threshold"]))

    # Statut global déterminé APRÈS construction de toutes les alertes.
    if any(a.level == "CRITICAL" for a in alerts):
        status = "CRITICAL"
    elif any(a.level == "WARNING" for a in alerts):
        status = "OK_WITH_WARNINGS"
    else:
        status = "OK"

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "report_month": analysis_cutoff.strftime("%Y-%m"),
        "report_date": analysis_cutoff.date().isoformat(),
        "signal_date": signal_date.date().isoformat(),
        "last_observation": last_observation.date().isoformat(),
        "generated_at": generated_at,
        "freshness_reference": freshness_reference.date().isoformat(),
        "history_start": monthly.index.min().date().isoformat(),
        "history_end": signal_date.date().isoformat(),
        "reference_currency": "EUR",
        "data_mode": "refreshed" if data_refreshed else "local",
        "pipeline_status": status,
    }

    universe = {
        "benchmark": config.benchmark_ticker,
        "assets": kept,
        "n_assets": len(kept),
        "period_start": monthly.index.min().date().isoformat(),
        "period_end": signal_date.date().isoformat(),
        "n_months": len(monthly),
        "roles": roles_info["roles"],
        "cash_proxy": cash_proxy_used,
        "defensive_as_candidates": config.universe.defensive_as_candidates,
        "excluded_by_role": roles_info["excluded_by_role"],
        "missing_from_data": roles_info["missing"],
        "ignored_not_configured": roles_info["extra"],
    }

    allocation_comparison = {
        "vt_enabled": vt_cfg.enabled,
        "benchmark": benchmark_report.executed_weights,
        "momentum_target": momentum_report.target_weights,
        "volatility_targeted_target": vt_report.target_weights,
        "momentum_invested_exposure": momentum_report.invested_exposure,
        "volatility_targeted_invested_exposure": vt_report.invested_exposure,
        "exposure_difference": _clean_float(
            momentum_report.invested_exposure - vt_report.invested_exposure
        ) if vt_cfg.enabled else None,
    }

    risk = {
        "realized_volatility": _clean_float(realized_vol_now),
        "target_volatility": vt_cfg.target_volatility if vt_cfg.enabled else None,
        "momentum_max_drawdown": momentum_report.max_drawdown,
        "vt_max_drawdown": vt_report.max_drawdown,
        "vt_current_drawdown": _clean_float(compute_drawdown(vt_bt["Equity Curve"]).iloc[-1]) if vt_cfg.enabled else None,
        "vt_invested_exposure": vt_report.invested_exposure,
        "vt_cash_weight": vt_report.cash_weight,
    }

    manual_decision = {
        "status": "PENDING",
        "selected_strategy": None,
        "approved_weights": None,
        "comment": None,
        "validated_at": None,
    }

    previous_comparison = _compare_with_previous(previous_snapshot, momentum_report, vt_report, alerts)

    report = MonthlyReport(
        metadata=metadata,
        data_quality=data_quality,
        universe=universe,
        benchmark=benchmark_report,
        momentum_strategy=momentum_report,
        volatility_targeted_strategy=vt_report,
        allocation_comparison=allocation_comparison,
        risk=risk,
        alerts=alerts,
        manual_decision=manual_decision,
        previous_comparison=previous_comparison,
        policy=policy_block,
        strategies=strategies,
    )

    return MonthlyPipelineResult(
        report=report,
        monthly_prices=monthly,
        momentum_backtest=momentum_bt,
        vt_backtest=vt_bt,
        benchmark_backtest=bench_bt,
        momentum_weights=momentum_bundle["executed_weights"],
        vt_weights=vt_bundle["final_weights"] if vt_bundle is not None else None,
        realized_volatility=vt_bundle["realized_volatility"] if vt_bundle is not None else None,
        strategy_backtests=strategy_backtests,
        followed_strategy=followed,
    )


def _compare_with_previous(
    previous: dict | None,
    momentum_report: StrategyReport,
    vt_report: StrategyReport,
    alerts: list[Alert],
) -> dict | None:
    """Compare au snapshot précédent (si fourni). Ne bloque jamais le pipeline."""
    if not previous:
        return None
    try:
        prev_vt = previous["volatility_targeted_strategy"]
        prev_mom = previous["momentum_strategy"]
        prev_alerts = previous.get("alerts", [])
    except (KeyError, TypeError):
        return None

    def _delta(current: float | None, previous_value: object) -> float | None:
        """Écart robuste : None si l'une des deux valeurs est absente."""
        if current is None or previous_value is None:
            return None
        return _clean_float(current - float(previous_value))

    return {
        "previous_report_month": previous.get("metadata", {}).get("report_month"),
        "momentum_selected_changed": prev_mom.get("selected_assets") != momentum_report.selected_assets,
        "vt_selected_changed": prev_vt.get("selected_assets") != vt_report.selected_assets,
        "vt_exposure_change": _delta(vt_report.invested_exposure, prev_vt.get("invested_exposure")),
        "vt_cash_change": _delta(vt_report.cash_weight, prev_vt.get("cash_weight")),
        "realized_volatility_change": _delta(vt_report.realized_volatility, prev_vt.get("realized_volatility")),
        "vt_drawdown_change": _delta(vt_report.max_drawdown, prev_vt.get("max_drawdown")),
        "alert_count_change": len(alerts) - len(prev_alerts),
    }

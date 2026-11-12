"""Formatage du rapport mensuel : Markdown lisible et snapshot JSON (Projet 4).

Ce module ne calcule rien : il met en forme un ``MonthlyPipelineResult`` produit
par ``src/monthly_pipeline.py``.

- ``generate_markdown_report`` : rapport Markdown destiné à l'humain ;
- ``save_report_snapshot`` : snapshot JSON stable, futur **contrat de données**
  pour une éventuelle API / application / widget ;
- ``load_previous_snapshot`` : relit le snapshot du mois précédent pour la
  section de comparaison.

Le snapshot JSON ne contient jamais de ``NaN``/``Infinity`` ni d'objet pandas :
les valeurs non finies sont converties en ``null``.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path

from src.monthly_pipeline import MonthlyPipelineResult


# --------------------------------------------------------------------------- #
# Helpers de formatage
# --------------------------------------------------------------------------- #
def _pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f} %"


def _eur(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.2f} €"


def _num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _weights_table(weights: dict[str, float] | None) -> str:
    if not weights:
        return "Aucune allocation disponible."
    lines = ["| Actif | Poids |", "| ----- | -----:|"]
    for asset, weight in weights.items():
        lines.append(f"| {asset} | {weight * 100:.1f} % |")
    return "\n".join(lines)


def _json_safe(obj):
    """Convertit récursivement en structures JSON sûres (NaN/inf -> None)."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def _strategy_section(title: str, strat) -> str:
    lines = [
        f"### {title}",
        "",
        f"- **{strat.name}** — {strat.description}",
        f"- Signal daté du : {strat.signal_date}",
        f"- Actif(s) sélectionné(s) : {', '.join(strat.selected_assets) or 'aucun (cash)'}",
        f"- Exposition investie : {_pct(strat.invested_exposure, 0)} | Cash : {_pct(strat.cash_weight, 0)}",
    ]
    if strat.realized_volatility is not None:
        vol_line = f"- Volatilité réalisée : {_pct(strat.realized_volatility)}"
        if strat.target_volatility is not None:
            vol_line += f" | Cible : {_pct(strat.target_volatility)}"
        lines.append(vol_line)
    lines += [
        f"- CAGR : {_pct(strat.cagr)} | Volatilité : {_pct(strat.annualized_volatility)} | "
        f"Sharpe : {_num(strat.sharpe)} | Max drawdown : {_pct(strat.max_drawdown)}",
        f"- Rendement récent : {_pct(strat.recent_return)} | Capital théorique : {_eur(strat.theoretical_capital)}",
        f"- Turnover moyen : {_pct(strat.turnover)} | Coûts cumulés : {_pct(strat.cumulative_cost)}",
        "",
        "Poids cibles (allocation théorique à appliquer) :",
        "",
        _weights_table(strat.target_weights),
        "",
    ]
    return "\n".join(lines)


def _alerts_section(alerts) -> str:
    if not alerts:
        return "Aucune alerte.\n"
    lines = ["| Niveau | Code | Message |", "| ------ | ---- | ------- |"]
    order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    for alert in sorted(alerts, key=lambda a: order.get(a.level, 3)):
        lines.append(f"| {alert.level} | {alert.code} | {alert.message} |")
    return "\n".join(lines) + "\n"


def _registry_block(strategies: dict, policy: dict) -> str:
    """Tableau comparatif de toutes les stratégies du registre (schéma 1.3)."""
    if not strategies:
        return ""
    lines = ["### Toutes les stratégies du registre (comparaison, backtest depuis le début)", "",
             "| Stratégie | Allocation cible | Exposition | CAGR | Sharpe | Max drawdown | Drawdown courant |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, item in strategies.items():
        weights = ", ".join(f"{k} {v:.0%}" for k, v in (item.get("target_weights") or {}).items() if v and v > 1e-9)
        marker = " **(suivie)**" if name == policy.get("followed") else ""
        lines.append(f"| {item['label']}{marker} | {weights or 'cash'} | {_pct(item.get('invested_exposure'), 0)} | "
                     f"{_pct(item.get('cagr'))} | {_num(item.get('sharpe'))} | {_pct(item.get('max_drawdown'))} | "
                     f"{_pct(item.get('current_drawdown'))} |")
    limit = policy.get("max_drawdown_limit")
    if limit is not None:
        lines += ["", f"_Même convention pour toutes (frais d'entrée inclus). Drawdown maximal accepté par la "
                      f"politique : {limit:.0%}._"]
    return "\n".join(lines) + "\n"


def _universe_roles_block(universe: dict) -> str:
    """Lignes Markdown décrivant rôles, proxy cash et écarts de configuration."""
    lines = []
    cash_proxy = universe.get("cash_proxy")
    lines.append(
        f"- Rémunération du cash : {cash_proxy} (rendement mensuel)" if cash_proxy
        else "- Rémunération du cash : taux fixe de la configuration"
    )
    if "defensive_as_candidates" in universe:
        lines.append(
            "- Obligataire (defensive) classé avec les actions : "
            f"{'oui' if universe['defensive_as_candidates'] else 'non'}"
        )
    for key, label in (("excluded_by_role", "Écartés par rôle"),
                       ("missing_from_data", "Configurés mais absents des données"),
                       ("ignored_not_configured", "Présents dans les données mais non configurés")):
        if universe.get(key):
            lines.append(f"- {label} : {', '.join(universe[key])}")
    return "\n".join(lines)


def _relative_figures(figures: dict[str, Path] | None, base_dir: Path) -> dict[str, str]:
    """Chemins des figures relatifs au dossier du rapport, en séparateurs ``/``."""
    relative: dict[str, str] = {}
    for name, figure_path in (figures or {}).items():
        try:
            relative[name] = Path(figure_path).resolve().relative_to(base_dir.resolve()).as_posix()
        except ValueError:
            relative[name] = Path(figure_path).as_posix()
    return relative


_FIGURE_CAPTIONS = {
    "equity": "Capital théorique (frais inclus)",
    "drawdown": "Drawdown",
    "allocation": "Allocation exécutée dans le temps",
    "volatility": "Volatilité réalisée vs cible",
}

DECISION_JOURNAL_TEMPLATE = """## Journal de décision

_À compléter à la main avant `paper-decision` (modèle du guide)._

- **Stratégie suivie** :
- **Signal actuel** :
- **Allocation cible** :
- **Allocation actuelle (réelle)** :
- **Écart à corriger** :
- **Arguments pour agir** :
- **Arguments contre agir** :
- **Risques identifiés** :
- **Décision finale** :
- **Émotion / niveau de confiance** :
- **Ce que je vérifierai le mois prochain** :
"""


def _figures_block(relative: dict[str, str]) -> str:
    if not relative:
        return "Graphiques non générés pour ce rapport.\n"
    lines = []
    for name, rel_path in relative.items():
        caption = _FIGURE_CAPTIONS.get(name, name)
        lines.append(f"### {caption}\n\n![{caption}]({rel_path})\n")
    return "\n".join(lines)


def generate_markdown_report(
    result: MonthlyPipelineResult,
    output_path: str | Path,
    figures: dict[str, Path] | None = None,
) -> Path:
    """Écrit le rapport Markdown et renvoie son chemin.

    ``figures`` (optionnel) : ``{nom: chemin PNG}`` produit par
    ``src.report_figures.save_monthly_figures`` ; liens relatifs au rapport.
    """
    report = result.report
    meta = report.metadata
    dq = report.data_quality
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    prev = report.previous_comparison
    if prev:
        prev_lines = [
            f"- Rapport précédent : {prev.get('previous_report_month')}",
            f"- Changement d'actif (VT) : {'oui' if prev.get('vt_selected_changed') else 'non'}",
            f"- Variation d'exposition VT : {_pct(prev.get('vt_exposure_change'))}",
            f"- Variation du cash VT : {_pct(prev.get('vt_cash_change'))}",
            f"- Variation de volatilité réalisée : {_pct(prev.get('realized_volatility_change'))}",
        ]
        prev_block = "\n".join(prev_lines)
    else:
        prev_block = "Aucun rapport précédent disponible."

    comp = report.allocation_comparison
    risk = report.risk

    # Volatility Targeting activé ou non : la section et la comparaison diffèrent.
    vt = report.volatility_targeted_strategy
    if vt.enabled:
        vt_section = _strategy_section("Momentum + VT", vt)
        comparison_block = (
            f"- Exposition investie — Momentum : {_pct(comp['momentum_invested_exposure'], 0)} | "
            f"VT : {_pct(comp['volatility_targeted_invested_exposure'], 0)}\n"
            f"- Écart d'exposition (Momentum − VT) : {_pct(comp['exposure_difference'])}"
        )
        main_strategy_name = "Momentum + Volatility Targeting"
        current_alloc_table = _weights_table(vt.target_weights)
    else:
        vt_section = "Volatility Targeting : désactivé dans la configuration\n"
        comparison_block = "Comparaison Momentum / VT : non applicable (Volatility Targeting désactivé)."
        main_strategy_name = "Momentum défensif"
        current_alloc_table = _weights_table(report.momentum_strategy.target_weights)

    policy = report.policy or {}
    if policy.get("target_weights"):
        main_strategy_name = f"{policy['label']} (`{policy['followed']}`, config/policy.yaml)"
        current_alloc_table = _weights_table(policy["target_weights"])
    registry_block = _registry_block(report.strategies or {}, policy)
    crash = policy.get("crash_rule") or {}
    crash_block = ""
    if crash:
        drawdown = crash.get("current_drawdown")
        state = ("**DÉCLENCHÉE : relis-la avant toute décision.**" if crash.get("triggered")
                 else "non déclenchée")
        crash_block = (f"\n## Ta règle de krach\n\n> {crash['text']}\n\n"
                       f"Seuil : baisse de {crash['threshold']:.0%} depuis le plus haut ; baisse actuelle de la "
                       f"stratégie suivie : {'n/a' if drawdown is None else f'{drawdown:.1%}'} ; {state}\n")

    content = f"""# Rapport mensuel — {meta['report_month']}

_Ce rapport est produit à des fins éducatives et de paper trading._
_Aucun ordre n'est exécuté ; la décision finale reste humaine._

## Statut général

- Statut du pipeline : **{meta['pipeline_status']}**
- Date d'arrêté (report_date) : {meta['report_date']}
- Date effective du signal : **{meta['signal_date']}** (dernier mois civil complet)
- Dernière observation disponible : {meta['last_observation']}
- Généré le : {meta['generated_at']}
- Devise de référence : {meta['reference_currency']} | Mode : {meta['data_mode']}
- Schéma : v{meta['schema_version']}

{crash_block}
## Qualité des données

- Actifs demandés : {dq['n_requested']} | retenus : {dq['n_kept']}
- Actifs exclus : {', '.join(f'{k} ({v})' for k, v in dq['excluded_assets'].items()) or 'aucun'}
- Ancienneté des données : {dq['data_age_days']} jours
- Mois partiel exclu du signal : {dq['partial_month'] or 'non'}
- Avertissements : {', '.join(dq['warnings']) or 'aucun'}

## Univers retenu

- Benchmark : {report.universe['benchmark']}
- Actifs : {', '.join(report.universe['assets'])}
- Période : {report.universe['period_start']} → {report.universe['period_end']} ({report.universe['n_months']} mois)
{_universe_roles_block(report.universe)}

## Benchmark

{_strategy_section('Benchmark', report.benchmark)}
## Stratégie Momentum

{_strategy_section('Momentum', report.momentum_strategy)}
## Stratégie Momentum + Volatility Targeting

{vt_section}
## Comparaison des allocations

{comparison_block}

## Allocation actuelle théorique (à valider manuellement)

Stratégie suivie selon la politique d'investissement : **{main_strategy_name}**.

{current_alloc_table}

{registry_block}

## Variation depuis le rapport précédent

{prev_block}

## Risque

- Volatilité réalisée : {_pct(risk['realized_volatility'])} (cible {_pct(risk['target_volatility'])})
- Drawdown courant (VT) : {_pct(risk['vt_current_drawdown'])}
- Max drawdown — Momentum : {_pct(risk['momentum_max_drawdown'])} | VT : {_pct(risk['vt_max_drawdown'])}
- Exposition investie VT : {_pct(risk['vt_invested_exposure'], 0)} | Cash : {_pct(risk['vt_cash_weight'], 0)}

## Alertes

{_alerts_section(report.alerts)}
## Graphiques

{_figures_block(_relative_figures(figures, path.parent))}
## Décision manuelle

- Décision : À renseigner
- Allocation retenue : À renseigner
- Action réelle effectuée : Aucune par défaut
- Commentaire :
- Date de validation :

## Limites

- Univers étroit et corrélé, historique court : à interpréter avec prudence.
- Données Yahoo Finance non officielles ; ni fiscalité, ni slippage réels.
- Backtest total-return approximatif ; les performances passées ne préjugent pas du futur.

## Dernière actualisation

Données arrêtées au {meta['last_observation']} — rapport généré le {meta['generated_at']}.

{DECISION_JOURNAL_TEMPLATE}"""
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #
def _series_records(result: MonthlyPipelineResult) -> list[dict]:
    """Séries mensuelles pour les graphiques interactifs (schéma 1.2).

    Une ligne par fin de mois : capital théorique et drawdown de chaque
    stratégie, exposition investie et actif(s) détenus (Momentum + VT si actif).
    """
    curves = {"benchmark": result.benchmark_backtest["Equity Curve"],
              "momentum": result.momentum_backtest["Equity Curve"]}
    if result.vt_backtest is not None:
        curves["momentum_vt"] = result.vt_backtest["Equity Curve"]
    main = result.vt_backtest if result.vt_backtest is not None else result.momentum_backtest
    followed = result.followed_strategy
    if followed and result.strategy_backtests and followed in result.strategy_backtests:
        main = result.strategy_backtests[followed]  # exposition / détention de la stratégie suivie
        if followed not in ("benchmark", "momentum", "momentum_vt"):
            curves[followed] = main["Equity Curve"]
    index = result.momentum_backtest.index
    records = []
    drawdowns = {name: curve / curve.cummax() - 1.0 for name, curve in curves.items()}
    for date in index:
        row = {"date": date.date().isoformat()}
        for name, curve in curves.items():
            row[f"{name}_equity"] = _clean(curve.get(date))
            row[f"{name}_drawdown"] = _clean(drawdowns[name].get(date))
        row["exposure"] = _clean(main["Invested Exposure"].get(date))
        row["held"] = str(main["Selected Assets"].get(date, ""))
        records.append(row)
    return records


def _clean(value) -> float | None:
    if value is None:
        return None
    number = float(value)
    return None if math.isnan(number) or math.isinf(number) else number


def _report_to_dict(result: MonthlyPipelineResult, figures: dict[str, str] | None = None) -> dict:
    report = result.report
    return {
        "figures": dict(figures or {}),
        "series": _series_records(result),
        "policy": report.policy,
        "strategies": report.strategies,
        "schema_version": report.metadata["schema_version"],
        "partial_month": report.data_quality.get("partial_month"),
        "freshness_reference": report.metadata.get("freshness_reference"),
        "metadata": report.metadata,
        "data_quality": report.data_quality,
        "universe": report.universe,
        "benchmark": asdict(report.benchmark),
        "momentum_strategy": asdict(report.momentum_strategy),
        "volatility_targeted_strategy": asdict(report.volatility_targeted_strategy),
        "allocation_comparison": report.allocation_comparison,
        "risk": report.risk,
        "alerts": [asdict(a) for a in report.alerts],
        "manual_decision": report.manual_decision,
        "previous_comparison": report.previous_comparison,
    }


def save_report_snapshot(
    result: MonthlyPipelineResult,
    output_path: str | Path,
    figures: dict[str, Path] | None = None,
) -> Path:
    """Écrit le snapshot JSON (contrat de données) et renvoie son chemin.

    ``figures`` : chemins PNG, sérialisés relativement au dossier du snapshot.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_safe(_report_to_dict(result, _relative_figures(figures, path.parent)))
    # allow_nan=False garantit l'absence de NaN/Infinity non standard.
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8", newline="\n")
    return path


def load_previous_snapshot(output_dir: str | Path, current_month: str) -> dict | None:
    """Renvoie le snapshot JSON le plus récent antérieur à ``current_month``.

    ``current_month`` au format ``YYYY-MM``. Retourne ``None`` si aucun.
    """
    directory = Path(output_dir)
    if not directory.is_dir():
        return None
    candidates = sorted(directory.glob("*-report.json"))
    previous = [p for p in candidates if p.name[:7] < current_month]
    if not previous:
        return None
    with open(previous[-1], "r", encoding="utf-8") as handle:
        snapshot = json.load(handle)
    # Anciens snapshots : les champs temporels optionnels absents valent None.
    snapshot.setdefault("partial_month", None)
    snapshot.setdefault("freshness_reference", None)
    return snapshot

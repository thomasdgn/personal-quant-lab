"""Résumé du mois en une page HTML autonome (lecture sur téléphone).

Rassemble : statut du rapport, politique suivie et allocation proposée,
alertes, plan de versement du mois (s'il existe), performance du paper
trading et du portefeuille réel, règles du PEA. Le fichier contient des
données personnelles : il est écrit dans ``reports/monthly/*.html`` (ignoré
par Git). Aucun ordre n'est passé.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.html_report import markdown_to_html


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _plan_section(plan_path: Path | None, month: str) -> list[str]:
    if plan_path is None or not plan_path.exists() or not plan_path.name.startswith(month):
        return ["Aucun plan pour ce mois : `python main.py plan-contribution`."]
    text = plan_path.read_text(encoding="utf-8")
    if "## Achats proposés" not in text:
        return [text]
    body = text.split("## Achats proposés", 1)[1]
    body = body.split("\n## ", 1)[0]
    return ["**Proposition uniquement, aucun ordre passé.**", "", "### Achats proposés" + body.rstrip()]


def build_month_summary(snapshot: dict, *, plan_path: Path | None = None, paper_lines: list[str] | None = None,
                        portfolio: dict | None = None) -> str:
    """Markdown du résumé (converti ensuite en HTML autonome)."""
    meta = snapshot.get("metadata", {})
    month = meta.get("report_month", "")
    policy = snapshot.get("policy") or {}
    lines = [f"# Résumé du mois {month}", "",
             f"Statut **{meta.get('pipeline_status')}** · signal du {meta.get('signal_date')} · données au "
             f"{meta.get('last_observation')}", "",
             "## Allocation proposée (à valider manuellement)", ""]
    if policy:
        lines.append(f"Politique : **{policy['label']}** (drawdown max accepté {policy['max_drawdown_limit']:.0%}).")
        lines += ["", "| Actif | Poids |", "| --- | ---: |"]
        lines += [f"| {k} | {v:.1%} |" for k, v in policy["target_weights"].items() if v and v > 1e-9]
    crash = policy.get("crash_rule") or {}
    if crash:
        state = "**déclenchée**" if crash.get("triggered") else "non déclenchée"
        lines += ["", "## Ta règle de krach", "", f"> {crash['text']}", "",
                  f"Seuil {crash['threshold']:.0%} ; état : {state}."]
    alerts = snapshot.get("alerts") or []
    important = [a for a in alerts if a.get("level") in ("WARNING", "CRITICAL")]
    lines += ["", f"## Alertes ({len(important)} importantes, {len(alerts) - len(important)} informatives)", ""]
    lines += [f"- **{a['level']}** {a['message']}" for a in important] or ["Aucune alerte importante."]
    lines += ["", "## Plan de versement", ""] + _plan_section(plan_path, month)
    if paper_lines:
        lines += ["", "## Paper trading", ""] + [f"- {line.strip()}" for line in paper_lines]
    if portfolio:
        perf, pea = portfolio.get("perf"), portfolio.get("pea") or {}
        lines += ["", "## Portefeuille réel", ""]
        if perf:
            lines += [f"- Valeur {perf['final_value']:,.0f} € pour {perf['net_contributions']:,.0f} € versés".replace(",", " "),
                      f"- TRI annualisé {_pct(perf['mwr'])} · TWR {_pct(perf['comparison'].get('real_twr'))} · "
                      f"frais {perf['fees_total']:,.2f} €".replace(",", " ")]
        else:
            lines.append("- Aucun journal de transactions.")
        lines += [f"- PEA : {alert}" for alert in pea.get("alerts", [])]
    lines += ["", "_Usage éducatif et paper trading ; aucun ordre n'est exécuté par le laboratoire._", ""]
    return "\n".join(lines)


def write_month_summary(snapshot: dict, output_path: str | Path, **kwargs) -> Path:
    """Écrit le résumé HTML autonome (le Markdown intermédiaire reste temporaire)."""
    markdown = build_month_summary(snapshot, **kwargs)
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "resume.md"
        source.write_text(markdown, encoding="utf-8", newline="\n")
        return markdown_to_html(source, output_path)

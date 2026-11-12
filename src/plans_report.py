"""Rapport des plans d'investissement (Markdown, graphiques PNG, JSON).

Le rapport contient les montants du profil : il est écrit dans
``reports/plans/`` (ignoré par Git). Aucun ordre, aucun conseil.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402

from src.investor_profile import TIME_BUDGETS, profile_lines  # noqa: E402
from src.taxes import ENVELOPE_RULES  # noqa: E402

ENVELOPE_LABELS = {"pea": "PEA", "assurance_vie": "Assurance-vie", "cto": "CTO", "crypto": "Crypto",
                   "cto_surplus": "CTO (surplus du plafond PEA)"}
POCKET_LABELS = {"etf": "ETF", "strategie": "Stratégie", "fonds_euros": "Fonds euros", "crypto": "Crypto"}
COLORS = ["#2563eb", "#16a34a", "#d97706", "#9333ea", "#dc2626", "#0891b2", "#4b5563", "#db2777"]


def eur(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.0f} €".replace(",", " ")


def pct(value: float | None, digits: int = 0) -> str:
    return "n/a" if value is None else f"{value:.{digits}%}"


def pocket_content(pocket) -> str:
    if pocket.type in ("etf", "crypto"):
        return ", ".join(f"{t} {w:.0%}" for t, w in pocket.allocation.items())
    if pocket.type == "strategie":
        return f"stratégie `{pocket.strategie}`"
    return "rendement constant (hypothèse)"


# --------------------------------------------------------------------------- #
# Graphiques
# --------------------------------------------------------------------------- #
def _euro_axis(ax, axis: str = "y") -> None:
    formatter = mticker.FuncFormatter(lambda v, _: f"{v / 1000:,.0f} k€".replace(",", " "))
    (ax.xaxis if axis == "x" else ax.yaxis).set_major_formatter(formatter)
    ax.grid(True, alpha=0.3)


def plan_figure(item: dict, path: Path) -> Path:
    """Éventail des projections (euros d'aujourd'hui) et relecture historique."""
    sim, replay = item["simulation"], item["replay"]
    fan = sim["fan"]
    years = np.array(fan["months"]) / 12
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 3.8))
    real = fan["real"]
    left.fill_between(years, real["p10"], real["p90"], color="#2563eb", alpha=0.15, label="80 % des scénarios")
    left.fill_between(years, real["p25"], real["p75"], color="#2563eb", alpha=0.25, label="50 % des scénarios")
    left.plot(years, real["p50"], color="#1d4ed8", linewidth=2, label="Médiane")
    left.plot(years, fan["contributed_real"], color="#6b7280", linestyle="--", label="Versé (en € d'aujourd'hui)")
    left.set_title("Projection (valeur brute, euros d'aujourd'hui)")
    left.set_xlabel("années")
    _euro_axis(left)
    left.legend(fontsize=8, loc="upper left")
    right.plot(replay.index, replay["valeur"], color="#16a34a", linewidth=1.8, label="Valeur (vrai passé)")
    right.plot(replay.index, replay["versé"], color="#6b7280", linestyle="--", label="Versé")
    right.set_title(f"Vrai passé : départ en {replay.index[0]:%Y-%m}, {len(replay) // 12} ans (€ courants)")
    _euro_axis(right)
    right.legend(fontsize=8, loc="upper left")
    fig.suptitle(item["plan"].nom, fontsize=12, fontweight="bold")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def comparison_figure(study: dict, path: Path) -> Path:
    order = study["ranking"]
    fig, ax = plt.subplots(figsize=(10, 0.55 * len(order) + 1.2))
    for i, pid in enumerate(order[::-1]):
        final = study["results"][pid]["simulation"]["final"]["net_real"]
        ax.plot([final["p10"], final["p90"]], [i, i], color=COLORS[i % len(COLORS)], linewidth=6, alpha=0.35,
                solid_capstyle="round")
        ax.plot(final["p50"], i, "o", color=COLORS[i % len(COLORS)], markersize=9)
    ax.set_yticks(range(len(order)), [study["results"][p]["plan"].nom for p in order[::-1]])
    contributed = next(iter(study["results"].values()))["simulation"]["contributed_real"]
    ax.axvline(contributed, color="#6b7280", linestyle="--", linewidth=1)
    ax.text(contributed, -0.6, " total versé", color="#6b7280", fontsize=8, va="bottom")
    ax.set_title("Valeur nette à l'horizon en euros d'aujourd'hui (point : médiane ; barre : 80 % des scénarios)",
                 fontsize=10)
    _euro_axis(ax, "x")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def _rel(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def generate_plans_report(study: dict, output_path: str | Path, *, figures: bool = True) -> Path:
    path = Path(output_path)
    profile, assessment, hyp = study["profile"], study["assessment"], study["hypotheses"]
    from src.plans import HISTORICAL

    scenario = study.get("scenario") or HISTORICAL
    first = next(iter(study["results"].values()))["simulation"]
    lines = [
        "# Plans d'investissement — simulations pour ton profil", "",
        f"Date de génération : {date.today().isoformat()}", "",
        "**Ordres de grandeur, pas des promesses ni des conseils.** Les plans sont des modèles génériques "
        "(`config/plans.yaml`) confrontés à tes préférences déclarées (`config/profil.yaml`). Le choix t'appartient ; "
        "le laboratoire ne passe aucun ordre et ne modifie pas la stratégie suivie.", "",
        "## Ton profil", "",
    ]
    lines += [f"- {line}" for line in profile_lines(profile, assessment)]
    lines += [f"- _{note}_" for note in assessment.notes]
    lines += [
        "", "## Méthode et hypothèses", "",
        f"- Rendements mensuels historiques {study['window'][0]} → {study['window'][1]} en EUR (**partiellement "
        "synthétiques** avant la cotation des ETF PEA), tirés par blocs de "
        f"{hyp.bloc_mois} mois ({first['n_sims']} trajectoires) : les crises restent groupées.",
        f"- Versement de {eur(profile.versement_mensuel_eur)} par mois après {eur(profile.capital_initial_eur)} de "
        f"départ, pendant {profile.horizon_ans} ans ({eur(first['contributed'])} versés au total).",
        f"- Inflation {hyp.inflation_pct:.1f} %/an (montants « en euros d'aujourd'hui ») ; fonds euros "
        f"{hyp.fonds_euros_taux_pct:.1f} %/an ; frais de gestion des unités de compte {hyp.av_frais_gestion_uc_pct:.1f} %/an ; "
        f"crypto recentrée sur {hyp.crypto_rendement_annuel_pct:.0f} %/an (frais d'achat {hyp.crypto_frais_achat_pct:.1f} %).",
        "- Valeur **nette** = retrait total à l'horizon après fiscalité de chaque enveloppe (hypothèse prudente) ; "
        f"revenu soutenable = valeur nette × {hyp.taux_retrait_pct:.1f} % / 12.",
        f"- **Scénario de rendement : {scenario.label}**"
        + (f" — {scenario.description}" if scenario.description else "")
        + " Voir la section « Sensibilité » pour les autres scénarios (`--scenario`).",
        f"- Adéquation : seuils de risque {hyp.seuil_risque_ok:.0%} / {hyp.seuil_risque_reserve:.0%} = **conventions** "
        "(`config/plans.yaml`), pas des résultats calibrés.",
        *[f"- {note}" for note in study["notes"]],
        "", "## Comparaison des plans", "",
    ]
    base = path.parent
    fig_dir = base / "figures"
    if figures:
        comp = comparison_figure(study, fig_dir / "plans_comparaison.png")
        lines += [f"![Comparaison des plans]({_rel(comp, base)})", ""]
    lines += ["| Plan | Adéquation | Temps | Valeur nette p10 / **médiane** / p90 (€ d'aujourd'hui) | Revenu mensuel médian | "
              "Pire baisse médiane | P(baisse > ta limite) | Rendement annuel implicite | Vrai passé : pire / médiane / "
              "meilleur départ | Modèle vs vrai passé |",
              "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |"]
    for pid in study["ranking"]:
        item = study["results"][pid]
        sim, hist = item["simulation"], item["historical"]
        f = sim["final"]
        hist_text = (f"{eur(hist['net_real']['min'])} / {eur(hist['net_real']['median'])} / {eur(hist['net_real']['max'])}"
                     if hist["available"] else "n/a")
        lines.append(f"| {item['plan'].nom} | {item['fit']['status']} | {TIME_BUDGETS[item['plan'].temps]} | "
                     f"{eur(f['net_real']['p10'])} / **{eur(f['net_real']['p50'])}** / {eur(f['net_real']['p90'])} | "
                     f"{eur(f['income_real_monthly']['p50'])} | {pct(sim['drawdown']['p50'])} | "
                     f"{pct(sim['drawdown']['prob_beyond_tolerance'])} | {pct(sim['implied_return_median'], 1)} | "
                     f"{hist_text} | {(item.get('model_check') or {}).get('status', 'n/a')} |")
    lines += ["", "_Tri : adéquation au profil, puis valeur nette médiane. « Vrai passé » : le plan lancé à chaque mois "
                  "de départ possible de l'historique (fenêtres complètes seulement), sur les vrais rendements. "
                  "« Modèle vs vrai passé » : la médiane du vrai passé tombe-t-elle dans le cœur (25-75 %) de la "
                  "distribution simulée sur le même historique ?_", ""]
    sensitivity = study.get("sensitivity")
    if sensitivity:
        keys = list(next(iter(sensitivity.values())))
        labels = [next(iter(sensitivity.values()))[k]["label"] for k in keys]
        lines += ["## Sensibilité aux hypothèses de rendement", "",
                  "Valeur nette médiane à l'horizon (euros d'aujourd'hui) ; entre crochets, 1 scénario sur 10 en dessous. "
                  "L'écart entre colonnes montre combien le résultat dépend d'une hypothèse que personne ne connaît.", "",
                  "| Plan | " + " | ".join(labels) + " |", "| --- | " + " | ".join("---:" for _ in keys) + " |"]
        for pid in study["ranking"]:
            cells = [f"{eur(sensitivity[pid][k]['p50'])} [{eur(sensitivity[pid][k]['p10'])}]" for k in keys]
            lines.append(f"| {study['results'][pid]['plan'].nom} | " + " | ".join(cells) + " |")
        lines.append("")
    for pid in study["ranking"]:
        item = study["results"][pid]
        plan, sim, hist, fit = item["plan"], item["simulation"], item["historical"], item["fit"]
        f = sim["final"]
        lines += [f"## {plan.nom} — {fit['status']}", "", plan.resume, "", f"**Pour qui ?** {plan.pour_qui}", "",
                  f"**Temps :** {TIME_BUDGETS[plan.temps]} · **complexité :** {plan.complexite}/4 · "
                  f"**horizon minimal :** {plan.horizon_min_ans} ans", "",
                  "| Poche | Enveloppe | Part du versement | Contenu | Par mois |", "| --- | --- | ---: | --- | ---: |"]
        for pocket in plan.poches:
            lines.append(f"| {pocket.nom} | {ENVELOPE_LABELS[pocket.enveloppe]} | {pocket.part:.0%} | "
                         f"{POCKET_LABELS[pocket.type]} : {pocket_content(pocket)} | "
                         f"{eur(profile.versement_mensuel_eur * pocket.part)} |")
        if figures:
            fig = plan_figure(item, fig_dir / f"plan_{plan.id}.png")
            lines += ["", f"![{plan.nom}]({_rel(fig, base)})"]
        lines += ["", "**Ce que l'on peut attendre** (à l'horizon, euros d'aujourd'hui, après impôts)", "",
                  f"- Scénario défavorable (1 sur 10) : **{eur(f['net_real']['p10'])}** · médian : "
                  f"**{eur(f['net_real']['p50'])}** · favorable (1 sur 10) : **{eur(f['net_real']['p90'])}**, "
                  f"pour {eur(sim['contributed'])} versés ({eur(sim['contributed_real'])} en euros d'aujourd'hui).",
                  f"- Revenu mensuel soutenable médian : {eur(f['income_real_monthly']['p50'])} "
                  f"(défavorable {eur(f['income_real_monthly']['p10'])}).",
                  f"- Pire baisse en cours de route : médiane {pct(sim['drawdown']['p50'])}, 1 scénario sur 10 pire que "
                  f"{pct(sim['drawdown']['p10'])} ; perte maximale affichée sur le relevé (médiane) "
                  f"{eur(sim['max_loss_eur']['p50'])}.",
                  f"- Probabilité de finir sous le total versé (net) : {pct(sim['prob_loss'])} ; en pouvoir d'achat : "
                  f"{pct(sim['prob_real_loss'])}.",
                  f"- Frais d'ordre cumulés : {eur(sim['fees_total'])}."]
        if sim["prob_goal"] is not None:
            lines.append(f"- Probabilité d'atteindre ton objectif de {eur(sim['goal_real'])} : **{pct(sim['prob_goal'])}**.")
        if hist["available"]:
            lines.append(f"- Vrai passé ({hist['n_windows']} départs de {hist['first_start'][:7]} à {hist['last_start'][:7]}) :"
                         f" pire {eur(hist['net_real']['min'])} (départ {hist['worst_start'][:7]}), médiane "
                         f"{eur(hist['net_real']['median'])}, meilleur {eur(hist['net_real']['max'])}.")
        else:
            lines.append(f"- Vrai passé : indisponible ({hist['reason']})")
        check = item.get("model_check")
        if check:
            lines.append(f"- **Contrôle du modèle ({check['status']})** : {check['text']}")
        if plan.has_crypto:
            lines.append("- **Attention** : le graphique du vrai passé contient la hausse exceptionnelle du bitcoin "
                         "depuis 2015 ; les projections ne l'extrapolent volontairement pas (rendement recentré).")
        lines += ["", "**Adéquation avec ton profil**", ""]
        marks = {"ok": "✔", "reserve": "⚠", "ko": "✖"}
        lines += [f"- {marks[c['niveau']]} {c['message']}" for c in fit["checks"]]
        lines += ["", "**Routine mensuelle**", ""] + [f"{i}. {step}" for i, step in enumerate(plan.routine, 1)] + [""]
    lines += ["## Les enveloppes en bref", ""]
    lines += [f"- **{ENVELOPE_LABELS[k]}** : {text}" for k, text in ENVELOPE_RULES.items()]
    lines += ["", "## Limites", "",
              "- Le passé (2005-2026) a été favorable aux actions mondiales : le scénario « historique » le rejoue, "
              "les scénarios « central » et « défavorable » recentrent les rendements sur des hypothèses plus modestes. "
              "Aucun n'est une prévision.",
              "- Données partiellement synthétiques avant la cotation des ETF PEA ; bootstrap = rééchantillonnage du "
              "passé, pas une prévision.",
              "- Fiscalité simplifiée (retrait total unique, taux de `config/patrimoine.yaml`) : les taux évoluent avec "
              "les lois de finances, à vérifier.",
              "- Les versements sont supposés constants ; aucun retrait avant l'horizon.", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def study_to_json(study: dict) -> dict:
    """Version sérialisable (tableau de bord, archivage)."""
    results = {}
    for pid, item in study["results"].items():
        replay = item["replay"]
        results[pid] = {
            "plan": asdict(item["plan"]), "simulation": item["simulation"], "historical": item["historical"],
            "fit": item["fit"], "model_check": item.get("model_check"),
            "replay": {"dates": [d.date().isoformat() for d in replay.index], "valeur": replay["valeur"].round(2).tolist(),
                       "versé": replay["versé"].round(2).tolist()},
        }
    return {"generated": date.today().isoformat(), "window": study["window"], "notes": study["notes"],
            "profile": study["profile"].to_dict(), "assessment": asdict(study["assessment"]),
            "hypotheses": asdict(study["hypotheses"]), "prudent": study["prudent"], "ranking": study["ranking"],
            "scenario": asdict(study["scenario"]) if study.get("scenario") else None,
            "sensitivity": study.get("sensitivity"), "results": results}


def save_plans_json(study: dict, output_path: str | Path) -> Path:
    from src.results import write_results_json

    return write_results_json(study_to_json(study), output_path, kind="plans", start=study["window"][0],
                              end=study["window"][1], notes=study["notes"], indent=1)

"""Fiches pédagogiques des stratégies du registre.

Chaque fiche associe un texte explicatif (principe, règles exactes, temps
requis, forces, faiblesses, pour qui, erreurs fréquentes) aux **résultats
mesurés** : robustesse sur historique long (``main.py robustness``) et
comportement dans les crises (``main.py stress``). Les textes décrivent des
mécanismes, pas des recommandations ; aucun ordre n'est passé.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

CARDS: dict[str, dict] = {
    "benchmark": {
        "titre": "Buy & Hold MSCI World",
        "resume": "Acheter chaque mois un ETF Monde et ne jamais vendre : la référence que toute stratégie doit battre.",
        "principe": "Posséder l'économie mondiale (environ 1 400 grandes entreprises de 23 pays développés) sans "
                    "jamais essayer de deviner le marché. Le rendement vient de la croissance des entreprises et "
                    "des dividendes réinvestis.",
        "regles": ["Chaque mois, investir tout le versement dans CW8.PA (ou WPEA.PA, part moins chère).",
                   "Ne jamais vendre, même pendant un krach.",
                   "Aucun signal à lire, aucun rééquilibrage."],
        "temps": "5 min / mois", "complexite": 1, "lignes": 1,
        "forces": ["Le plus simple et le moins cher : frais d'ordre minimaux, aucune décision à prendre.",
                   "Capte toute la hausse de long terme des marchés.",
                   "Impossible de « rater » un rebond en étant sorti du marché."],
        "faiblesses": ["Subit toutes les baisses : −51 % en 2008-09 (en euros), −19 % en 2020.",
                       "Peut rester sous son plus haut plusieurs années (environ 4 ans et demi après 2008).",
                       "Environ 70 % d'actions américaines : concentration géographique et monétaire (dollar)."],
        "pour_qui": "Tout investisseur long terme qui veut une méthode simple et peut supporter de fortes baisses.",
        "erreurs": ["Vendre pendant un krach puis racheter trop tard.",
                    "Arrêter les versements quand le marché baisse (c'est justement là qu'ils achètent le moins cher)."],
    },
    "momentum": {
        "titre": "Momentum défensif (12-1, moyenne mobile 10 mois, 1 ETF)",
        "resume": "Détenir l'ETF qui a le plus monté sur un an, s'il est en tendance haussière ; sinon rester en cash.",
        "principe": "Les actifs qui ont monté ont tendance à continuer à court terme (effet momentum), et un marché "
                    "sous sa moyenne mobile est souvent en phase baissière. On suit la tendance au lieu de la prédire.",
        "regles": ["Fin de mois : classer les ETF selon leur performance sur 12 mois, en excluant le dernier mois.",
                   "Garder le premier s'il cote au-dessus de sa moyenne mobile 10 mois ; sinon, cash.",
                   "Appliquer la décision au début du mois suivant (vendre l'ancien ETF si besoin, acheter le nouveau)."],
        "temps": "30 min / mois", "complexite": 3, "lignes": 1,
        "forces": ["Sort du marché lors des baisses longues (2008, 2022) et limite les pertes.",
                   "Règles mécaniques : aucune émotion dans la décision."],
        "faiblesses": ["Concentration sur un seul ETF à la fois (parfois un marché régional ou sectoriel).",
                       "Faux signaux (« whipsaws ») : vendre en bas puis racheter plus haut lors des rebonds en V.",
                       "Rotation élevée : plus d'ordres, donc plus de frais et une gestion plus exigeante."],
        "pour_qui": "Investisseur qui accepte de suivre une règle chaque mois et de sous-performer en marché haussier "
                    "en échange de baisses plus limitées.",
        "erreurs": ["Ignorer un signal de sortie « parce que le marché va remonter ».",
                    "Changer les paramètres après une mauvaise année (sur-ajustement)."],
    },
    "momentum_vt": {
        "titre": "Momentum + ciblage de volatilité (stratégie suivie par défaut)",
        "resume": "Le Momentum défensif, dont la part investie baisse quand le marché devient agité.",
        "principe": "La volatilité récente annonce souvent les turbulences. On vise une volatilité de 10 % par an : "
                    "si l'ETF choisi bouge deux fois plus, on n'en détient que la moitié et le reste attend en cash.",
        "regles": ["Même choix d'ETF que le Momentum défensif.",
                   "Exposition = 10 % ÷ volatilité réalisée (fenêtre de 3 mois), plafonnée à 100 %.",
                   "Le reste en cash (ou fonds monétaire), ajusté chaque mois."],
        "temps": "30 min / mois", "complexite": 4, "lignes": 1,
        "forces": ["Baisses nettement plus faibles que le Buy & Hold (environ −21 % au pire, contre −40 %).",
                   "Réduit l'exposition avant le cœur de certaines crises (Covid 2020)."],
        "faiblesses": ["Souvent partiellement en cash : rendement moyen le plus faible des stratégies d'actions.",
                       "Beaucoup de petits ajustements mensuels.",
                       "Le réglage actuel (fenêtre de 3 mois) est parmi les moins bons de sa grille : une fenêtre de "
                       "12 mois est plus robuste sur l'historique long (à tester en paper trading)."],
        "pour_qui": "Investisseur pour qui limiter les baisses compte plus que maximiser le rendement.",
        "erreurs": ["Compter sur elle pour battre le marché : son intérêt est la protection, pas la performance.",
                    "Laisser le cash dormir sur un compte non rémunéré."],
    },
    "inverse_vol": {
        "titre": "Inverse volatilité (actions)",
        "resume": "Répartir entre tous les ETF actions, avec plus de poids aux plus calmes.",
        "principe": "Chaque ETF reçoit un poids proportionnel à 1 ÷ sa volatilité sur 12 mois : le risque est mieux "
                    "réparti qu'en pondération égale, et on reste toujours investi.",
        "regles": ["Fin de mois : calculer la volatilité 12 mois de chaque ETF actions.",
                   "Poids = (1 ÷ volatilité), normalisés pour faire 100 %.",
                   "Orienter les versements vers les lignes sous leur poids cible."],
        "temps": "30 min / mois", "complexite": 2, "lignes": 6,
        "forces": ["Diversifiée sur toutes les zones de l'univers.", "Toujours investie : ne rate aucun rebond."],
        "faiblesses": ["Aucune protection en krach (baisse maximale proche du Buy & Hold).",
                       "Beaucoup de lignes : peu pratique avec un petit versement mensuel."],
        "pour_qui": "Investisseur qui veut diversifier au-delà du MSCI World sans règle de sortie.",
        "erreurs": ["Multiplier les petites lignes quand le versement est faible (frais et parts entières)."],
    },
    "static_80_20": {
        "titre": "80/20 actions Monde / obligations euro",
        "resume": "80 % MSCI World, 20 % obligations de la zone euro, rééquilibrés.",
        "principe": "Les obligations amortissent une partie des baisses d'actions, et le rééquilibrage force à "
                    "acheter ce qui a baissé.",
        "regles": ["Viser 80 % CW8.PA / WPEA.PA et 20 % OBLI.PA.",
                   "Diriger chaque versement vers la ligne en retard sur sa cible.",
                   "Rééquilibrer si un poids s'écarte de plus de 5 points."],
        "temps": "10 min / mois", "complexite": 1, "lignes": 2,
        "forces": ["Baisses un peu plus faibles que le 100 % actions.", "Simple et discipliné."],
        "faiblesses": ["Rendement de long terme plus faible.",
                       "En 2022, actions et obligations ont baissé ensemble : la protection n'est pas garantie.",
                       "Dans le PEA, OBLI.PA est devenu un fonds monétaire (€STR) vers 2024-11 : la poche « obligataire » est en pratique du cash ; aucun ETF obligataire éligible au PEA n'est suivi (voir `main.py universe`)."],
        "pour_qui": "Investisseur à horizon moyen ou qui dort mal avec 100 % d'actions.",
        "erreurs": ["Vendre les obligations quand elles baissent (elles servent de réserve pour racheter des actions)."],
    },
    "static_60_40": {
        "titre": "60/40 actions Monde / obligations euro",
        "resume": "Le portefeuille équilibré classique : 60 % actions, 40 % obligations.",
        "principe": "Même logique que le 80/20, avec davantage d'amortisseur : les baisses sont nettement plus "
                    "faibles, au prix d'un rendement plus bas.",
        "regles": ["Viser 60 % CW8.PA / WPEA.PA et 40 % OBLI.PA (ou fonds euros en assurance-vie).",
                   "Diriger les versements vers la ligne en retard ; rééquilibrer au-delà de 5 points d'écart."],
        "temps": "10 min / mois", "complexite": 1, "lignes": 2,
        "forces": ["La meilleure protection contre les baisses parmi les stratégies testées (verdict « forte »).",
                   "Adaptée à un horizon de 5 à 10 ans ou à un objectif précis."],
        "faiblesses": ["Rendement nettement plus faible sur 15 à 30 ans.",
                       "Les obligations peuvent souffrir quand les taux montent (2022).",
                       "Dans le PEA, OBLI.PA est devenu un fonds monétaire (€STR) vers 2024-11 : la poche « obligataire » est en pratique du cash ; aucun ETF obligataire éligible au PEA n'est suivi (voir `main.py universe`)."],
        "pour_qui": "Profil prudent ou projet à moyen terme.",
        "erreurs": ["Choisir le 60/40 avec un horizon de 20 ans ou plus sans en accepter le coût en rendement."],
    },
    "dual_momentum": {
        "titre": "Dual momentum (actions / obligations / cash)",
        "resume": "Détenir la meilleure action si elle bat les obligations et zéro ; sinon les obligations ou le cash.",
        "principe": "Deux filtres de momentum : relatif (la meilleure zone actions) et absolu (a-t-elle au moins "
                    "battu les obligations et le cash ?). En marché baissier, on se réfugie dans l'obligataire.",
        "regles": ["Fin de mois : momentum 12-1 de chaque ETF actions et de l'obligataire.",
                   "Si la meilleure action bat l'obligataire et zéro : 100 % sur elle.",
                   "Sinon, obligataire si son momentum est positif ; sinon cash."],
        "temps": "30 min / mois", "complexite": 3, "lignes": 1,
        "forces": ["Meilleur rendement annualisé observé sur l'historique long, avec des baisses limitées.",
                   "Une seule ligne à la fois : praticable avec un petit budget."],
        "faiblesses": ["Tout sur un seul actif : forte dépendance au bon timing.",
                       "Signal lent (12 mois) : entre et sort avec retard.",
                       "Surperformance « possible » mais non démontrée statistiquement.",
                       "Dans le PEA, OBLI.PA est devenu un fonds monétaire (€STR) vers 2024-11 : la poche « obligataire » est en pratique du cash ; aucun ETF obligataire éligible au PEA n'est suivi (voir `main.py universe`)."],
        "pour_qui": "Investisseur à l'aise avec une stratégie active et concentrée, qui suit la règle sans exception.",
        "erreurs": ["La juger sur une seule année : ses résultats sont très irréguliers d'une année à l'autre."],
    },
    "top3_trend": {
        "titre": "Top 3 équipondéré + filtre de tendance",
        "resume": "Les trois ETF les plus forts sur un an, à parts égales, seulement s'ils sont en tendance haussière.",
        "principe": "Même idée que le Momentum, mais répartie sur trois ETF pour réduire le risque de concentration ; "
                    "chaque ligne sous sa moyenne mobile 10 mois est remplacée par du cash.",
        "regles": ["Fin de mois : classer les ETF selon leur momentum 12-1.",
                   "Garder les trois premiers, un tiers chacun, s'ils cotent au-dessus de leur moyenne mobile 10 mois.",
                   "La part d'un ETF sous sa moyenne mobile reste en cash."],
        "temps": "45 min / mois", "complexite": 3, "lignes": 3,
        "forces": ["Meilleur Sharpe observé (0,93) et baisse maximale la plus faible (environ −17 %).",
                   "Plus diversifié que le Momentum à un ETF."],
        "faiblesses": ["Trois lignes : difficile avec moins de 300 € par mois (parts entières, frais).",
                       "Surperformance non démontrée après correction des tests multiples.",
                       "Rotation élevée."],
        "pour_qui": "Investisseur actif, avec un budget suffisant pour trois lignes, prêt à suivre la règle chaque mois.",
        "erreurs": ["Garder un ETF sorti du top 3 par attachement."],
    },
    "core_satellite": {
        "titre": "Cœur / satellite",
        "resume": "Un cœur en Buy & Hold (80 %) et un satellite (20 %) dans une stratégie active.",
        "principe": "Le cœur garantit de capter le marché ; le satellite permet d'appliquer une stratégie active sur "
                    "une petite part, sans mettre en jeu tout le portefeuille.",
        "regles": ["Cœur : 80 % en CW8.PA / WPEA.PA, jamais vendu.",
                   "Satellite : 20 % selon la stratégie choisie (Momentum + VT par défaut).",
                   "Versements dirigés vers la poche en retard sur sa cible."],
        "temps": "30 min / mois", "complexite": 2, "lignes": 2,
        "forces": ["Compromis : presque tout le rendement du marché, avec un peu d'amortisseur.",
                   "Idéal pour apprendre une stratégie active sans risquer tout le capital."],
        "faiblesses": ["Protection modeste (le cœur subit les krachs).", "Deux logiques à suivre."],
        "pour_qui": "Investisseur qui veut rester principalement passif tout en expérimentant.",
        "erreurs": ["Laisser le satellite grossir au-delà de sa part cible."],
    },
}

CARDS["allocation_fixe"] = {
    "titre": "Allocation fixe (définie dans ta politique)",
    "resume": "Une répartition fixe entre quelques ETF, par exemple 85 % Monde et 15 % émergents, jamais vendue.",
    "principe": "Même logique que le Buy & Hold, sur plusieurs ETF : les versements vont en priorité à la ligne en "
                "retard sur sa cible, ce qui rééquilibre sans vendre.",
    "regles": ["Répartition cible écrite dans config/policy.yaml > allocation_fixe.",
               "Chaque mois, acheter la ligne la plus en retard sur sa cible (le plan de versement le calcule).",
               "Grouper les petites lignes pour limiter les frais fixes ; ne rien vendre."],
    "temps": "5-10 min / mois", "complexite": 1, "lignes": 2,
    "forces": ["Simple, peu coûteuse, diversifiée au-delà du MSCI World (émergents).",
               "Aucune décision de marché à prendre."],
    "faiblesses": ["Subit toutes les baisses du marché.",
                   "Une ligne de plus que le Monde seul : frais fixes à surveiller avec un petit versement."],
    "pour_qui": "Investisseur passif qui veut choisir lui-même sa répartition géographique.",
    "erreurs": ["Changer la répartition après une bonne ou une mauvaise année d'une zone."],
}

WINDOW_ORDER = ("Crise financière 2008-09", "Crise de la dette euro 2011", "Chine / pétrole 2015-16", "T4 2018",
                "Covid 2020", "Inflation et taux 2022")


def _load(path: str | Path) -> dict | None:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def card_view(name: str, robustness: dict | None = None, stress: dict | None = None) -> dict:
    """Fiche complète : texte + mesures (robustesse, crises) quand disponibles."""
    if name not in CARDS:
        raise ValueError(f"Pas de fiche pour la stratégie {name}.")
    view = {"key": name, **CARDS[name], "mesures": None, "crises": []}
    item = (robustness or {}).get("strategies", {}).get(name)
    if item:
        view["mesures"] = {
            "label": item["label"], "stats": item["stats"], "fiabilite": item["verdict"], "score": item["score"],
            "surperformance": item.get("edge"), "protection": item.get("protection"),
            "criteres": item["criteria"], "sous_periodes": item["subperiods"], "grille": item.get("grid"),
            "periode": f"{robustness['start']} → {robustness['end']}",  # type: ignore[index]
        }
    if stress:
        rows = [w for w in stress.get("windows", []) if w["stratégie"] == name]
        bench = {w["fenêtre"]: w for w in stress.get("windows", []) if w["stratégie"] == "benchmark"}
        for row in rows:
            ref = bench.get(row["fenêtre"], {})
            view["crises"].append({"fenêtre": row["fenêtre"], "actif": row["actif"], "rendement": row["rendement"],
                                   "drawdown_max": row["drawdown_max"], "drawdown_benchmark": ref.get("drawdown_max"),
                                   "mois_recuperation": row["mois_recuperation"],
                                   "part_synthetique": row["part_synthetique"]})
    return view


def _pct(value, digits: int = 0) -> str:
    return "n/a" if value is None else f"{value:.{digits}%}"


def card_markdown(view: dict) -> list[str]:
    lines = [f"## {view['titre']}", "", f"_{view['resume']}_", "",
             f"**Temps :** {view['temps']} · **complexité :** {view['complexite']}/4 · **lignes détenues :** "
             f"{view['lignes']}", "", f"**Principe.** {view['principe']}", "", "**Règles exactes**", ""]
    lines += [f"{i}. {rule}" for i, rule in enumerate(view["regles"], 1)]
    lines += ["", "**Forces**", ""] + [f"- {x}" for x in view["forces"]]
    lines += ["", "**Faiblesses**", ""] + [f"- {x}" for x in view["faiblesses"]]
    lines += ["", f"**Pour qui ?** {view['pour_qui']}", "", "**Erreurs fréquentes**", ""]
    lines += [f"- {x}" for x in view["erreurs"]]
    m = view["mesures"]
    if m:
        s = m["stats"]
        sharpe = "n/a" if s["sharpe"] is None else f"{s['sharpe']:.2f}"
        lines += ["",f"**Mesures sur historique long ({m['periode']}, partiellement synthétique)**", "",
                  "| CAGR | Volatilité | Sharpe | Pire baisse | Pire année | Meilleure année | Pire 5 ans (/an) | "
                  "Part investie | Rotation / an |",
                  "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                  f"| {_pct(s['cagr'], 1)} | {_pct(s['volatility'], 1)} | "
                  f"{sharpe} | {_pct(s['max_drawdown'])} | "
                  f"{_pct(s['worst_year'])} | {_pct(s['best_year'])} | {_pct(s.get('worst_5y_cagr'), 1)} | "
                  f"{_pct(s.get('avg_exposure'))} | {_pct(s.get('turnover_per_year'))} |", "",
                  f"Fiabilité **{m['fiabilite']}** ({m['score']:.0%} des critères)"
                  + (f" · surperformance **{m['surperformance']['verdict']}** · protection "
                     f"**{m['protection']['verdict']}**" if m["surperformance"] else " · référence de comparaison")
                  + "."]
    if view["crises"]:
        lines += ["", "**Dans les crises** (pire baisse pendant la fenêtre, Buy & Hold entre parenthèses)", ""]
        for c in view["crises"]:
            if not c["actif"]:
                lines.append(f"- {c['fenêtre']} : pas encore active.")
                continue
            lines.append(f"- {c['fenêtre']} : {_pct(c['drawdown_max'])} ({_pct(c['drawdown_benchmark'])})"
                         + (" — données synthétiques" if (c["part_synthetique"] or 0) > 0.5 else ""))
    return lines + [""]


def generate_cards_report(output_path: str | Path, robustness_path: str | Path,
                          stress_path: str | Path) -> Path:
    robustness, stress = _load(robustness_path), _load(stress_path)
    lines = ["# Fiches des stratégies", "", f"Date de génération : {date.today().isoformat()}", "",
             "Chaque fiche décrit le mécanisme d'une stratégie du registre et ses résultats mesurés (robustesse sur "
             "historique long, crises). **Ce ne sont pas des recommandations** : le choix de la stratégie suivie "
             "reste une décision humaine (`config/policy.yaml`). Aucun ordre n'est passé.", ""]
    if robustness is None:
        lines += ["> Mesures absentes : lancer `python main.py robustness` puis `python main.py stress`.", ""]
    lines += ["| Stratégie | Temps | Complexité | Lignes | Fiabilité | Surperformance | Protection |",
              "| --- | --- | ---: | ---: | --- | --- | --- |"]
    views = [card_view(name, robustness, stress) for name in CARDS]
    for v in views:
        m = v["mesures"] or {}
        edge = (m.get("surperformance") or {}).get("verdict", "référence" if v["key"] == "benchmark" else "n/a")
        protection = (m.get("protection") or {}).get("verdict", "référence" if v["key"] == "benchmark" else "n/a")
        lines.append(f"| {v['titre']} | {v['temps']} | {v['complexite']}/4 | {v['lignes']} | "
                     f"{m.get('fiabilite', 'n/a')} | {edge} | {protection} |")
    lines.append("")
    for v in views:
        lines += card_markdown(v)
    lines += ["_Mesures indicatives : données partiellement synthétiques avant la cotation des ETF PEA ; les "
              "performances passées ne préjugent pas des performances futures._", ""]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path

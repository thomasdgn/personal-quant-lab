# Format des résultats JSON des études

Les études écrivent un JSON à côté de leur rapport Markdown. Depuis la v6, tous
partagent un bloc `meta` commun (`src/results.py`). Les clés historiques de
chaque fichier sont conservées : les changements sont **additifs uniquement**.
Le snapshot mensuel a son propre contrat : [snapshot_schema.md](snapshot_schema.md).

## Bloc commun `meta` (schéma 1.0)

| Clé | Type | Sens |
| --- | --- | --- |
| `kind` | `research` \| `robustness` \| `stress` \| `plans` | Type d'étude |
| `schema_version` | texte | Version du format commun (`1.0`) |
| `generated` | date ISO | Date de génération |
| `data_window` | `{start, end}` ou `null` | Fenêtre des données utilisées |
| `synthetic_share` | nombre ou `null` | Part moyenne des prix synthétiques (proxys), 0 à 1 |
| `notes` | liste de textes | Avertissements sur les données ou les hypothèses |

Conventions de valeurs : JSON strict (aucun `NaN`) ; NaN et infinis deviennent
`null`, les types numpy des types JSON, les dates des chaînes ISO 8601.

## Fichiers

| Fichier | `kind` | Commande | Clés principales |
| --- | --- | --- | --- |
| `reports/research/strategy_research_report.json` (et `_long`) | `research` | `main.py research [--long]` | `strategies`, `walk_forward`, `rank_correlation`, `conclusion` |
| `reports/research/robustness_report.json` | `robustness` | `main.py robustness` | `strategies` (verdicts, critères, grilles), `meta_selection`, `series`, `conclusion` |
| `reports/research/stress_report.json` | `stress` | `main.py stress` | `windows`, `outcomes`, `labels`, `conclusion` |
| `reports/plans/plans_report.json` (personnel) | `plans` | `main.py plans` | `profile`, `hypotheses`, `scenario`, `sensitivity` (plan × scénario : p10 / p50 / p90), `results` (simulation, vrai passé, `model_check`, adéquation, relecture), `ranking` |

Lecture recommandée : `src.results.read_results_json(path, kind)`, qui vérifie le
type quand le bloc `meta` est présent et accepte les anciens fichiers qui ne
l'ont pas.

## Moteur de calcul commun

Recherche, robustesse, stress et plans calculent leurs rendements par
`src/engine.py` : poids exécutés (décalés d'un mois), frais par côté traité, cash
explicite, période de chauffe exclue (`active_returns`). Le pipeline mensuel
utilise la même fonction de backtest (`src/backtest.py`).

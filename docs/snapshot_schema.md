# Schéma du snapshot JSON mensuel

Fichier : `reports/monthly/YYYY-MM-report.json`, produit par `python main.py monthly-report`
ou `python main.py run-month`. C'est le **contrat de données** du laboratoire : le tableau de
bord (`app/dashboard.py`), le journal de paper trading et une future application ne lisent
que ce fichier, sans rien recalculer.

## Règles générales

- JSON standard UTF-8 : jamais de `NaN` ni d'`Infinity` (valeurs non finies → `null`).
- Dates au format ISO `YYYY-MM-DD` ; horodatages `YYYY-MM-DDTHH:MM:SS`.
- Poids exprimés en fraction (0,42 = 42 %) ; chaque allocation somme à 1 avec une clé `CASH`
  explicite.
- **Versionnement** : `schema_version` passe en version mineure (`1.0` → `1.1`) pour tout
  ajout de champ ; les champs existants ne changent ni de nom ni de sens. Un changement
  incompatible imposerait une version majeure (`2.0`).

## Historique des versions

| Version | Changements |
| ------- | ----------- |
| 1.0 | Version initiale (Projet 4). |
| 1.1 | Ajouts : `figures` ; dans `universe` : `roles`, `cash_proxy`, `defensive_as_candidates`, `excluded_by_role`, `missing_from_data`, `ignored_not_configured` ; nouveaux codes d'alerte `UNIVERSE_MISMATCH` et `UNIVERSE_EXTRA`. |
| 1.2 | Ajouts : `data_quality.anomalies` (liste `{ticker, type, date, detail}`, types `JUMP` / `STALE` / `GAP` sur les 45 derniers jours) ; code d'alerte `DATA_ANOMALY` ; `series` (séries mensuelles pour les graphiques interactifs). |
| 1.4 | Ajouts dans `policy` : `plan` (plan suivi, `plan_suivi` de la politique) et `crash_rule` (`text`, `threshold`, `current_drawdown`, `triggered`) ; nouvelle stratégie `allocation_fixe` dans `strategies` quand la politique en définit une ; alerte `CRASH_RULE` (WARNING) quand la baisse de la stratégie suivie dépasse le seuil. |
| 1.3 | Ajouts : `policy` (stratégie suivie selon `config/policy.yaml`, allocation cible, limite de drawdown) et `strategies` (toutes les stratégies du registre : allocation cible, exposition, métriques) ; `series.exposure` / `held` suivent la stratégie de la politique. |

## Champs de premier niveau

| Champ | Type | Description |
| ----- | ---- | ----------- |
| `figures` | objet | `{equity, drawdown, allocation, volatility}` → chemin PNG **relatif au dossier du snapshot** (ex. `figures/2026-09-equity.png`). Vide si les graphiques n'ont pas été générés. |
| `series` | liste | (1.2) Une ligne par fin de mois : `date`, `benchmark_equity`, `benchmark_drawdown`, `momentum_equity`, `momentum_drawdown`, `momentum_vt_equity`, `momentum_vt_drawdown` (si VT actif), `exposure` (exposition investie de la stratégie suivie), `held` (actifs détenus). |
| `schema_version` | texte | Version du schéma (voir ci-dessus). |
| `partial_month` | texte ou `null` | Mois en cours incomplet exclu du signal (`YYYY-MM`). |
| `freshness_reference` | date | Date de référence pour l'ancienneté des données. |
| `metadata` | objet | Voir ci-dessous. |
| `data_quality` | objet | Qualité des données. |
| `universe` | objet | Univers retenu et rôles. |
| `benchmark` | stratégie | Buy & Hold du benchmark. |
| `momentum_strategy` | stratégie | Momentum défensif. |
| `volatility_targeted_strategy` | stratégie | Momentum + Volatility Targeting (`enabled: false` et `status: DISABLED` si désactivé). |
| `allocation_comparison` | objet | Allocations cibles comparées, expositions investies, écart Momentum − VT. |
| `risk` | objet | Volatilité réalisée et cible, drawdowns, exposition et cash VT. |
| `policy` | objet | (1.3) `followed`, `label`, `target_weights`, `invested_exposure`, `max_drawdown_limit`, `historical_max_drawdown`, `drawdown_within_limit`, `core_weight` / `satellite` (cœur/satellite), `rebalancing`, `band_tolerance_pct` ; (1.4) `plan`, `crash_rule` (`null` sans règle). C'est **l'allocation proposée** du mois. |
| `strategies` | objet | (1.3) Par nom du registre (`benchmark`, `momentum`, `momentum_vt`, `inverse_vol`, `static_80_20`, `static_60_40`, `dual_momentum`, `top3_trend`, `core_satellite`, (1.4) `allocation_fixe`) : `label`, `description`, `target_weights`, `executed_weights`, `invested_exposure`, `cash_weight`, `selected_assets`, `cagr`, `annualized_volatility`, `sharpe`, `max_drawdown`, `current_drawdown`, `turnover`, `cumulative_cost`. |
| `alerts` | liste | Alertes (voir ci-dessous). |
| `manual_decision` | objet | Toujours `status: PENDING` à la génération ; la décision se prend dans le journal de paper trading. |
| `previous_comparison` | objet ou `null` | Variations par rapport au snapshot précédent trouvé sur disque. |

### `metadata`

`schema_version`, `report_month` (`YYYY-MM`), `report_date` (date d'arrêté), `signal_date`
(dernier mois civil complet, **date du signal officiel**), `last_observation` (dernière séance
utilisée, jamais postérieure à `report_date`), `generated_at`, `freshness_reference`,
`history_start`, `history_end`, `reference_currency` (`EUR`), `data_mode` (`local` ou
`refreshed`), `pipeline_status` (`OK`, `OK_WITH_WARNINGS`, `CRITICAL`).

### `data_quality`

`requested_assets`, `n_requested`, `kept_assets`, `n_kept`, `excluded_assets`
(`{ticker: raison}`), `last_date_per_asset`, `missing_values_monthly`, `data_age_days`,
`partial_month`, `anomalies` (1.2), `warnings` (messages des alertes de données non `INFO`).

### `universe`

| Champ | Description |
| ----- | ----------- |
| `benchmark`, `assets`, `n_assets` | Benchmark et actifs classables retenus. |
| `period_start`, `period_end`, `n_months` | Période mensuelle utilisée. |
| `roles` | `{ticker: candidate / defensive / cash_proxy}` pour les tickers présents (1.1). |
| `cash_proxy` | Ticker dont le rendement rémunère la poche cash, ou `null` (1.1). |
| `defensive_as_candidates` | L'obligataire est-il classé avec les actions (1.1). |
| `excluded_by_role` | Actifs `defensive` écartés par la configuration (1.1). |
| `missing_from_data` | Tickers configurés sans prix locaux (1.1). |
| `ignored_not_configured` | Tickers présents dans les prix mais absents d'`assets.yaml` (1.1). |

### Objet « stratégie »

`name`, `description`, `selected_assets`, `target_weights` (allocation **cible** à appliquer
le mois suivant), `executed_weights` (allocation détenue pendant le mois du signal),
`cash_weight`, `invested_exposure`, `momentum` et `trend_filter` (par ticker),
`realized_volatility`, `target_volatility`, `cagr`, `annualized_volatility`, `sharpe`,
`max_drawdown`, `recent_return`, `theoretical_capital`, `turnover` (moyen), `cumulative_cost`,
`signal_date`, `enabled`, `status` (`ACTIVE` ou `DISABLED`).

### Alerte

`level` (`INFO`, `WARNING`, `CRITICAL`), `code`, `title`, `message`, `timestamp`, `context`
(détails libres). Codes existants : `STALE_DATA`, `DATA_NOT_REFRESHED`, `UNIVERSE_MISMATCH`,
`UNIVERSE_EXTRA`, `ASSET_EXCLUDED`, `INSUFFICIENT_HISTORY`, `PARTIAL_MONTH`, `FULL_CASH`,
`REDUCED_EXPOSURE`, `HIGH_VOLATILITY`, `HIGH_DRAWDOWN`, `MOMENTUM_VT_DIVERGENCE`,
`HIGH_TURNOVER`, `HIGH_COST`, `METRIC_UNAVAILABLE`, `DATA_ANOMALY` (1.2).

## Exemple (extrait)

```json
{
  "figures": {"equity": "figures/2026-09-equity.png"},
  "schema_version": "1.4",
  "metadata": {"report_month": "2026-09", "signal_date": "2026-08-31", "pipeline_status": "OK_WITH_WARNINGS"},
  "universe": {"benchmark": "CW8.PA", "cash_proxy": "CSH2.PA", "roles": {"OBLI.PA": "defensive"}},
  "volatility_targeted_strategy": {"target_weights": {"PAASI.PA": 0.42, "CASH": 0.58}},
  "manual_decision": {"status": "PENDING"}
}
```

# Détection ML des régimes de marché

Module expérimental de contexte de marché, destiné au paper trading uniquement.

## Dataset

- Période : 2016-01-31 → 2026-05-31
- Observations : 125
- Features : momentum_1m, momentum_3m, momentum_6m, momentum_12m, vol_3m, vol_6m, vol_12m, drawdown_actuel, above_ma_12m
- Splits : train=69, validation=21, test=29
- Distribution cible : risk-off=32, risk-on=93
- Cible : 1 si le rendement CW8.PA de M à M+3 est strictement positif, 0 sinon.

## Résultats ML

### Logistic Regression

| Split | Accuracy | Precision off/on | Recall off/on | F1 off/on | ROC-AUC | Baseline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| validation | 0.524 | 0.000 / 0.524 | 0.000 / 1.000 | 0.000 / 0.688 | 0.491 | 0.524 |
| test | 0.759 | 0.200 / 0.875 | 0.250 / 0.840 | 0.222 / 0.857 | 0.650 | 0.862 |

Matrice de confusion validation `[[TN, FP], [FN, TP]]` : `[[0, 10], [0, 11]]`.
Matrice de confusion test `[[TN, FP], [FN, TP]]` : `[[1, 3], [4, 21]]`.
Sur le test, ce modèle ne bat pas la baseline majoritaire.

### Random Forest

| Split | Accuracy | Precision off/on | Recall off/on | F1 off/on | ROC-AUC | Baseline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| validation | 0.524 | 0.000 / 0.524 | 0.000 / 1.000 | 0.000 / 0.688 | 0.482 | 0.524 |
| test | 0.586 | 0.000 / 0.810 | 0.000 / 0.680 | 0.000 / 0.739 | 0.510 | 0.862 |

Matrice de confusion validation `[[TN, FP], [FN, TP]]` : `[[0, 10], [0, 11]]`.
Matrice de confusion test `[[TN, FP], [FN, TP]]` : `[[0, 4], [8, 17]]`.
Sur le test, ce modèle ne bat pas la baseline majoritaire.

## Importance des features (Random Forest)

| Rang | Feature | Importance |
| ---: | --- | ---: |
| 1 | vol_12m | 0.2267 |
| 2 | vol_3m | 0.2060 |
| 3 | momentum_12m | 0.1399 |
| 4 | vol_6m | 0.1094 |
| 5 | momentum_1m | 0.1088 |
| 6 | momentum_6m | 0.0924 |
| 7 | drawdown_actuel | 0.0646 |
| 8 | momentum_3m | 0.0518 |
| 9 | above_ma_12m | 0.0004 |

## Backtest financier — split fixe, période de test (sans frais)

| Stratégie | CAGR | Sharpe | Max drawdown |
| --- | ---: | ---: | ---: |
| Logistic Regression | 13.41% | 1.099 | -14.38% |
| Random Forest | 8.48% | 0.777 | -13.84% |
| Buy & Hold CW8.PA | 16.97% | 1.313 | -13.84% |

Le seuil de classification est fixé à 0,5 et n'a pas été optimisé sur le backtest.
Ce backtest à split fixe n'inclut pas de coûts de transaction ; voir la section walk-forward.

## Walk-forward (fenêtre expansive, réentraînement mensuel)

- Période évaluée : 2021-03-31 → 2026-05-31 (63 mois à cible connue).
- Entraînement : toutes les cibles entièrement connues à la date de décision (purge stricte), minimum 60 observations.

| Modèle | Accuracy | ROC-AUC | Recall risk-off | Baseline |
| --- | ---: | ---: | ---: | ---: |
| Logistic Regression | 0.492 | 0.230 | 0.000 | 0.730 |
| Random Forest | 0.556 | 0.178 | 0.000 | 0.730 |

## Comparaison financière avec frais (0.10% par unité de turnover)

Mêmes mois pour toutes les stratégies : 2021-04-30 → 2026-08-31 (65 mois). Exposition ML : >60 % → 100 %, 50–60 % → 60 %, 40–50 % → 30 %, ≤40 % → cash ; décidée fin de mois M, appliquée en M+1.

| Stratégie | CAGR | Sharpe | Max drawdown | Exposition moy. | Frais cumulés |
| --- | ---: | ---: | ---: | ---: | ---: |
| Buy & Hold CW8.PA | 12.65% | 1.002 | -14.15% | 100% | 0.00% |
| ML (logistique) sur CW8.PA | 5.92% | 0.557 | -14.18% | 74% | 0.64% |
| ML (logistique) x Momentum | 4.87% | 0.375 | -23.91% | 69% | 2.28% |
| Momentum défensif | 9.95% | 0.616 | -24.32% | 95% | 2.50% |
| Momentum + VT | 5.52% | 0.482 | -20.95% | 68% | 2.57% |

## Verdict (règle fixe : Sharpe supérieur ET drawdown non dégradé)

- ML (logistique) sur CW8.PA vs Buy & Hold CW8.PA : **non retenu** (Sharpe 0.56 vs 1.00, max DD -14.2% vs -14.1%).
- ML (logistique) x Momentum vs Momentum défensif : **non retenu** (Sharpe 0.38 vs 0.62, max DD -23.9% vs -24.3%).

Conclusion : l'overlay ML n'améliore pas le profil de risque hors échantillon. Il reste un indicateur de contexte, sans effet sur l'allocation proposée.

## Régime courant (information, pas une recommandation)

- Date du signal : 2026-08-31
- Probabilité favorable (logistique) : 60.5%
- Probabilité favorable (random forest) : 59.4%
- Exposition indicative (paliers, logistique) : 100%

## Limites

- Nombre d'observations faible (~130 mois) : risque de surapprentissage.
- Stationnarité non garantie des régimes de marché.
- Historique court et majoritairement haussier : peu de régimes défavorables pour apprendre.
- Features uniquement issues des prix du benchmark (aucune donnée macro).
- Paliers d'exposition fixés a priori (guide), non optimisés.
- Les résultats passés ne préjugent pas des résultats futurs.
- Ce module est expérimental et ne doit pas déclencher d'ordres réels.

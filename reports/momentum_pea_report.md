# Rapport — Projet 2 : Stratégie ETF Momentum défensive PEA

> Document de recherche **éducatif**. Ce n'est pas un conseil d'investissement.
> Aucun ordre n'est exécuté. Les résultats dépendent des données Yahoo Finance
> au moment de l'exécution (backtest daté du 7 juillet 2026).

Notebook associé : [`notebooks/03_momentum_pea.ipynb`](../notebooks/03_momentum_pea.ipynb).
Code : `src/features.py`, `src/signals.py`, `src/backtest.py`.

## 1. Objectif

Construire et backtester une stratégie mensuelle qui sélectionne le ou les ETF
les plus « forts » (momentum), tout en restant en cash lorsqu'ils passent sous
leur tendance longue, puis la comparer honnêtement à un Buy & Hold.

## 2. Hypothèse financière

Les actifs ayant bien performé sur ~12 mois tendent à continuer à court/moyen
terme, **sauf** lorsque leur tendance longue est cassée (prix sous sa moyenne
mobile). Le filtre de tendance vise à éviter les marchés baissiers durables.

## 3. Univers utilisé

Univers lu dans `config/assets.yaml` (catégorie actions, tickers `.PA`) ; les
cryptos sont exclues de ce projet.

| Ticker   | Première cotation | Retenu | Raison |
| -------- | ----------------- | ------ | ------ |
| CW8.PA   | 2015-01-02        | Oui    | ETF MSCI World, historique complet (benchmark) |
| ESE.PA   | 2015-01-02        | Oui    | ETF S&P 500, historique complet |
| EWLD.PA  | 2024-03-15        | **Non** | ~29 mois d'historique : insuffisant pour un momentum 12 mois + MA 10 |

Règle d'inclusion codée : au moins `lookback + MA + 12` mois valides. Les tickers
sont un **univers expérimental** à revérifier chez un courtier avant tout usage
réel (l'éligibilité PEA n'est pas garantie ici).

## 4. Qualité des données

Période commune retenue : **2015-01-02 → 2026-07-07** (139 prix mensuels).
CW8.PA : 0 NaN ; ESE.PA : 2 NaN quotidiens négligeables. Passage en mensuel via
le **dernier prix réellement coté** du mois (pas de moyenne, pas de forward-fill
silencieux). Le dernier mois (juillet 2026) est **partiel** (arrêté au 7).

## 5. Définition mathématique du momentum

```text
momentum(t) = prix(t - skip) / prix(t - lookback) - 1
```

Momentum 12-1 : `prix(t-1) / prix(t-12) - 1`. On saute le dernier mois (`skip=1`)
pour atténuer le retournement court terme. On n'utilise **pas** l'approximation
`pct_change(12) - pct_change(1)` (test dédié à l'appui).

## 6. Filtre de tendance

Moyenne mobile simple 10 mois (`min_periods=10`, aucune donnée future). Un actif
est **éligible** si son momentum est disponible **et** `prix > MA`. Lorsque la MA
n'est pas encore disponible, l'actif est non éligible.

## 7. Décalage temporel (anti look-ahead)

Le signal calculé fin de mois M est **exécuté au mois M+1**
(`lag_weights_for_execution`, décalage explicite d'une période ; les premières
périodes sont en cash). Le backtest applique `poids_exécutés(t) × rendement(t)`
avec `rendement(t) = prix(t)/prix(t-1) - 1` : le poids de `t` n'utilise jamais le
prix de `t`. Un test construit un scénario où une variante « même mois » (triche)
surperforme la version correcte — preuve que le moteur ne regarde pas le futur
par accident.

## 8. Convention de frais et de turnover

```text
turnover(t) = 0.5 × Σ_j | w_j(t) - w_j(t-1) |   (actifs + cash)
coût(t)     = frais × turnover(t)               (retranché du rendement)
```

Cette convention mesure la fraction du portefeuille **réellement remplacée** :
`100 % cash → 100 % ETF` = 100 % ; `100 % ETF A → 100 % ETF B` = 100 %
(remplacement complet, pas un double comptage). Frais testés : 0 ; 0,10 ;
0,20 ; 0,30 %.

## 9. Stratégies comparées

1. Buy & Hold du benchmark (CW8.PA) ;
2. Momentum 12-1 **sans** filtre de tendance ;
3. Momentum 12-1 **+** MA 10 mois (stratégie principale, défensive) ;
4. Momentum 6-1 + MA 10 mois ;
5. Momentum 12-1 + MA 10 mois, **top 2** équipondéré.

## 10. Tableau des métriques

Période 2015→2026, mensuel, frais 0,10 %, capital initial 10 000 €.

| Stratégie | CAGR | Vol. | Sharpe | Max DD | Capital final | Mois cash | Turnover moy. |
| --------- | ----:| ----:| ------:| ------:| -------------:| ---------:| -------------:|
| Buy & Hold CW8.PA        | 11,2 % | 13,2 % | 0,88 | −18,6 % | 34 053 € | 0  | 0,00 |
| Mom 12-1 (sans tendance) | 13,1 % | 13,2 % | 1,00 | −17,6 % | 41 757 € | 13 | 0,11 |
| **Mom 12-1 + MA10**      | 8,8 %  | 10,9 % | 0,83 | −16,6 % | 26 456 € | 33 | 0,22 |
| Mom 6-1 + MA10           | 7,6 %  | 11,2 % | 0,71 | −16,6 % | 23 287 € | 30 | 0,24 |
| Mom 12-1 + MA10 (top 2)  | 7,3 %  | 10,0 % | 0,76 | −13,7 % | 22 631 € | 33 | 0,14 |

## 11. Résultats de robustesse

Grille `lookback ∈ {3,6,12} × skip ∈ {0,1} × MA ∈ {6,10,12} × top_n ∈ {1,2} ×
frais ∈ {0 ; 0,1 ; 0,2 ; 0,3 %}` (voir notebook). Enseignements :

- **Sensibilité aux frais** (CAGR moyen sur toutes les configs) : 8,02 % (0 %) →
  7,75 % (0,1 %) → 7,48 % (0,2 %) → 7,22 % (0,3 %). Les frais dégradent
  monotonement la performance : le turnover compte.
- Les lookbacks courts (3-6 mois) sont plus instables et plus coûteux (turnover
  plus élevé) sans gain de rendement clair.
- Aucune combinaison ne domine simultanément sur rendement **et** drawdown : il
  n'y a pas de « paramètre magique ».

## 12. Drawdowns

Le filtre de tendance réduit le drawdown maximal (de −18,6 % pour le Buy & Hold à
−16,6 % pour la version défensive, et −13,7 % pour la version top 2), au prix
d'un rendement plus faible sur cette période haussière.

## 13. Turnover

Turnover mensuel moyen ~0,11 à 0,25 selon les variantes. Il augmente avec les
lookbacks courts et diminue avec le top 2 (diversification plus stable). Chaque
rotation d'actif coûte `frais × turnover`.

## 14. Limites

- Univers minuscule (2 ETF) et **fortement corrélés** (World vs S&P 500) : peu de
  vraie diversification, momentum relatif peu discriminant.
- Historique court (≈11,5 ans, un seul grand régime globalement haussier).
- Dernier mois partiel non retraité.
- Backtest total-return approximatif (prix ajustés yfinance), sans fiscalité
  réelle, sans slippage, sans impact de marché.

## 15. Risques

- **Biais de survivance** possible (tickers choisis a posteriori).
- **yfinance** : source non officielle, révisions/absences possibles.
- **Éligibilité PEA** susceptible de changer : à revérifier chez le courtier.
- **Sur-optimisation** : la grille sert à étudier la stabilité, pas à choisir le
  meilleur rendement.
- Les performances passées ne préjugent pas des performances futures.

## 16. Conclusion

Sur cet échantillon et ce mini-univers, le **Momentum pur** (sans filtre) a battu
le Buy & Hold (CAGR 13,1 % vs 11,2 %, Sharpe 1,00 vs 0,88), mais en restant
quasiment tout le temps investi. La **version défensive** (momentum + MA10)
**n'a pas battu** le Buy & Hold en rendement (8,8 % vs 11,2 %) ; elle a seulement
réduit modérément la volatilité et le drawdown. C'est un résultat honnête et
attendu dans un marché majoritairement haussier : l'assurance (passage en cash)
a un coût. La logique est correcte, testée et sans look-ahead, mais l'avantage
économique n'est **pas** démontré de façon robuste sur ces données.

## 17. Décision : paper trading ?

**Non — pas de passage en argent réel.** Conditions non remplies : univers trop
étroit, historique trop court, avantage non robuste après frais. Prochaines
étapes de recherche recommandées avant toute décision :

- élargir l'univers PEA (ETF réellement éligibles, secteurs/régions plus variés
  et moins corrélés) ;
- allonger l'historique et tester hors échantillon ;
- tenir un journal de décision.

La décision d'investissement reste **manuelle**. Le passage éventuel en paper
trading n'interviendra qu'après ces vérifications.

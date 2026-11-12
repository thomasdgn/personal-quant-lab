# Robustesse des stratégies (historique long)

Date de génération : 2026-09-25

Fenêtre commune : 2008-02-29 → 2026-08-31 (223 mois). **Part synthétique moyenne des prix : 50%** (proxys avant la cotation des ETF PEA). Frais de 0.10% par unité de turnover. Aucun ordre, aucune stratégie modifiée.

## Verdicts

| Stratégie | Fiabilité | Score | Surperformance vs B&H | Protection | CAGR | Sharpe | Max DD | PSR | DSR |
| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Buy & Hold CW8.PA | **robuste** | 100% | référence | référence | 9.9% | 0.78 | -39.1% | 100% | 98% |
| Momentum défensif | **robuste** | 100% | non démontrée | moyenne | 10.0% | 0.73 | -24.3% | 100% | 97% |
| Momentum + Volatility Targeting **(suivie)** | **robuste** | 100% | non démontrée | moyenne | 7.2% | 0.66 | -20.9% | 100% | 94% |
| Inverse volatilité (actions) | **robuste** | 100% | non démontrée | faible | 10.2% | 0.78 | -40.0% | 100% | 98% |
| 80/20 CW8.PA / OBLI.PA | **robuste** | 100% | possible | moyenne | 8.3% | 0.79 | -32.4% | 100% | 98% |
| 60/40 CW8.PA / OBLI.PA | **robuste** | 100% | possible | forte | 6.6% | 0.79 | -25.2% | 100% | 98% |
| Dual momentum (actions / obligataire / cash) | **robuste** | 86% | possible | moyenne | 13.0% | 0.86 | -20.1% | 100% | 99% |
| Top 3 équipondéré + tendance | **robuste** | 100% | non démontrée | moyenne | 10.7% | 0.93 | -16.6% | 100% | 100% |
| Cœur / satellite (80% CW8.PA + 20% momentum_vt) | **robuste** | 100% | possible | moyenne | 9.4% | 0.80 | -34.2% | 100% | 98% |

## Conclusion

- Fiabilité « robuste » : Buy & Hold CW8.PA, Momentum défensif, Momentum + Volatility Targeting, Inverse volatilité (actions), 80/20 CW8.PA / OBLI.PA, 60/40 CW8.PA / OBLI.PA, Dual momentum (actions / obligataire / cash), Top 3 équipondéré + tendance, Cœur / satellite (80% CW8.PA + 20% momentum_vt) ; « fragile » : aucune.
- Surperformance démontrée face au Buy & Hold (après correction des tests multiples) : aucune stratégie.
- Protection forte contre les baisses : 60/40 CW8.PA / OBLI.PA.
- Choisir chaque année la stratégie qui a le mieux marché (méta-sélection) donne un Sharpe hors échantillon de 0.89, contre 0.99 pour le Buy & Hold : courir après la meilleure stratégie récente n'aide pas.
- 81 variantes évaluées au total : le Sharpe dégonflé corrige ce nombre d'essais.
- Aucun réglage n'est modifié automatiquement ; un réglage « plateau » différent du défaut est une piste à suivre en paper trading, pas une consigne.

## Détail des critères

### Buy & Hold CW8.PA — robuste

| Critère | Résultat | Détail |
| --- | --- | --- |
| Sharpe réellement positif (PSR ≥ 95 %) | oui | PSR 100% |
| Résiste aux tests multiples (Sharpe dégonflé ≥ 90 %) | oui | DSR 98% |
| Sharpe positif dans chaque sous-période de 5 ans | oui | 4/4 sous-périodes |
| Aucune fenêtre de 5 ans perdante (CAGR ≥ 0) | oui | pire fenêtre +2.2% par an |
| Frais × 3 : Sharpe en baisse de moins de 0,10 | oui | −0.00 |

| Sous-période | CAGR | Sharpe | Max DD | Part synthétique |
| --- | ---: | ---: | ---: | ---: |
| 2008-2012 | 1.7% | 0.18 | -39.1% | 100% |
| 2013-2017 | 14.0% | 1.33 | -12.2% | 74% |
| 2018-2022 | 8.5% | 0.62 | -18.6% | 13% |
| 2023-auj. | 18.1% | 1.52 | -13.8% | 0% |

### Momentum défensif — robuste

- Surperformance **non démontrée** : meilleur Sharpe que le Buy & Hold dans 16% des fenêtres de 5 ans ; probabilité d'un surplus de rendement réel 54%, 5% après correction des tests multiples ; surplus médian -1.4% par an.
- Protection **moyenne** : baisse maximale -24% contre -39% pour le Buy & Hold ; baisse moins profonde dans 40% des fenêtres de 5 ans.

| Critère | Résultat | Détail |
| --- | --- | --- |
| Sharpe réellement positif (PSR ≥ 95 %) | oui | PSR 100% |
| Résiste aux tests multiples (Sharpe dégonflé ≥ 90 %) | oui | DSR 97% |
| Sharpe positif dans chaque sous-période de 5 ans | oui | 4/4 sous-périodes |
| Aucune fenêtre de 5 ans perdante (CAGR ≥ 0) | oui | pire fenêtre +3.1% par an |
| Réglage sur un plateau (voisins ≥ 80 % du Sharpe) | oui | pire voisin 86% du Sharpe par défaut |
| Paramètres choisis sur le passé ≈ réglage par défaut (walk-forward, écart ≥ −0,10) | oui | écart de Sharpe +0.10 |
| Frais × 3 : Sharpe en baisse de moins de 0,10 | oui | −0.06 |

| Sous-période | CAGR | Sharpe | Max DD | Part synthétique |
| --- | ---: | ---: | ---: | ---: |
| 2008-2012 | 3.7% | 0.36 | -14.2% | 100% |
| 2013-2017 | 13.9% | 1.14 | -14.9% | 74% |
| 2018-2022 | 4.5% | 0.37 | -24.3% | 13% |
| 2023-auj. | 21.6% | 1.13 | -20.1% | 0% |

Réglages testés : 27 (momentum (mois) [6, 9, 12], moyenne mobile (mois) [6, 10, 12], nombre d'ETF [1, 2, 3]). Défaut `lookback=12 ma=10 top_n=1` : Sharpe 0.73, rang 18/27. Meilleur sur le passé `lookback=12 ma=12 top_n=3` (0.95) ; centre du plateau `lookback=12 ma=12 top_n=3` (0.95). Walk-forward depuis 2011-02-28 : Sharpe 0.89 contre 0.79 pour le défaut sur les mêmes mois.

### Momentum + Volatility Targeting — robuste

- Surperformance **non démontrée** : meilleur Sharpe que le Buy & Hold dans 9% des fenêtres de 5 ans ; probabilité d'un surplus de rendement réel 13%, 0% après correction des tests multiples ; surplus médian -3.4% par an.
- Protection **moyenne** : baisse maximale -21% contre -39% pour le Buy & Hold ; baisse moins profonde dans 63% des fenêtres de 5 ans.

| Critère | Résultat | Détail |
| --- | --- | --- |
| Sharpe réellement positif (PSR ≥ 95 %) | oui | PSR 100% |
| Résiste aux tests multiples (Sharpe dégonflé ≥ 90 %) | oui | DSR 94% |
| Sharpe positif dans chaque sous-période de 5 ans | oui | 4/4 sous-périodes |
| Aucune fenêtre de 5 ans perdante (CAGR ≥ 0) | oui | pire fenêtre +2.0% par an |
| Réglage sur un plateau (voisins ≥ 80 % du Sharpe) | oui | pire voisin 100% du Sharpe par défaut |
| Paramètres choisis sur le passé ≈ réglage par défaut (walk-forward, écart ≥ −0,10) | oui | écart de Sharpe +0.09 |
| Frais × 3 : Sharpe en baisse de moins de 0,10 | oui | −0.07 |

| Sous-période | CAGR | Sharpe | Max DD | Part synthétique |
| --- | ---: | ---: | ---: | ---: |
| 2008-2012 | 2.5% | 0.29 | -13.1% | 100% |
| 2013-2017 | 11.9% | 1.15 | -11.1% | 74% |
| 2018-2022 | 2.7% | 0.28 | -20.9% | 13% |
| 2023-auj. | 13.5% | 1.01 | -12.8% | 0% |

Réglages testés : 12 (volatilité cible [0.08, 0.1, 0.12, 0.15], fenêtre de volatilité (mois) [3, 6, 12]). Défaut `target_vol=0.1 vol_window=3` : Sharpe 0.66, rang 11/12. Meilleur sur le passé `target_vol=0.1 vol_window=12` (0.77) ; centre du plateau `target_vol=0.1 vol_window=12` (0.77). Walk-forward depuis 2011-02-28 : Sharpe 0.82 contre 0.73 pour le défaut sur les mêmes mois.

### Inverse volatilité (actions) — robuste

- Surperformance **non démontrée** : meilleur Sharpe que le Buy & Hold dans 25% des fenêtres de 5 ans ; probabilité d'un surplus de rendement réel 62%, 7% après correction des tests multiples ; surplus médian -0.5% par an.
- Protection **faible** : baisse maximale -40% contre -39% pour le Buy & Hold ; baisse moins profonde dans 39% des fenêtres de 5 ans.

| Critère | Résultat | Détail |
| --- | --- | --- |
| Sharpe réellement positif (PSR ≥ 95 %) | oui | PSR 100% |
| Résiste aux tests multiples (Sharpe dégonflé ≥ 90 %) | oui | DSR 98% |
| Sharpe positif dans chaque sous-période de 5 ans | oui | 4/4 sous-périodes |
| Aucune fenêtre de 5 ans perdante (CAGR ≥ 0) | oui | pire fenêtre +3.4% par an |
| Réglage sur un plateau (voisins ≥ 80 % du Sharpe) | oui | pire voisin 98% du Sharpe par défaut |
| Paramètres choisis sur le passé ≈ réglage par défaut (walk-forward, écart ≥ −0,10) | oui | écart de Sharpe -0.01 |
| Frais × 3 : Sharpe en baisse de moins de 0,10 | oui | −0.00 |

| Sous-période | CAGR | Sharpe | Max DD | Part synthétique |
| --- | ---: | ---: | ---: | ---: |
| 2008-2012 | 4.0% | 0.32 | -40.0% | 100% |
| 2013-2017 | 13.4% | 1.24 | -14.1% | 74% |
| 2018-2022 | 6.4% | 0.51 | -16.9% | 13% |
| 2023-auj. | 20.1% | 1.62 | -9.5% | 0% |

Réglages testés : 3 (fenêtre de volatilité (mois) [6, 12, 24]). Défaut `window=12` : Sharpe 0.78, rang 1/3. Meilleur sur le passé `window=12` (0.78) ; centre du plateau `window=24` (0.78). Walk-forward depuis 2011-02-28 : Sharpe 0.95 contre 0.96 pour le défaut sur les mêmes mois.

### 80/20 CW8.PA / OBLI.PA — robuste

- Surperformance **possible** : meilleur Sharpe que le Buy & Hold dans 68% des fenêtres de 5 ans ; probabilité d'un surplus de rendement réel 0%, 0% après correction des tests multiples ; surplus médian -2.1% par an.
- Protection **moyenne** : baisse maximale -32% contre -39% pour le Buy & Hold ; baisse moins profonde dans 88% des fenêtres de 5 ans.

| Critère | Résultat | Détail |
| --- | --- | --- |
| Sharpe réellement positif (PSR ≥ 95 %) | oui | PSR 100% |
| Résiste aux tests multiples (Sharpe dégonflé ≥ 90 %) | oui | DSR 98% |
| Sharpe positif dans chaque sous-période de 5 ans | oui | 4/4 sous-périodes |
| Aucune fenêtre de 5 ans perdante (CAGR ≥ 0) | oui | pire fenêtre +2.4% par an |
| Frais × 3 : Sharpe en baisse de moins de 0,10 | oui | −0.00 |

| Sous-période | CAGR | Sharpe | Max DD | Part synthétique |
| --- | ---: | ---: | ---: | ---: |
| 2008-2012 | 2.0% | 0.22 | -32.4% | 100% |
| 2013-2017 | 11.8% | 1.37 | -10.0% | 74% |
| 2018-2022 | 6.3% | 0.55 | -15.6% | 13% |
| 2023-auj. | 15.0% | 1.56 | -11.1% | 0% |

### 60/40 CW8.PA / OBLI.PA — robuste

- Surperformance **possible** : meilleur Sharpe que le Buy & Hold dans 68% des fenêtres de 5 ans ; probabilité d'un surplus de rendement réel 0%, 0% après correction des tests multiples ; surplus médian -4.2% par an.
- Protection **forte** : baisse maximale -25% contre -39% pour le Buy & Hold ; baisse moins profonde dans 88% des fenêtres de 5 ans.

| Critère | Résultat | Détail |
| --- | --- | --- |
| Sharpe réellement positif (PSR ≥ 95 %) | oui | PSR 100% |
| Résiste aux tests multiples (Sharpe dégonflé ≥ 90 %) | oui | DSR 98% |
| Sharpe positif dans chaque sous-période de 5 ans | oui | 4/4 sous-périodes |
| Aucune fenêtre de 5 ans perdante (CAGR ≥ 0) | oui | pire fenêtre +2.5% par an |
| Frais × 3 : Sharpe en baisse de moins de 0,10 | oui | −0.00 |

| Sous-période | CAGR | Sharpe | Max DD | Part synthétique |
| --- | ---: | ---: | ---: | ---: |
| 2008-2012 | 2.2% | 0.28 | -25.2% | 100% |
| 2013-2017 | 9.7% | 1.42 | -8.2% | 74% |
| 2018-2022 | 4.2% | 0.45 | -15.5% | 13% |
| 2023-auj. | 12.0% | 1.59 | -8.2% | 0% |

### Dual momentum (actions / obligataire / cash) — robuste

- Surperformance **possible** : meilleur Sharpe que le Buy & Hold dans 59% des fenêtres de 5 ans ; probabilité d'un surplus de rendement réel 91%, 33% après correction des tests multiples ; surplus médian +2.7% par an.
- Protection **moyenne** : baisse maximale -20% contre -39% pour le Buy & Hold ; baisse moins profonde dans 60% des fenêtres de 5 ans.

| Critère | Résultat | Détail |
| --- | --- | --- |
| Sharpe réellement positif (PSR ≥ 95 %) | oui | PSR 100% |
| Résiste aux tests multiples (Sharpe dégonflé ≥ 90 %) | oui | DSR 99% |
| Sharpe positif dans chaque sous-période de 5 ans | oui | 4/4 sous-périodes |
| Aucune fenêtre de 5 ans perdante (CAGR ≥ 0) | oui | pire fenêtre +5.8% par an |
| Réglage sur un plateau (voisins ≥ 80 % du Sharpe) | oui | pire voisin 98% du Sharpe par défaut |
| Paramètres choisis sur le passé ≈ réglage par défaut (walk-forward, écart ≥ −0,10) | **non** | écart de Sharpe -0.16 |
| Frais × 3 : Sharpe en baisse de moins de 0,10 | oui | −0.05 |

| Sous-période | CAGR | Sharpe | Max DD | Part synthétique |
| --- | ---: | ---: | ---: | ---: |
| 2008-2012 | 5.9% | 0.49 | -15.0% | 100% |
| 2013-2017 | 16.7% | 1.24 | -11.5% | 74% |
| 2018-2022 | 12.4% | 0.77 | -18.7% | 13% |
| 2023-auj. | 18.6% | 1.01 | -20.1% | 0% |

Réglages testés : 3 (momentum (mois) [6, 9, 12]). Défaut `lookback=12` : Sharpe 0.86, rang 1/3. Meilleur sur le passé `lookback=12` (0.86) ; centre du plateau `lookback=12` (0.86). Walk-forward depuis 2011-02-28 : Sharpe 0.80 contre 0.96 pour le défaut sur les mêmes mois.

### Top 3 équipondéré + tendance — robuste

- Surperformance **non démontrée** : meilleur Sharpe que le Buy & Hold dans 29% des fenêtres de 5 ans ; probabilité d'un surplus de rendement réel 60%, 6% après correction des tests multiples ; surplus médian -2.4% par an.
- Protection **moyenne** : baisse maximale -17% contre -39% pour le Buy & Hold ; baisse moins profonde dans 58% des fenêtres de 5 ans.

| Critère | Résultat | Détail |
| --- | --- | --- |
| Sharpe réellement positif (PSR ≥ 95 %) | oui | PSR 100% |
| Résiste aux tests multiples (Sharpe dégonflé ≥ 90 %) | oui | DSR 100% |
| Sharpe positif dans chaque sous-période de 5 ans | oui | 4/4 sous-périodes |
| Aucune fenêtre de 5 ans perdante (CAGR ≥ 0) | oui | pire fenêtre +1.6% par an |
| Réglage sur un plateau (voisins ≥ 80 % du Sharpe) | oui | pire voisin 88% du Sharpe par défaut |
| Paramètres choisis sur le passé ≈ réglage par défaut (walk-forward, écart ≥ −0,10) | oui | écart de Sharpe +0.03 |
| Frais × 3 : Sharpe en baisse de moins de 0,10 | oui | −0.04 |

| Sous-période | CAGR | Sharpe | Max DD | Part synthétique |
| --- | ---: | ---: | ---: | ---: |
| 2008-2012 | 9.6% | 0.98 | -10.3% | 100% |
| 2013-2017 | 12.5% | 1.32 | -15.1% | 74% |
| 2018-2022 | 4.3% | 0.41 | -16.6% | 13% |
| 2023-auj. | 19.1% | 1.21 | -15.7% | 0% |

Réglages testés : 27 (momentum (mois) [6, 9, 12], moyenne mobile (mois) [6, 10, 12], nombre d'ETF [2, 3, 4]). Défaut `lookback=12 ma=10 top_n=3` : Sharpe 0.93, rang 8/27. Meilleur sur le passé `lookback=12 ma=12 top_n=4` (1.04) ; centre du plateau `lookback=12 ma=12 top_n=4` (1.04). Walk-forward depuis 2011-02-28 : Sharpe 0.92 contre 0.89 pour le défaut sur les mêmes mois.

### Cœur / satellite (80% CW8.PA + 20% momentum_vt) — robuste

- Surperformance **possible** : meilleur Sharpe que le Buy & Hold dans 60% des fenêtres de 5 ans ; probabilité d'un surplus de rendement réel 13%, 0% après correction des tests multiples ; surplus médian -0.6% par an.
- Protection **moyenne** : baisse maximale -34% contre -39% pour le Buy & Hold ; baisse moins profonde dans 88% des fenêtres de 5 ans.

| Critère | Résultat | Détail |
| --- | --- | --- |
| Sharpe réellement positif (PSR ≥ 95 %) | oui | PSR 100% |
| Résiste aux tests multiples (Sharpe dégonflé ≥ 90 %) | oui | DSR 98% |
| Sharpe positif dans chaque sous-période de 5 ans | oui | 4/4 sous-périodes |
| Aucune fenêtre de 5 ans perdante (CAGR ≥ 0) | oui | pire fenêtre +2.3% par an |
| Frais × 3 : Sharpe en baisse de moins de 0,10 | oui | −0.01 |

| Sous-période | CAGR | Sharpe | Max DD | Part synthétique |
| --- | ---: | ---: | ---: | ---: |
| 2008-2012 | 2.0% | 0.21 | -34.2% | 100% |
| 2013-2017 | 13.6% | 1.36 | -11.0% | 74% |
| 2018-2022 | 7.4% | 0.59 | -16.7% | 13% |
| 2023-auj. | 17.2% | 1.45 | -13.6% | 0% |

## Méta-sélection (choisir chaque année la meilleure stratégie passée)

Hors échantillon depuis 2011-02-28 : Sharpe 0.89, CAGR 10.2%, max DD -16.6% ; Buy & Hold sur les mêmes mois : Sharpe 0.99, CAGR 12.0%.

| Année testée | Stratégie choisie | Sharpe passé |
| --- | --- | ---: |
| 2011-02 → 2012-01 | top3_trend | 1.15 |
| 2012-02 → 2013-01 | top3_trend | 0.91 |
| 2013-02 → 2014-01 | top3_trend | 0.99 |
| 2014-02 → 2015-01 | top3_trend | 1.16 |
| 2015-02 → 2016-01 | top3_trend | 1.44 |
| 2016-02 → 2017-01 | top3_trend | 1.09 |
| 2017-02 → 2018-01 | top3_trend | 1.10 |
| 2018-02 → 2019-01 | top3_trend | 1.18 |
| 2019-02 → 2020-01 | top3_trend | 0.96 |
| 2020-02 → 2021-01 | top3_trend | 1.07 |
| 2021-02 → 2022-01 | top3_trend | 1.00 |
| 2022-02 → 2023-01 | top3_trend | 0.98 |
| 2023-02 → 2024-01 | top3_trend | 0.87 |
| 2024-02 → 2025-01 | top3_trend | 0.91 |
| 2025-02 → 2026-01 | top3_trend | 1.00 |
| 2026-02 → 2026-08 | top3_trend | 0.95 |

## Méthode et limites

- Surperformance : PSR et DSR appliqués au surplus mensuel (stratégie − Buy & Hold), avec la dispersion des surplus de toutes les variantes testées.
- PSR : probabilité que le vrai Sharpe soit positif, corrigée de l'asymétrie et des queues épaisses. DSR : même test contre le meilleur Sharpe attendu par hasard après 81 essais.
- Fenêtres glissantes de 60 mois, pas mensuel (fenêtres qui se chevauchent : pas indépendantes).
- Plateau : réglage dont la moyenne des Sharpe (lui et ses voisins immédiats dans la grille) est la plus haute.
- Walk-forward : paramètres choisis sur tout le passé disponible (≥ 36 mois), testés sur les 12 mois suivants.
- Données partiellement synthétiques avant la cotation des ETF PEA ; avant 2009, indice MSCI World de prix complété d'un rendement de dividende **estimé** (1,5 %/an net de frais, calibré sur CW8, `config/long_history.yaml`) ; cash non rémunéré.
- Les performances passées ne préjugent pas des performances futures.

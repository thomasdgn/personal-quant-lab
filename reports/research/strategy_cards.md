# Fiches des stratégies

Date de génération : 2026-09-25

Chaque fiche décrit le mécanisme d'une stratégie du registre et ses résultats mesurés (robustesse sur historique long, crises). **Ce ne sont pas des recommandations** : le choix de la stratégie suivie reste une décision humaine (`config/policy.yaml`). Aucun ordre n'est passé.

| Stratégie | Temps | Complexité | Lignes | Fiabilité | Surperformance | Protection |
| --- | --- | ---: | ---: | --- | --- | --- |
| Buy & Hold MSCI World | 5 min / mois | 1/4 | 1 | robuste | référence | référence |
| Momentum défensif (12-1, moyenne mobile 10 mois, 1 ETF) | 30 min / mois | 3/4 | 1 | robuste | non démontrée | moyenne |
| Momentum + ciblage de volatilité (stratégie suivie par défaut) | 30 min / mois | 4/4 | 1 | robuste | non démontrée | moyenne |
| Inverse volatilité (actions) | 30 min / mois | 2/4 | 6 | robuste | non démontrée | faible |
| 80/20 actions Monde / obligations euro | 10 min / mois | 1/4 | 2 | robuste | possible | moyenne |
| 60/40 actions Monde / obligations euro | 10 min / mois | 1/4 | 2 | robuste | possible | forte |
| Dual momentum (actions / obligations / cash) | 30 min / mois | 3/4 | 1 | robuste | possible | moyenne |
| Top 3 équipondéré + filtre de tendance | 45 min / mois | 3/4 | 3 | robuste | non démontrée | moyenne |
| Cœur / satellite | 30 min / mois | 2/4 | 2 | robuste | possible | moyenne |

## Buy & Hold MSCI World

_Acheter chaque mois un ETF Monde et ne jamais vendre : la référence que toute stratégie doit battre._

**Temps :** 5 min / mois · **complexité :** 1/4 · **lignes détenues :** 1

**Principe.** Posséder l'économie mondiale (environ 1 400 grandes entreprises de 23 pays développés) sans jamais essayer de deviner le marché. Le rendement vient de la croissance des entreprises et des dividendes réinvestis.

**Règles exactes**

1. Chaque mois, investir tout le versement dans CW8.PA (ou WPEA.PA, part moins chère).
2. Ne jamais vendre, même pendant un krach.
3. Aucun signal à lire, aucun rééquilibrage.

**Forces**

- Le plus simple et le moins cher : frais d'ordre minimaux, aucune décision à prendre.
- Capte toute la hausse de long terme des marchés.
- Impossible de « rater » un rebond en étant sorti du marché.

**Faiblesses**

- Subit toutes les baisses : −51 % en 2008-09 (en euros), −19 % en 2020.
- Peut rester sous son plus haut plusieurs années (environ 4 ans et demi après 2008).
- Environ 70 % d'actions américaines : concentration géographique et monétaire (dollar).

**Pour qui ?** Tout investisseur long terme qui veut une méthode simple et peut supporter de fortes baisses.

**Erreurs fréquentes**

- Vendre pendant un krach puis racheter trop tard.
- Arrêter les versements quand le marché baisse (c'est justement là qu'ils achètent le moins cher).

**Mesures sur historique long (2008-02-29 → 2026-08-31, partiellement synthétique)**

| CAGR | Volatilité | Sharpe | Pire baisse | Pire année | Meilleure année | Pire 5 ans (/an) | Part investie | Rotation / an |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 9.9% | 13.2% | 0.78 | -39% | -14% | 32% | 2.2% | 100% | 0% |

Fiabilité **robuste** (100% des critères) · référence de comparaison.

**Dans les crises** (pire baisse pendant la fenêtre, Buy & Hold entre parenthèses)

- Crise financière 2008-09 : -49% (-49%) — données synthétiques
- Crise de la dette euro 2011 : -28% (-28%) — données synthétiques
- Chine / pétrole 2015-16 : -12% (-12%) — données synthétiques
- T4 2018 : -12% (-12%) — données synthétiques
- Covid 2020 : -19% (-19%)
- Inflation et taux 2022 : -14% (-14%)

## Momentum défensif (12-1, moyenne mobile 10 mois, 1 ETF)

_Détenir l'ETF qui a le plus monté sur un an, s'il est en tendance haussière ; sinon rester en cash._

**Temps :** 30 min / mois · **complexité :** 3/4 · **lignes détenues :** 1

**Principe.** Les actifs qui ont monté ont tendance à continuer à court terme (effet momentum), et un marché sous sa moyenne mobile est souvent en phase baissière. On suit la tendance au lieu de la prédire.

**Règles exactes**

1. Fin de mois : classer les ETF selon leur performance sur 12 mois, en excluant le dernier mois.
2. Garder le premier s'il cote au-dessus de sa moyenne mobile 10 mois ; sinon, cash.
3. Appliquer la décision au début du mois suivant (vendre l'ancien ETF si besoin, acheter le nouveau).

**Forces**

- Sort du marché lors des baisses longues (2008, 2022) et limite les pertes.
- Règles mécaniques : aucune émotion dans la décision.

**Faiblesses**

- Concentration sur un seul ETF à la fois (parfois un marché régional ou sectoriel).
- Faux signaux (« whipsaws ») : vendre en bas puis racheter plus haut lors des rebonds en V.
- Rotation élevée : plus d'ordres, donc plus de frais et une gestion plus exigeante.

**Pour qui ?** Investisseur qui accepte de suivre une règle chaque mois et de sous-performer en marché haussier en échange de baisses plus limitées.

**Erreurs fréquentes**

- Ignorer un signal de sortie « parce que le marché va remonter ».
- Changer les paramètres après une mauvaise année (sur-ajustement).

**Mesures sur historique long (2008-02-29 → 2026-08-31, partiellement synthétique)**

| CAGR | Volatilité | Sharpe | Pire baisse | Pire année | Meilleure année | Pire 5 ans (/an) | Part investie | Rotation / an |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10.0% | 14.5% | 0.73 | -24% | -23% | 31% | 3.1% | 92% | 395% |

Fiabilité **robuste** (100% des critères) · surperformance **non démontrée** · protection **moyenne**.

**Dans les crises** (pire baisse pendant la fenêtre, Buy & Hold entre parenthèses)

- Crise financière 2008-09 : -29% (-49%) — données synthétiques
- Crise de la dette euro 2011 : -21% (-28%) — données synthétiques
- Chine / pétrole 2015-16 : -15% (-12%) — données synthétiques
- T4 2018 : -16% (-12%) — données synthétiques
- Covid 2020 : -11% (-19%)
- Inflation et taux 2022 : -20% (-14%)

## Momentum + ciblage de volatilité (stratégie suivie par défaut)

_Le Momentum défensif, dont la part investie baisse quand le marché devient agité._

**Temps :** 30 min / mois · **complexité :** 4/4 · **lignes détenues :** 1

**Principe.** La volatilité récente annonce souvent les turbulences. On vise une volatilité de 10 % par an : si l'ETF choisi bouge deux fois plus, on n'en détient que la moitié et le reste attend en cash.

**Règles exactes**

1. Même choix d'ETF que le Momentum défensif.
2. Exposition = 10 % ÷ volatilité réalisée (fenêtre de 3 mois), plafonnée à 100 %.
3. Le reste en cash (ou fonds monétaire), ajusté chaque mois.

**Forces**

- Baisses nettement plus faibles que le Buy & Hold (environ −21 % au pire, contre −40 %).
- Réduit l'exposition avant le cœur de certaines crises (Covid 2020).

**Faiblesses**

- Souvent partiellement en cash : rendement moyen le plus faible des stratégies d'actions.
- Beaucoup de petits ajustements mensuels.
- Le réglage actuel (fenêtre de 3 mois) est parmi les moins bons de sa grille : une fenêtre de 12 mois est plus robuste sur l'historique long (à tester en paper trading).

**Pour qui ?** Investisseur pour qui limiter les baisses compte plus que maximiser le rendement.

**Erreurs fréquentes**

- Compter sur elle pour battre le marché : son intérêt est la protection, pas la performance.
- Laisser le cash dormir sur un compte non rémunéré.

**Mesures sur historique long (2008-02-29 → 2026-08-31, partiellement synthétique)**

| CAGR | Volatilité | Sharpe | Pire baisse | Pire année | Meilleure année | Pire 5 ans (/an) | Part investie | Rotation / an |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 7.2% | 11.6% | 0.66 | -21% | -19% | 29% | 2.0% | 74% | 419% |

Fiabilité **robuste** (100% des critères) · surperformance **non démontrée** · protection **moyenne**.

**Dans les crises** (pire baisse pendant la fenêtre, Buy & Hold entre parenthèses)

- Crise financière 2008-09 : -20% (-49%) — données synthétiques
- Crise de la dette euro 2011 : -15% (-28%) — données synthétiques
- Chine / pétrole 2015-16 : -11% (-12%) — données synthétiques
- T4 2018 : -13% (-12%) — données synthétiques
- Covid 2020 : -9% (-19%)
- Inflation et taux 2022 : -16% (-14%)

## Inverse volatilité (actions)

_Répartir entre tous les ETF actions, avec plus de poids aux plus calmes._

**Temps :** 30 min / mois · **complexité :** 2/4 · **lignes détenues :** 6

**Principe.** Chaque ETF reçoit un poids proportionnel à 1 ÷ sa volatilité sur 12 mois : le risque est mieux réparti qu'en pondération égale, et on reste toujours investi.

**Règles exactes**

1. Fin de mois : calculer la volatilité 12 mois de chaque ETF actions.
2. Poids = (1 ÷ volatilité), normalisés pour faire 100 %.
3. Orienter les versements vers les lignes sous leur poids cible.

**Forces**

- Diversifiée sur toutes les zones de l'univers.
- Toujours investie : ne rate aucun rebond.

**Faiblesses**

- Aucune protection en krach (baisse maximale proche du Buy & Hold).
- Beaucoup de lignes : peu pratique avec un petit versement mensuel.

**Pour qui ?** Investisseur qui veut diversifier au-delà du MSCI World sans règle de sortie.

**Erreurs fréquentes**

- Multiplier les petites lignes quand le versement est faible (frais et parts entières).

**Mesures sur historique long (2008-02-29 → 2026-08-31, partiellement synthétique)**

| CAGR | Volatilité | Sharpe | Pire baisse | Pire année | Meilleure année | Pire 5 ans (/an) | Part investie | Rotation / an |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10.2% | 13.6% | 0.78 | -40% | -17% | 39% | 3.4% | 100% | 30% |

Fiabilité **robuste** (100% des critères) · surperformance **non démontrée** · protection **faible**.

**Dans les crises** (pire baisse pendant la fenêtre, Buy & Hold entre parenthèses)

- Crise financière 2008-09 : -49% (-49%) — données synthétiques
- Crise de la dette euro 2011 : -22% (-28%) — données synthétiques
- Chine / pétrole 2015-16 : -14% (-12%) — données synthétiques
- T4 2018 : -11% (-12%) — données synthétiques
- Covid 2020 : -17% (-19%)
- Inflation et taux 2022 : -16% (-14%)

## 80/20 actions Monde / obligations euro

_80 % MSCI World, 20 % obligations de la zone euro, rééquilibrés._

**Temps :** 10 min / mois · **complexité :** 1/4 · **lignes détenues :** 2

**Principe.** Les obligations amortissent une partie des baisses d'actions, et le rééquilibrage force à acheter ce qui a baissé.

**Règles exactes**

1. Viser 80 % CW8.PA / WPEA.PA et 20 % OBLI.PA.
2. Diriger chaque versement vers la ligne en retard sur sa cible.
3. Rééquilibrer si un poids s'écarte de plus de 5 points.

**Forces**

- Baisses un peu plus faibles que le 100 % actions.
- Simple et discipliné.

**Faiblesses**

- Rendement de long terme plus faible.
- En 2022, actions et obligations ont baissé ensemble : la protection n'est pas garantie.
- Dans le PEA, OBLI.PA est devenu un fonds monétaire (€STR) vers 2024-11 : la poche « obligataire » est en pratique du cash ; aucun ETF obligataire éligible au PEA n'est suivi (voir `main.py universe`).

**Pour qui ?** Investisseur à horizon moyen ou qui dort mal avec 100 % d'actions.

**Erreurs fréquentes**

- Vendre les obligations quand elles baissent (elles servent de réserve pour racheter des actions).

**Mesures sur historique long (2008-02-29 → 2026-08-31, partiellement synthétique)**

| CAGR | Volatilité | Sharpe | Pire baisse | Pire année | Meilleure année | Pire 5 ans (/an) | Part investie | Rotation / an |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 8.3% | 10.8% | 0.79 | -32% | -15% | 24% | 2.4% | 100% | 0% |

Fiabilité **robuste** (100% des critères) · surperformance **possible** · protection **moyenne**.

**Dans les crises** (pire baisse pendant la fenêtre, Buy & Hold entre parenthèses)

- Crise financière 2008-09 : pas encore active.
- Crise de la dette euro 2011 : -11% (-28%) — données synthétiques
- Chine / pétrole 2015-16 : -10% (-12%) — données synthétiques
- T4 2018 : -9% (-12%) — données synthétiques
- Covid 2020 : -16% (-19%)
- Inflation et taux 2022 : -14% (-14%)

## 60/40 actions Monde / obligations euro

_Le portefeuille équilibré classique : 60 % actions, 40 % obligations._

**Temps :** 10 min / mois · **complexité :** 1/4 · **lignes détenues :** 2

**Principe.** Même logique que le 80/20, avec davantage d'amortisseur : les baisses sont nettement plus faibles, au prix d'un rendement plus bas.

**Règles exactes**

1. Viser 60 % CW8.PA / WPEA.PA et 40 % OBLI.PA (ou fonds euros en assurance-vie).
2. Diriger les versements vers la ligne en retard ; rééquilibrer au-delà de 5 points d'écart.

**Forces**

- La meilleure protection contre les baisses parmi les stratégies testées (verdict « forte »).
- Adaptée à un horizon de 5 à 10 ans ou à un objectif précis.

**Faiblesses**

- Rendement nettement plus faible sur 15 à 30 ans.
- Les obligations peuvent souffrir quand les taux montent (2022).
- Dans le PEA, OBLI.PA est devenu un fonds monétaire (€STR) vers 2024-11 : la poche « obligataire » est en pratique du cash ; aucun ETF obligataire éligible au PEA n'est suivi (voir `main.py universe`).

**Pour qui ?** Profil prudent ou projet à moyen terme.

**Erreurs fréquentes**

- Choisir le 60/40 avec un horizon de 20 ans ou plus sans en accepter le coût en rendement.

**Mesures sur historique long (2008-02-29 → 2026-08-31, partiellement synthétique)**

| CAGR | Volatilité | Sharpe | Pire baisse | Pire année | Meilleure année | Pire 5 ans (/an) | Part investie | Rotation / an |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 6.6% | 8.6% | 0.79 | -25% | -16% | 19% | 2.5% | 100% | 0% |

Fiabilité **robuste** (100% des critères) · surperformance **possible** · protection **forte**.

**Dans les crises** (pire baisse pendant la fenêtre, Buy & Hold entre parenthèses)

- Crise financière 2008-09 : pas encore active.
- Crise de la dette euro 2011 : -8% (-28%) — données synthétiques
- Chine / pétrole 2015-16 : -8% (-12%) — données synthétiques
- T4 2018 : -7% (-12%) — données synthétiques
- Covid 2020 : -12% (-19%)
- Inflation et taux 2022 : -14% (-14%)

## Dual momentum (actions / obligations / cash)

_Détenir la meilleure action si elle bat les obligations et zéro ; sinon les obligations ou le cash._

**Temps :** 30 min / mois · **complexité :** 3/4 · **lignes détenues :** 1

**Principe.** Deux filtres de momentum : relatif (la meilleure zone actions) et absolu (a-t-elle au moins battu les obligations et le cash ?). En marché baissier, on se réfugie dans l'obligataire.

**Règles exactes**

1. Fin de mois : momentum 12-1 de chaque ETF actions et de l'obligataire.
2. Si la meilleure action bat l'obligataire et zéro : 100 % sur elle.
3. Sinon, obligataire si son momentum est positif ; sinon cash.

**Forces**

- Meilleur rendement annualisé observé sur l'historique long, avec des baisses limitées.
- Une seule ligne à la fois : praticable avec un petit budget.

**Faiblesses**

- Tout sur un seul actif : forte dépendance au bon timing.
- Signal lent (12 mois) : entre et sort avec retard.
- Surperformance « possible » mais non démontrée statistiquement.
- Dans le PEA, OBLI.PA est devenu un fonds monétaire (€STR) vers 2024-11 : la poche « obligataire » est en pratique du cash ; aucun ETF obligataire éligible au PEA n'est suivi (voir `main.py universe`).

**Pour qui ?** Investisseur à l'aise avec une stratégie active et concentrée, qui suit la règle sans exception.

**Erreurs fréquentes**

- La juger sur une seule année : ses résultats sont très irréguliers d'une année à l'autre.

**Mesures sur historique long (2008-02-29 → 2026-08-31, partiellement synthétique)**

| CAGR | Volatilité | Sharpe | Pire baisse | Pire année | Meilleure année | Pire 5 ans (/an) | Part investie | Rotation / an |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 13.0% | 15.6% | 0.86 | -20% | -9% | 36% | 5.8% | 94% | 357% |

Fiabilité **robuste** (86% des critères) · surperformance **possible** · protection **moyenne**.

**Dans les crises** (pire baisse pendant la fenêtre, Buy & Hold entre parenthèses)

- Crise financière 2008-09 : -30% (-49%) — données synthétiques
- Crise de la dette euro 2011 : -19% (-28%) — données synthétiques
- Chine / pétrole 2015-16 : -11% (-12%) — données synthétiques
- T4 2018 : -16% (-12%) — données synthétiques
- Covid 2020 : -11% (-19%)
- Inflation et taux 2022 : -19% (-14%)

## Top 3 équipondéré + filtre de tendance

_Les trois ETF les plus forts sur un an, à parts égales, seulement s'ils sont en tendance haussière._

**Temps :** 45 min / mois · **complexité :** 3/4 · **lignes détenues :** 3

**Principe.** Même idée que le Momentum, mais répartie sur trois ETF pour réduire le risque de concentration ; chaque ligne sous sa moyenne mobile 10 mois est remplacée par du cash.

**Règles exactes**

1. Fin de mois : classer les ETF selon leur momentum 12-1.
2. Garder les trois premiers, un tiers chacun, s'ils cotent au-dessus de leur moyenne mobile 10 mois.
3. La part d'un ETF sous sa moyenne mobile reste en cash.

**Forces**

- Meilleur Sharpe observé (0,93) et baisse maximale la plus faible (environ −17 %).
- Plus diversifié que le Momentum à un ETF.

**Faiblesses**

- Trois lignes : difficile avec moins de 300 € par mois (parts entières, frais).
- Surperformance non démontrée après correction des tests multiples.
- Rotation élevée.

**Pour qui ?** Investisseur actif, avec un budget suffisant pour trois lignes, prêt à suivre la règle chaque mois.

**Erreurs fréquentes**

- Garder un ETF sorti du top 3 par attachement.

**Mesures sur historique long (2008-02-29 → 2026-08-31, partiellement synthétique)**

| CAGR | Volatilité | Sharpe | Pire baisse | Pire année | Meilleure année | Pire 5 ans (/an) | Part investie | Rotation / an |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10.7% | 11.7% | 0.93 | -17% | -17% | 32% | 1.6% | 86% | 240% |

Fiabilité **robuste** (100% des critères) · surperformance **non démontrée** · protection **moyenne**.

**Dans les crises** (pire baisse pendant la fenêtre, Buy & Hold entre parenthèses)

- Crise financière 2008-09 : -22% (-49%) — données synthétiques
- Crise de la dette euro 2011 : -10% (-28%) — données synthétiques
- Chine / pétrole 2015-16 : -15% (-12%) — données synthétiques
- T4 2018 : -13% (-12%) — données synthétiques
- Covid 2020 : -14% (-19%)
- Inflation et taux 2022 : -15% (-14%)

## Cœur / satellite

_Un cœur en Buy & Hold (80 %) et un satellite (20 %) dans une stratégie active._

**Temps :** 30 min / mois · **complexité :** 2/4 · **lignes détenues :** 2

**Principe.** Le cœur garantit de capter le marché ; le satellite permet d'appliquer une stratégie active sur une petite part, sans mettre en jeu tout le portefeuille.

**Règles exactes**

1. Cœur : 80 % en CW8.PA / WPEA.PA, jamais vendu.
2. Satellite : 20 % selon la stratégie choisie (Momentum + VT par défaut).
3. Versements dirigés vers la poche en retard sur sa cible.

**Forces**

- Compromis : presque tout le rendement du marché, avec un peu d'amortisseur.
- Idéal pour apprendre une stratégie active sans risquer tout le capital.

**Faiblesses**

- Protection modeste (le cœur subit les krachs).
- Deux logiques à suivre.

**Pour qui ?** Investisseur qui veut rester principalement passif tout en expérimentant.

**Erreurs fréquentes**

- Laisser le satellite grossir au-delà de sa part cible.

**Mesures sur historique long (2008-02-29 → 2026-08-31, partiellement synthétique)**

| CAGR | Volatilité | Sharpe | Pire baisse | Pire année | Meilleure année | Pire 5 ans (/an) | Part investie | Rotation / an |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 9.4% | 12.2% | 0.80 | -34% | -15% | 28% | 2.3% | 95% | 84% |

Fiabilité **robuste** (100% des critères) · surperformance **possible** · protection **moyenne**.

**Dans les crises** (pire baisse pendant la fenêtre, Buy & Hold entre parenthèses)

- Crise financière 2008-09 : -43% (-49%) — données synthétiques
- Crise de la dette euro 2011 : -23% (-28%) — données synthétiques
- Chine / pétrole 2015-16 : -11% (-12%) — données synthétiques
- T4 2018 : -12% (-12%) — données synthétiques
- Covid 2020 : -17% (-19%)
- Inflation et taux 2022 : -13% (-14%)

_Mesures indicatives : données partiellement synthétiques avant la cotation des ETF PEA ; les performances passées ne préjugent pas des performances futures._

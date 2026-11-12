# Rapport — Projet 3 : Volatility Targeting et contrôle du risque

> Document de recherche **éducatif**. Ce n'est pas un conseil d'investissement.
> Aucun ordre n'est exécuté. Résultats dépendant des données Yahoo Finance au
> moment de l'exécution (backtest daté du 7 juillet 2026).

Notebook : [`notebooks/04_volatility_targeting.ipynb`](../notebooks/04_volatility_targeting.ipynb).
Code : `src/features.py` (`rolling_annualized_volatility`), `src/portfolio.py`.

## 1. Objectif

Ajuster la **taille** de l'exposition d'une stratégie (ici le Momentum défensif
du Projet 2) selon le risque observé, sans chercher à prédire le rendement.

## 2. Logique financière

Les périodes de forte volatilité sont souvent associées à un risque de perte
accru. Réduire l'exposition quand la volatilité réalisée dépasse une cible vise à
lisser le profil de risque — quitte à parfois rater une partie d'une reprise.

## 3. Formule utilisée

```text
exposition_brute  = volatilité_cible / volatilité_réalisée
exposition_finale = clip(exposition_brute, min_exposure, max_exposure)
```

Version sans levier : `min_exposure = 0`, `max_exposure = 1`. Le reste du
portefeuille va au cash. Volatilité réalisée = écart-type d'échantillon glissant
des rendements mensuels de la stratégie de base, annualisé par `× √12`.

## 4. Choix de la fenêtre

Fenêtres testées : 3, 6, 12 mois. **Choix principal : 3 mois** (réactif). Les
fenêtres plus longues sont plus lisses mais réagissent tard aux chocs. La fenêtre
est un paramètre de la grille de robustesse, pas un réglage optimisé sur le
rendement.

## 5. Volatilité cible

Cibles testées : 6, 8, 10, 12 %. La cible principale illustrée est **10 %**.
Plus la cible est basse, plus l'exposition moyenne et le rendement baissent.

## 6. Gestion des NaN et des volatilités nulles

- Volatilité **NaN** (fenêtre incomplète en début d'historique) → exposition
  **0 %** (100 % cash) : aucune donnée future n'est inventée.
- Volatilité **nulle** (risque observé nul) → exposition plafonnée à
  `max_exposure` (1,0) : jamais de levier implicite malgré la division.
- Aucun forward-fill silencieux ; les premières périodes restent en cash.

## 7. Règle anti-look-ahead

La volatilité réalisée à la fin du mois M utilise le rendement de M. Elle ne peut
donc dimensionner que l'exposition du mois **M+1**. On applique un **décalage
explicite d'une période** (`shift(1)`) : l'exposition tenue pendant le mois M
n'utilise que la volatilité connue jusqu'à M-1. Un test synthétique prouve qu'un
pic de volatilité en M ne réduit pas le rendement de M (seulement celui de M+1)
et qu'une version « même mois » (trichée) donnerait un résultat différent.

## 8. Construction de l'exposition finale

1. rendements nets mensuels de la stratégie Momentum de base
   (`backtest_monthly_allocation`, frais nuls pour mesurer le risque, pas le coût) ;
2. volatilité réalisée glissante (`rolling_annualized_volatility`) ;
3. exposition cible `compute_target_exposure` (connue en fin de mois) ;
4. **décalage d'un mois** pour l'exécution ;
5. mise à l'échelle des poids Momentum par l'exposition, le reste en cash
   (`apply_volatility_target`). Les poids finaux restent dans `[0, 1]` et
   totalisent 1 ; un portefeuille 100 % cash le reste.

Pas de matrice de covariance, pas de risk parity, pas d'optimisation : version
simple, lisible et testable.

## 9. Stratégies comparées

Buy & Hold CW8.PA ; Momentum 12-1 sans filtre ; Momentum 12-1 + MA10 ;
Momentum 12-1 + MA10 **+ Volatility Targeting** ; Momentum sans filtre + VT.
Mêmes conventions (frais, turnover, cash, capital 10 000 €, mensuel, période
commune 2015→2026, univers CW8.PA + ESE.PA).

## 10. Résultats

Frais 0,10 %, cible 10 %, fenêtre 3 mois.

| Stratégie | CAGR | Vol. | Sharpe | Max DD | Expo. moy. | Capital final |
| --------- | ----:| ----:| ------:| ------:| ----------:| -------------:|
| Buy & Hold CW8.PA        | 11,2 % | 13,2 % | 0,88 | −18,6 % | 100 % | 34 053 € |
| Mom 12-1 + MA10          |  8,8 % | 10,9 % | 0,83 | −16,6 % | ~76 % | 26 456 € |
| **Mom 12-1 + MA10 + VT** |  7,1 % |  9,9 % | 0,75 | −14,9 % | ~85 % | 22 236 € |

## 11. Robustesse

Grille cible × fenêtre × frais (voir notebook). À fenêtre 3 mois, frais 0,10 % :

| Cible | CAGR | Vol. | Sharpe | Max DD | Expo. moy. |
| -----:| ----:| ----:| ------:| ------:| ----------:|
|  6 %  | 5,6 % | 8,2 % | 0,71 | −13,1 % | 69 % |
|  8 %  | 6,4 % | 9,1 % | 0,73 | −14,4 % | 79 % |
| 10 %  | 7,1 % | 9,9 % | 0,75 | −14,9 % | 85 % |
| 12 %  | 7,7 % | 10,3 % | 0,77 | −15,2 % | 90 % |

Tendance nette et monotone : plus la cible est basse, plus la volatilité, le
drawdown, l'exposition et le rendement baissent ensemble. Les frais dégradent
monotonement le capital final moyen.

## 12. Drawdowns

Le VT réduit le drawdown maximal (−14,9 % à cible 10 % contre −16,6 % pour le
Momentum seul et −18,6 % pour le Buy & Hold), et davantage encore aux cibles
basses (−13,1 % à 6 %).

## 13. Turnover

Le VT ajoute du turnover : l'exposition varie en continu (et pas seulement lors
des changements d'actif), donc chaque mois rebalance partiellement. C'est un coût
supplémentaire par rapport au Momentum seul.

## 14. Coûts

Les coûts cumulés augmentent avec le turnover ; à frais constants, le VT coûte
plus que le Momentum simple. La sensibilité aux frais reste monotone (plus de
frais ⇒ moins de capital).

## 15. Exposition moyenne

Exposition exécutée moyenne ≈ 85 % à cible 10 % (min 0 %, max 100 %), avec 8 mois
sur 139 à exposition fortement réduite (< 50 %). Aux cibles plus basses,
l'exposition moyenne descend (69 % à 6 %).

## 16. Limites

- Univers minuscule et très corrélé (World vs S&P 500), historique court (~11,5
  ans, marché majoritairement haussier) : peu favorable à une assurance-risque.
- La volatilité réalisée est un estimateur retardé ; le VT vend souvent **après**
  le début d'une baisse et réinvestit **après** le creux.
- Vol total-return approximatif (yfinance), sans fiscalité, sans slippage.
- Dernier mois partiel non retraité.

## 17. Conclusion

> **Le Volatility Targeting améliore-t-il réellement le couple rendement/risque
> par rapport au Momentum simple ?**

**Sur ces données : non, pas en rendement ajusté du risque.** Le VT **réduit bien
le risque absolu** (volatilité 10,9 % → 9,9 %, drawdown −16,6 % → −14,9 %), ce qui
est son but, mais le **Sharpe baisse** (0,83 → 0,75) et le rendement diminue
nettement. Dans un marché haussier, réduire l'exposition coûte du rendement sans
gain de Sharpe. La mécanique est correcte, testée et sans look-ahead ; l'intérêt
économique **n'est pas démontré** ici. Le VT reste défendable pour un investisseur
qui privilégie explicitement un drawdown plus faible à un Sharpe plus élevé.

## 18. Décision : paper trading ?

**Non — pas de passage en argent réel.** Le VT n'apporte pas d'avantage robuste
de rendement/risque sur cet échantillon. Pistes avant toute décision : univers
plus large et moins corrélé, historique incluant plusieurs régimes baissiers,
comparaison hors échantillon, et arbitrage explicite entre drawdown et Sharpe
selon la tolérance au risque. La décision reste **manuelle**.

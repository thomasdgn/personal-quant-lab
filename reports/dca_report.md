# Versements mensuels programmés (DCA) — Projet 1B

Date de génération : 2026-09-25

Simulation d'un versement mensuel fixe dans chaque stratégie, sur les mêmes mois. Usage éducatif : aucun ordre n'est exécuté.

## Hypothèses

- Période : 2015-02-28 → 2026-08-31 (139 versements)
- Versement mensuel : 400.00 €
- Frais des versements (barème configuré) : 0.10% + 0.00 € par ordre (minimum 0.00 €), un ordre par ETF acheté ; frais de rotation des stratégies inclus dans leurs rendements nets (modèle proportionnel).
- Versement en début de mois, rendement net du mois appliqué ensuite.
- Fiscalité : retrait total en fin de période ; PEA de plus de 5 ans = prélèvements sociaux 18.6 % sur le gain (sinon flat tax 31 %). Inflation non modélisée.

## Résultats

| Stratégie | Total versé | Valeur finale | Valeur nette d'impôt | Plus-value | TRI annualisé | Frais des versements | Max DD stratégie | Pire recul du capital |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Buy & Hold CW8.PA | 55,600.00 € | 120,980.26 € | 108,819.53 € | 65,380.26 € (117.59%) | 12.72% | 55.60 € | -18.61% | -16.46% |
| Momentum défensif | 55,600.00 € | 123,588.11 € | 110,942.32 € | 67,988.11 € (122.28%) | 13.06% | 47.20 € | -24.32% | -18.92% |
| Momentum + VT | 55,600.00 € | 90,360.74 € | 83,895.24 € | 34,760.74 € (62.52%) | 8.06% | 35.47 € | -20.95% | -11.23% |

## Lecture

- Valeur finale la plus élevée : Momentum défensif.
- Le « pire recul du capital » mesure la baisse maximale de la valeur du portefeuille (versements inclus) : c'est la perte que tu aurais vue sur ton relevé.
- Une valeur finale plus élevée sur une seule période ne prouve pas la supériorité d'une stratégie.

## Limites

- Historique court (depuis 2015) et majoritairement haussier.
- Données Yahoo Finance non officielles ; frais réels du courtier à vérifier.
- Les performances passées ne préjugent pas des performances futures.

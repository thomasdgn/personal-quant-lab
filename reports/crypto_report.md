# Poche crypto risk-on / risk-off BTC/ETH — Projet 6 (recherche)

Date de génération : 2026-09-23

Recherche uniquement : **non branchée** sur le rapport mensuel, aucun levier, aucun ordre.

## Hypothèses

- Données : BTC-EUR et ETH-EUR (Yahoo Finance, en euros), période 2017-12-31 → 2026-08-31.
- Risk-on si BTC > MA 200 jours et momentum 90 jours > 0 ; sinon 100 % cash (non rémunéré).
- Rebalancement mensuel, signal exécuté la période suivante.
- Frais : 0.25% par unité de turnover (plateforme crypto).
- Volatility targeting : cible 40% annualisée, volatilité 30 jours, sans levier.
- Fiscalité : flat tax 30 % sur la plus-value, payée une fois à la sortie (rendement cumulé net).

## Stratégies crypto

| Stratégie | CAGR | Volatilité | Sharpe | Max drawdown | Exposition moy. | Cumulé brut | Cumulé net d'impôt |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Buy & Hold BTC | 26.6% | 67.7% | 0.67 | -74.4% | 100% | 686.0% | 480.2% |
| Buy & Hold 70/30 BTC/ETH | 29.8% | 71.0% | 0.70 | -75.6% | 100% | 881.4% | 617.0% |
| Risk-on/off BTC | 27.5% | 49.1% | 0.72 | -56.4% | 47% | 735.2% | 514.7% |
| Risk-on/off 70/30 | 38.0% | 49.2% | 0.87 | -46.1% | 47% | 1577.1% | 1104.0% |
| Risk-on/off 70/30 + VT | 26.3% | 34.8% | 0.83 | -30.6% | 34% | 671.1% | 469.7% |

## Effet patrimonial (cœur = Buy & Hold CW8.PA, rebalancement mensuel)

| Portefeuille | CAGR | Volatilité | Sharpe | Max drawdown |
| --- | ---: | ---: | ---: | ---: |
| 100 % cœur | 12.4% | 13.6% | 0.93 | -18.6% |
| 95% cœur + 5% Buy & Hold 70/30 BTC/ETH | 14.3% | 14.7% | 0.99 | -19.0% |
| 90% cœur + 10% Buy & Hold 70/30 BTC/ETH | 16.1% | 16.5% | 0.99 | -19.4% |
| 95% cœur + 5% Risk-on/off 70/30 | 14.1% | 13.5% | 1.05 | -17.7% |
| 90% cœur + 10% Risk-on/off 70/30 | 15.8% | 13.9% | 1.13 | -16.7% |
| 95% cœur + 5% Risk-on/off 70/30 + VT | 13.3% | 13.4% | 1.00 | -17.7% |
| 90% cœur + 10% Risk-on/off 70/30 + VT | 14.2% | 13.5% | 1.06 | -16.8% |

## Lecture

- Le filtre risk-on/off vise d'abord à **réduire le drawdown** de la poche (les krachs crypto dépassent −70 %) ;
  son intérêt se juge au drawdown et au Sharpe, pas au rendement final.
- Une poche de 5 à 10 % modifie peu le portefeuille global en temps normal mais pèse fortement lors des chocs.
- Taille maximale suggérée par le guide : 1 à 3 % du patrimoine au début, 5 % au plus, après paper trading.

## Limites

- Historique court (ETH-EUR depuis fin 2017) et dominé par quelques cycles haussiers extrêmes.
- Frais, spreads, fiscalité (flat tax sur les plus-values crypto) et risque de plateforme non modélisés finement.
- Rebalancement entre cœur et poche crypto sans frais ; poche crypto hors PEA.
- Les performances passées ne préjugent pas des performances futures. Aucun ordre n'est exécuté.

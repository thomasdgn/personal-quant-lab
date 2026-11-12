# Stress tests et versements sur longue période

Date de génération : 2026-09-25

Historique mensuel en EUR : 2003-12-31 → 2026-08-31. **Avant la cotation des ETF PEA, les prix sont synthétiques** (proxys de même exposition, `config/long_history.yaml`) : la colonne « part synthétique » indique leur poids dans chaque fenêtre. Aucun ordre, aucune modification de la politique.

## Fenêtres de crise

### Crise financière 2008-09 (2007-11 → 2009-03, part synthétique 100%)

| Stratégie | Rendement | Drawdown max | Récupération (mois après le creux) |
| --- | ---: | ---: | ---: |
| Buy & Hold CW8.PA | -43.4% | -49.4% | 49 |
| Momentum défensif | -21.3% | -29.5% | 41 |
| Momentum + Volatility Targeting **(suivie)** | -14.2% | -20.4% | 37 |
| Inverse volatilité (actions) | -42.2% | -49.1% | 41 |
| 80/20 CW8.PA / OBLI.PA | non active | — | — |
| 60/40 CW8.PA / OBLI.PA | non active | — | — |
| Dual momentum (actions / obligataire / cash) | -22.0% | -30.2% | 36 |
| Top 3 équipondéré + tendance | -15.2% | -22.1% | 12 |
| Cœur / satellite (80% CW8.PA + 20% momentum_vt) | -38.2% | -43.2% | 48 |

### Crise de la dette euro 2011 (2011-05 → 2011-12, part synthétique 100%)

| Stratégie | Rendement | Drawdown max | Récupération (mois après le creux) |
| --- | ---: | ---: | ---: |
| Buy & Hold CW8.PA | -1.8% | -28.0% | 18 |
| Momentum défensif | -6.7% | -21.4% | 9 |
| Momentum + Volatility Targeting **(suivie)** | -5.8% | -15.1% | 5 |
| Inverse volatilité (actions) | -4.3% | -22.4% | 10 |
| 80/20 CW8.PA / OBLI.PA | -1.5% | -11.3% | 5 |
| 60/40 CW8.PA / OBLI.PA | -1.1% | -8.1% | 4 |
| Dual momentum (actions / obligataire / cash) | 4.9% | -18.8% | 6 |
| Top 3 équipondéré + tendance | -3.5% | -10.3% | 5 |
| Cœur / satellite (80% CW8.PA + 20% momentum_vt) | -2.6% | -23.4% | 17 |

### Chine / pétrole 2015-16 (2015-05 → 2016-02, part synthétique 57%)

| Stratégie | Rendement | Drawdown max | Récupération (mois après le creux) |
| --- | ---: | ---: | ---: |
| Buy & Hold CW8.PA | -11.2% | -12.2% | 14 |
| Momentum défensif | -12.9% | -14.9% | 14 |
| Momentum + Volatility Targeting **(suivie)** | -10.7% | -11.1% | 13 |
| Inverse volatilité (actions) | -13.5% | -14.1% | 14 |
| 80/20 CW8.PA / OBLI.PA | -8.5% | -10.0% | 14 |
| 60/40 CW8.PA / OBLI.PA | -5.8% | -8.2% | 10 |
| Dual momentum (actions / obligataire / cash) | -4.1% | -11.5% | 1 |
| Top 3 équipondéré + tendance | -14.4% | -14.6% | 21 |
| Cœur / satellite (80% CW8.PA + 20% momentum_vt) | -11.0% | -11.0% | 9 |

### T4 2018 (2018-09 → 2018-12, part synthétique 54%)

| Stratégie | Rendement | Drawdown max | Récupération (mois après le creux) |
| --- | ---: | ---: | ---: |
| Buy & Hold CW8.PA | -11.6% | -11.6% | 3 |
| Momentum défensif | -15.4% | -15.7% | 11 |
| Momentum + Volatility Targeting **(suivie)** | -12.9% | -13.2% | 13 |
| Inverse volatilité (actions) | -10.7% | -10.7% | 3 |
| 80/20 CW8.PA / OBLI.PA | -9.2% | -9.2% | 3 |
| 60/40 CW8.PA / OBLI.PA | -6.7% | -6.7% | 3 |
| Dual momentum (actions / obligataire / cash) | -15.4% | -15.7% | 4 |
| Top 3 équipondéré + tendance | -13.1% | -13.1% | 11 |
| Cœur / satellite (80% CW8.PA + 20% momentum_vt) | -11.9% | -11.9% | 4 |

### Covid 2020 (2020-01 → 2020-04, part synthétique 0%)

| Stratégie | Rendement | Drawdown max | Récupération (mois après le creux) |
| --- | ---: | ---: | ---: |
| Buy & Hold CW8.PA | -10.9% | -18.6% | 8 |
| Momentum défensif | -11.0% | -11.0% | 4 |
| Momentum + Volatility Targeting **(suivie)** | -8.8% | -8.8% | 4 |
| Inverse volatilité (actions) | -8.8% | -16.9% | 5 |
| 80/20 CW8.PA / OBLI.PA | -9.0% | -15.6% | 8 |
| 60/40 CW8.PA / OBLI.PA | -7.1% | -12.5% | 8 |
| Dual momentum (actions / obligataire / cash) | 0.9% | -10.9% | 1 |
| Top 3 équipondéré + tendance | -13.6% | -13.6% | 7 |
| Cœur / satellite (80% CW8.PA + 20% momentum_vt) | -10.3% | -16.7% | 5 |

### Inflation et taux 2022 (2021-12 → 2022-10, part synthétique 0%)

| Stratégie | Rendement | Drawdown max | Récupération (mois après le creux) |
| --- | ---: | ---: | ---: |
| Buy & Hold CW8.PA | -8.7% | -14.1% | 18 |
| Momentum défensif | -18.4% | -19.6% | 16 |
| Momentum + Volatility Targeting **(suivie)** | -13.6% | -16.0% | 17 |
| Inverse volatilité (actions) | -16.4% | -16.4% | 15 |
| 80/20 CW8.PA / OBLI.PA | -10.4% | -13.7% | 19 |
| 60/40 CW8.PA / OBLI.PA | -12.0% | -14.3% | 18 |
| Dual momentum (actions / obligataire / cash) | -9.1% | -18.7% | 18 |
| Top 3 équipondéré + tendance | -14.9% | -14.9% | 16 |
| Cœur / satellite (80% CW8.PA + 20% momentum_vt) | -9.6% | -12.8% | 18 |

## Versements programmés : distribution des résultats

400 € par mois pendant 30 ans (144 000 € versés), 2000 trajectoires par bootstrap par blocs de 12 mois des rendements historiques de chaque stratégie. Valeur nette : frais d'ordre du barème et prélèvements sociaux (PEA > 5 ans) sur le gain.

| Stratégie | Historique depuis | Valeur nette p5 | p50 | p95 | P(perte) | P(drawdown > limite) | Drawdown médian du pire épisode |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Buy & Hold CW8.PA | 2004-01-31 | 251 050 € | 637 367 € | 1 565 268 € | 0% | 86% | -39.0% |
| Momentum défensif | 2005-01-31 | 360 366 € | 974 646 € | 2 924 110 € | 0% | 80% | -30.5% |
| Momentum + Volatility Targeting **(suivie)** | 2005-01-31 | 264 472 € | 516 460 € | 1 046 645 € | 0% | 46% | -24.4% |
| Inverse volatilité (actions) | 2005-01-31 | 291 887 € | 772 829 € | 2 055 341 € | 0% | 88% | -40.2% |
| 80/20 CW8.PA / OBLI.PA | 2008-02-29 | 267 174 € | 523 143 € | 1 024 918 € | 0% | 78% | -31.6% |
| 60/40 CW8.PA / OBLI.PA | 2008-02-29 | 234 040 € | 386 886 € | 648 449 € | 0% | 43% | -23.9% |
| Dual momentum (actions / obligataire / cash) | 2005-01-31 | 572 543 € | 1 574 033 € | 4 642 553 € | 0% | 79% | -30.0% |
| Top 3 équipondéré + tendance | 2005-01-31 | 421 090 € | 970 011 € | 2 329 051 € | 0% | 45% | -24.1% |
| Cœur / satellite (80% CW8.PA + 20% momentum_vt) | 2004-01-31 | 262 618 € | 613 396 € | 1 362 555 € | 0% | 80% | -34.3% |

## Étude de robustesse : fenêtre courte vs historique long

Courte : 2019-01-31 → 2026-08-31 (données réelles). Longue : 2008-02-29 → 2026-08-31 (partiellement synthétique).

| Stratégie | Sharpe court | Sharpe long | Écart vs B&H long [IC 90 %] | Max DD long |
| --- | ---: | ---: | ---: | ---: |
| Buy & Hold CW8.PA | 1.07 | 0.78 | — | -39.1% |
| Momentum 12-1 MA10 top 1 (défaut) | 0.84 | 0.73 | -0.05 [-0.38 ; +0.27] | -24.3% |
| Momentum + Volatility Targeting | 0.73 | 0.66 | -0.12 [-0.45 ; +0.19] | -20.9% |
| Inverse volatilité (actions) | 1.17 | 0.78 | +0.00 [-0.12 ; +0.12] | -40.0% |
| 80/20 CW8.PA / OBLI.PA | 1.02 | 0.79 | +0.01 [-0.03 ; +0.05] | -32.4% |
| 60/40 CW8.PA / OBLI.PA | 0.94 | 0.79 | +0.01 [-0.10 ; +0.12] | -25.2% |
| Dual momentum (actions / obligataire / cash) | 0.98 | 0.86 | +0.08 [-0.29 ; +0.43] | -20.1% |
| Top 3 équipondéré + tendance | 0.96 | 0.93 | +0.15 [-0.16 ; +0.50] | -16.6% |
| Momentum, paramètres choisis en walk-forward | 0.57 | 0.75 | -0.03 [-0.36 ; +0.32] | -19.6% |

## Sources des données synthétiques

| ETF PEA | Proxys (du plus récent au plus ancien) |
| --- | --- |
| CW8.PA | EUNL.DE (EUR) — iShares Core MSCI World (capitalisant) ; ^990100-USD-STRD (USD) — indice MSCI World prix (sans dividendes) + rendement de dividende net de frais estimé 1,5 %/an (calibré) |
| PUST.PA | QQQ (USD) — Invesco QQQ (Nasdaq-100) ; PUST.PA se comporte comme le Nasdaq-100 |
| ESE.PA | SPY (USD) — SPDR S&P 500 (même indice que ESE.PA) |
| PAEEM.PA | EEM (USD) — iShares MSCI Emerging Markets |
| PCEU.PA | EXSA.DE (EUR) — iShares STOXX Europe 600 ; VGK (USD) — Vanguard FTSE Europe |
| PAASI.PA | AAXJ (USD) — iShares MSCI All Country Asia ex Japan (proche de l'Asie émergente) ; EEM (USD) — iShares MSCI Emerging Markets (avant 2008) |
| OBLI.PA | IEAG.AS (EUR) — iShares Core Euro Aggregate Bond ; IBGL.AS (EUR) — iShares Euro Govt Bond 15-30y (duration longue, plus volatile) |

_Avant 2009, le proxy MSCI World est un indice de prix : un rendement de dividende **estimé** (`dividend_yield_pct`) lui est ajouté ; l'erreur résiduelle est de l'ordre de ±0,5 point par an._

## Conclusion

- Crise financière 2008-09 : drawdown le plus limité Momentum + Volatility Targeting (-20.4%), le plus profond Buy & Hold CW8.PA (-49.4%).
- Crise de la dette euro 2011 : drawdown le plus limité 60/40 CW8.PA / OBLI.PA (-8.1%), le plus profond Buy & Hold CW8.PA (-28.0%).
- Chine / pétrole 2015-16 : drawdown le plus limité 60/40 CW8.PA / OBLI.PA (-8.2%), le plus profond Momentum défensif (-14.9%).
- T4 2018 : drawdown le plus limité 60/40 CW8.PA / OBLI.PA (-6.7%), le plus profond Dual momentum (actions / obligataire / cash) (-15.7%).
- Covid 2020 : drawdown le plus limité Momentum + Volatility Targeting (-8.8%), le plus profond Buy & Hold CW8.PA (-18.6%).
- Inflation et taux 2022 : drawdown le plus limité Cœur / satellite (80% CW8.PA + 20% momentum_vt) (-12.8%), le plus profond Momentum défensif (-19.6%).
- Stratégie suivie (momentum_vt) : probabilité simulée de dépasser un drawdown de 25% sur l'horizon = 46%.
- Résultats indicatifs : données partiellement synthétiques, passé non représentatif du futur.

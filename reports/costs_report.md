# Sensibilité aux frais de transaction

Date de génération : 2026-09-23

Barème configuré : 0.10% + 0.00 € par ordre (minimum 0.00 €). Les scénarios « portefeuille X € » convertissent ce barème en taux proportionnel équivalent pour un rééquilibrage complet.

| Scénario | Taux équivalent | Stratégie | CAGR | Sharpe | Max drawdown | Frais cumulés |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| 0.10% proportionnel | 0.10% | Momentum défensif 12-1 + MA10 | 11.62% | 0.80 | -24.32% | 3.60% |
| 0.10% proportionnel | 0.10% | Momentum + Volatility Targeting | 7.49% | 0.68 | -20.95% | 4.06% |
| 0.20% proportionnel | 0.20% | Momentum défensif 12-1 + MA10 | 11.28% | 0.78 | -24.93% | 7.20% |
| 0.20% proportionnel | 0.20% | Momentum + Volatility Targeting | 7.11% | 0.65 | -21.73% | 8.12% |
| 0.30% proportionnel | 0.30% | Momentum défensif 12-1 + MA10 | 10.94% | 0.76 | -25.54% | 10.80% |
| 0.30% proportionnel | 0.30% | Momentum + Volatility Targeting | 6.74% | 0.62 | -22.51% | 12.18% |
| Barème configuré, portefeuille 2,000 € | 0.10% | Momentum défensif 12-1 + MA10 | 11.62% | 0.80 | -24.32% | 3.60% |
| Barème configuré, portefeuille 2,000 € | 0.10% | Momentum + Volatility Targeting | 7.49% | 0.68 | -20.95% | 4.06% |
| Barème configuré, portefeuille 10,000 € | 0.10% | Momentum défensif 12-1 + MA10 | 11.62% | 0.80 | -24.32% | 3.60% |
| Barème configuré, portefeuille 10,000 € | 0.10% | Momentum + Volatility Targeting | 7.49% | 0.68 | -20.95% | 4.06% |
| Barème configuré, portefeuille 50,000 € | 0.10% | Momentum défensif 12-1 + MA10 | 11.62% | 0.80 | -24.32% | 3.60% |
| Barème configuré, portefeuille 50,000 € | 0.10% | Momentum + Volatility Targeting | 7.49% | 0.68 | -20.95% | 4.06% |
| sans frais (achat unique) | 0.00% | Buy & Hold CW8.PA | 11.37% | 0.89 | -18.61% | 0.00% |

## Lecture

- Une stratégie qui change souvent d'ETF perd plus de rendement quand les frais augmentent ; le Buy & Hold n'en paie presque pas.
- Avec un forfait par ordre, un petit portefeuille supporte un taux effectif élevé : vérifier le barème réel de ton courtier et le renseigner dans `config/strategy_params.yaml > costs`.

# Validation de l'univers ETF PEA

Validation technique des historiques Yahoo Finance. Paper trading uniquement ; aucun ordre réel.

| Ticker | Nom | Catégorie | Première date | Dernière date | Mois d'historique | Actif | Flags | Notes |
|---|---|---|---:|---:|---:|:---:|---|---|
| CW8.PA | MSCI World | monde | 2015-01-02 | 2026-07-31 | 139 | true | — | — |
| ESE.PA | S&P 500 ESG | us_esg | 2015-01-02 | 2026-07-31 | 139 | true | — | — |
| WPEA.PA | MSCI World PEA synthétique | monde | 2024-04-02 | 2026-07-31 | 28 | true | SHORT_HISTORY | Historique court depuis 2024-04-02. |
| PAEEM.PA | MSCI EM PEA | emergents | 2019-04-25 | 2026-07-31 | 88 | true | — | — |
| PUST.PA | S&P 500 PEA | us | 2015-01-02 | 2026-07-31 | 139 | true | — | — |
| PCEU.PA | MSCI Europe | europe | 2019-04-25 | 2026-07-31 | 88 | true | — | — |
| PAASI.PA | MSCI Pacific ex-Japan PEA | pacifique | 2019-04-25 | 2026-07-31 | 88 | true | — | Remplace PXPM.PA, indisponible sur yfinance. |
| GWT.PA | MSCI World Small Cap | small_caps | 2024-04-25 | 2026-07-31 | 28 | true | SHORT_HISTORY | Historique court depuis 2024-04-25. |
| OBLI.PA | Obligations EUR agrégat | obligataire | 2018-12-17 | 2026-07-31 | 92 | true | — | — |
| GOVF.PA | EuroMTS All-Maturity | obligations_souveraines | — | — | — | false | UNAVAILABLE | UNAVAILABLE sur yfinance au 2026-08-03. Données indisponibles via yfinance : historique vide |
| CRPE.PA | EUR Corporate Bond Amundi | obligations_corporate | — | — | — | false | UNAVAILABLE | UNAVAILABLE sur yfinance au 2026-08-03. Données indisponibles via yfinance : historique vide |
| CSH2.PA | Smart Overnight Return | monetaire | 2025-03-17 | 2026-07-31 | 17 | true | SHORT_HISTORY | Historique court depuis 2025-03-17. |

Seuil d'historique suffisant : première date au plus tard le 2022-01-01.
Les actifs `UNAVAILABLE` restent documentés mais sont exclus de l'univers actif.

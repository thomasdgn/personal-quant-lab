# Guide pas-a-pas - Personal Quant Lab

**Objectif du document**  
Te guider pas a pas dans la conception, le codage, le test et la mise en place prudente de plusieurs projets quantitatifs autour de l'investissement sur PEA, compte-titres et crypto.

**Philosophie generale**  
Le but n'est pas de predire les marches de facon certaine. Le but est de construire un systeme rationnel, mesure, testable et documente, qui aide a prendre des decisions d'allocation avec un controle du risque.

**Regle centrale**  
Tant que les backtests, tests de robustesse et rapports ne sont pas propres, le projet reste en paper trading. Aucun algorithme ne doit executer d'ordre automatiquement au debut.

---

## Mode d'emploi rapide

Lis ce document dans l'ordre. Ne commence pas par le machine learning ni la crypto. Commence par le socle technique puis la strategie momentum defensive.

Ordre recommande :

1. Projet 0 - Socle technique et architecture du repo.
2. Projet 1 - Benchmark buy & hold et metriques financieres.
3. Projet 2 - Strategie ETF momentum defensive PEA.
4. Projet 3 - Volatility targeting et controle du risque.
5. Projet 4 - Rapport mensuel et dashboard de decision.
6. Projet 5 - Machine learning pour regimes de marche.
7. Projet 6 - Crypto risk-on / risk-off BTC/ETH.

Ce document est volontairement operationnel : chaque projet contient des objectifs, des fichiers a creer, des etapes, des criteres de validation et des points de vigilance.

---

# État d'avancement au 23 septembre 2026

| Projet                           | État                    | Commentaire                                                                    |
| -------------------------------- | ----------------------- | ------------------------------------------------------------------------------ |
| Projet 0 — Socle technique       | Terminé                 | Data loader, YAML, CSV/Parquet, métriques, graphiques et tests validés         |
| Projet 1 — Benchmark Buy & Hold  | Cœur technique terminé  | Notebook exécuté de bout en bout, métriques et contrôles mathématiques validés |
| Projet 1B — DCA mensuel          | Terminé                 | `src/dca.py`, `main.py dca`, `reports/dca_report.md` (versements, frais, TRI)  |
| Projet 2 — Momentum défensif PEA | Cœur technique terminé  | features/signals/backtest + tests, notebook 03 et rapport ; **pas** de passage en argent réel |
| Projet 3 — Volatility targeting  | Cœur technique terminé  | features/portfolio + tests, notebook 04 et rapport ; réduit le risque mais **pas** le Sharpe |
| Projet 4 — Rapport mensuel       | Cœur technique terminé  | `run-month`, graphiques, journal de décision intégré, snapshot JSON 1.1       |
| Projet 4B — Paper trading        | **Phase active**        | 4 mois décidés (règle des 3 mois atteinte) ; réel suivi par `portfolio`       |
| Projet 4C — Univers ETF PEA      | Validé techniquement    | Univers issu d'`assets.yaml`, rôles `candidate` / `defensive` / `cash_proxy`   |
| Projet 5 — Machine learning      | Terminé — non retenu    | Walk-forward avec frais : l'overlay n'améliore ni Sharpe ni drawdown          |
| Projet 6 — Crypto BTC/ETH        | Recherche terminée      | `src/crypto_signals.py`, notebook 10, `reports/crypto_report.md` ; non branché |
| Projet 7 — Pilotage patrimonial  | Terminé                 | `main.py patrimoine`, valeurs dans `config/holdings.yaml` (non versionné)     |
| Projet 8 — Automatisation        | Script local prêt       | `scripts/run_monthly.ps1` ; planification Windows à activer manuellement      |
| Projet 9 — Notifications         | Prêt, désactivé         | ntfy via `config/notify.yaml` et `run-month --notify`                          |
| Tableau de bord local            | Terminé (lecture seule) | `app/dashboard.py` (Streamlit), lit uniquement les snapshots JSON             |

**Évolutions lab v4 (septembre 2026)** : registre unique des stratégies et politique
d'investissement (`config/policy.yaml`, défaut `momentum_vt`, choix humain) ; expositions et
véhicules (bascule CW8.PA → WPEA.PA quand une part dépasse le budget) ; historique long
2004-2026 par proxys (synthétique, signalé) et stress tests de crise ; portefeuille réel à
partir d'un journal de transactions (TWR, TRI, frais, jalon PEA des 5 ans, plafond) ; tests
par propriétés et non-régression golden ; CI GitHub prête ; libellés PUST.PA (Nasdaq-100) et
PAASI.PA (Asie émergente) corrigés. Règle des 3 mois de journal atteinte (4 mois décidés).

**Évolutions lab v3 (septembre 2026)** : portefeuille fictif du journal (`paper-performance`,
valeur ajoutée de mes choix vs système), plan de versement en parts entières à partir des
positions réelles (proposition, aucun ordre), frais réels (forfait / minimum) et fiscalité
simplifiée, étude de robustesse (`research` : grille en walk-forward, stratégies
alternatives, intervalles de confiance — aucune ne bat le Buy & Hold de façon robuste),
données incrémentales avec contrôles qualité (`DATA_ANOMALY`), notifications ntfy
désactivées par défaut, tableau de bord multipage interactif, export HTML, CLI découpée en
`src/cli/`.

**Évolutions de septembre 2026 (lab v2)** : (1) l'univers du rapport mensuel provient de
`config/assets.yaml` (alerte `UNIVERSE_MISMATCH` si les données locales divergent) ;
CSH2.PA est le proxy monétaire qui rémunère la poche cash et n'est jamais classé ;
l'obligataire peut être classé ou non (`strategy_params.yaml > universe`) ;
(2) `run-month` enchaîne rapport, entrée de journal et comparaison ; `status` indique les
prochaines actions ; (3) constat honnête : sur 2015-2026 avec l'univers enrichi, le
Momentum ne bat pas le Buy & Hold CW8.PA en rendement ajusté du risque, et le VT réduit
fortement le rendement ; (4) le ML de régimes est évalué en walk-forward avec frais et
**n'est pas retenu**. Mode d'emploi : `docs/USAGE.md`.

« Le cœur technique du Projet 2 (Momentum défensif PEA) est terminé et validé techniquement — voir `notebooks/03_momentum_pea.ipynb` et `reports/momentum_pea_report.md`. La validation technique **ne vaut pas** recommandation d'investissement : pas de passage en argent réel (univers trop étroit, historique court, avantage non robuste après frais). La prochaine étape possible est le Projet 3 — Volatility targeting, à ne pas commencer sans décision explicite. Les extensions d'automatisation et d'application mobile restent dans le backlog. »

**Décisions techniques du Projet 2** : momentum défini comme `prix(t-skip)/prix(t-lookback)-1` (12-1 par défaut) ; moyenne mobile simple 10 mois avec `min_periods` ; éligibilité = momentum disponible ET prix > MA ; poids équipondérés sur `top_n`, reste en `CASH` ; signal décalé d'un mois pour l'exécution ; turnover = `0,5·Σ|Δw|` (cash↔ETF et ETF A→B = 100 %) ; frais = `frais × turnover`.

**Décisions techniques du Projet 3** : volatilité réalisée = écart-type d'échantillon glissant des rendements mensuels de la stratégie de base, annualisé `× √12` (fenêtre principale 3 mois) ; exposition = `clip(vol_cible / vol_réalisée, 0, 1)` (sans levier) ; vol nulle → exposition plafonnée (jamais de levier), vol NaN → 0 % (cash) ; **décalage d'un mois** de l'exposition (la vol de M ne dimensionne que M+1) ; poids finaux = poids Momentum × exposition, reste en cash. Résultat honnête sur ces données : le VT **réduit** volatilité et drawdown mais **n'améliore pas** le Sharpe. Voir `notebooks/04_volatility_targeting.ipynb` et `reports/volatility_targeting_report.md`. Prochaine étape possible : Projet 4 (rapport mensuel), à ne pas commencer sans décision explicite.

**Décisions techniques du Projet 4** : paramètres centralisés dans `config/strategy_params.yaml` ; orchestration `src/monthly_pipeline.py` (modèle de données typé en `dataclasses`, alertes INFO/WARNING/CRITICAL, validation structurelle), formatage `src/reporting.py` (Markdown + snapshot JSON), CLI `main.py` (`monthly-report`, `validate`). Anti-look-ahead : troncature stricte à la date d'arrêté + **dernier mois civil complet** comme signal officiel (mois en cours incomplet exclu et signalé). Sorties dans `reports/monthly/` : `.md` lisible et `.json` versionné (`schema_version`, sans NaN, dates ISO). Le **snapshot JSON est le futur contrat de données** pour les extensions (application, widget, notifications), non développées à ce stade. Défaut hors-ligne (`--refresh-data` pour télécharger). La décision reste **manuelle** (`manual_decision.status = PENDING`) : aucun ordre exécuté. Prochaine étape : Projet 4B — paper trading (au moins 3 mois) avant d'envisager le ML.

**Corrections P2 (revue Codex)** : (1) les poids d'allocation doivent totaliser exactement 100 %, la part non investie étant affectée **explicitement** au cash (pas de complétion automatique dans le backtest) ; (2) une alerte `CRITICAL` fixe `pipeline_status = CRITICAL` et fait retourner à la CLI le **code de sortie 2** (le Markdown et le JSON restent générés) ; (3) `volatility_targeting.enabled: false` **désactive réellement** le VT (section `DISABLED`, `target_volatility: null`, aucune alerte VT) ; (4) les replays historiques (`--report-date`) ne publient **aucune métadonnée postérieure** à la date d'arrêté (`last_observation ≤ report_date`, `data_age_days ≥ 0`).

**Décisions techniques du Projet 4B (paper trading)** : couche `src/paper_trading.py` **en fichiers uniquement** (pas de base de données, pas de web, pas de scheduler, pas de notification), au-dessus des snapshots JSON existants — aucune formule financière modifiée. Une entrée de journal (`reports/paper_trading/YYYY-MM-paper-entry.json`) reprend, depuis le snapshot, la stratégie proposée, les allocations cibles, un résumé d'alertes et la **décision humaine** (`manual_decision_status`, défaut `PENDING`). Statuts autorisés : `PENDING`, `APPROVED_PAPER`, `REJECTED`, `SKIPPED`, `NEEDS_REVIEW` — **aucun** statut d'exécution réelle. CLI : `paper-init` (n'écrase pas une entrée approuvée sans `--force`), `paper-list`, `compare-reports`, `paper-decision` (statut et stratégie contrôlés). Le **snapshot JSON reste le contrat de données** pour un futur widget / une application (non développés).

**Routine mensuelle de paper trading** : (1) générer le rapport mensuel ; (2) créer l'entrée paper trading ; (3) lire les alertes ; (4) choisir une stratégie théorique ; (5) renseigner la décision manuelle ; (6) ne passer **aucun** ordre automatique ; (7) le mois suivant, comparer le nouveau rapport au précédent. Le **ML reste dans le backlog** et l'**automatisation réelle** (notifications, courtier, exécution) viendra bien plus tard, uniquement après cette phase d'observation.

## Jalon actuel à fermer avant le Momentum

- [ ] Vérifier une dernière fois `git status` et `git diff`.
- [ ] Exécuter `python -m pytest -q`.
- [ ] Exécuter le notebook Buy & Hold de bout en bout.
- [ ] Ajouter une courte conclusion au benchmark.
- [ ] Sauvegarder éventuellement une synthèse dans `reports/`.
- [ ] Réaliser un commit Git dédié.
- [ ] Commencer seulement ensuite le Projet 2.

Le DCA mensuel (Projet 1B) reste **optionnel** et ne bloque pas le passage au Projet 2.

---

# Principes de securite financiere

## A ne jamais oublier

- Il n'existe pas de prediction safe au sens certain.
- Une strategie doit d'abord survivre aux mauvaises periodes.
- Le rendement n'est pas la premiere metrique a regarder : le drawdown, la volatilite et le risque de ruine passent avant.
- Le backtest doit etre traite avec mefiance.
- Le ML en finance est souvent fragile si les donnees sont peu nombreuses ou mal separees dans le temps.
- Le meilleur systeme est celui que tu peux comprendre, expliquer et suivre en periode de stress.

## Interdictions au debut

- [ ] Pas de levier.
- [ ] Pas de futures.
- [ ] Pas de CFD.
- [ ] Pas de margin trading.
- [ ] Pas de bot intraday.
- [ ] Pas d'options au debut.
- [ ] Pas de strategie crypto avec perpetuals ou levier.
- [ ] Pas d'argent reel avant une phase de paper trading documentee.

## Regle de passage en argent reel

Une strategie peut passer en petite taille seulement si :

- [ ] Elle est comparee a un benchmark simple.
- [ ] Les signaux sont decales correctement dans le temps.
- [ ] Les frais sont inclus.
- [ ] Les resultats sont testes hors echantillon.
- [ ] Les parametres ne sont pas sur-optimises.
- [ ] Le drawdown maximal est acceptable psychologiquement.
- [ ] Tu peux expliquer la strategie en moins de 5 phrases.
- [ ] Tu as tenu un journal de decision pendant au moins 3 mois.

---

# Architecture cible du repo

Nom conseille : `personal-quant-lab`

```text
personal-quant-lab/
|
|-- data/
|   |-- raw/
|   |-- processed/
|
|-- notebooks/
|   |-- 01_data_download.ipynb
|   |-- 02_benchmark_buy_hold.ipynb
|   |-- 03_momentum_pea.ipynb
|   |-- 04_volatility_targeting.ipynb
|   |-- 05_monthly_report.ipynb
|   |-- 06_market_regime_ml.ipynb
|   |-- 07_crypto_risk_on_off.ipynb
|
|-- src/
|   |-- __init__.py
|   |-- data_loader.py
|   |-- cleaning.py
|   |-- features.py
|   |-- signals.py
|   |-- backtest.py
|   |-- metrics.py
|   |-- portfolio.py
|   |-- plotting.py
|   |-- reporting.py
|   |-- crypto_signals.py
|
|-- config/
|   |-- assets.yaml
|   |-- strategy_params.yaml
|
|-- reports/
|   |-- monthly/
|   |-- figures/
|   |-- tables/
|
|-- tests/
|   |-- test_metrics.py
|   |-- test_features.py
|   |-- test_backtest.py
|
|-- requirements.txt
|-- README.md
|-- main.py
```

---

# Setup initial dans VS Code

## Etape 1 - Creer le dossier

```bash
mkdir personal-quant-lab
cd personal-quant-lab
```

## Etape 2 - Creer l'environnement virtuel

Windows :

```bash
python -m venv .venv
.venv\Scripts\activate
```

Mac/Linux :

```bash
python -m venv .venv
source .venv/bin/activate
```

## Etape 3 - Installer les librairies

```bash
pip install pandas numpy matplotlib yfinance pandas-datareader scikit-learn pyyaml jupyter pytest
```

Puis, selon les besoins :

```bash
pip install vectorbt backtesting quantstats scipy statsmodels
```

Pour la crypto plus tard :

```bash
pip install ccxt
```

## Etape 4 - Creer `requirements.txt`

```bash
pip freeze > requirements.txt
```

## Etape 5 - Initialiser Git

```bash
git init
git add .
git commit -m "Initial project structure"
```

---

# Projet 0 - Socle technique et architecture

## Resume

Ce projet consiste a creer le squelette du laboratoire quant. Il ne cherche pas encore a battre le marche. Il sert a poser des bases solides : donnees, metriques, fonctions reutilisables et organisation propre.

## Objectif

Avoir un repo propre qui permet de telecharger des donnees, les sauvegarder, calculer des rendements et produire une premiere courbe de portefeuille.

## Duree indicative

1 a 2 semaines.

## Fichiers a creer

- `src/data_loader.py`
- `src/metrics.py`
- `src/plotting.py`
- `config/assets.yaml`
- `notebooks/01_data_download.ipynb`
- `README.md`

## Etape 0.1 - Creer la configuration des actifs

Fichier : `config/assets.yaml`

```yaml
equity:
  - CW8.PA
  - EWLD.PA
  - ESE.PA

crypto:
  - BTC-USD
  - ETH-USD

benchmarks:
  - CW8.PA
```

Important : ces tickers sont des exemples. Avant tout usage reel, verifie les tickers chez ton courtier et dans Yahoo Finance.

## Etape 0.2 - Creer le module de chargement des donnees

Fichier : `src/data_loader.py`

Fonctions attendues :

```python
def download_prices(tickers: list[str], start: str, end: str | None = None):
    """Telecharge les prix ajustes pour une liste de tickers."""
    pass


def save_prices(prices, path: str):
    """Sauvegarde les prix localement."""
    pass


def load_prices(path: str):
    """Recharge les prix sauvegardes."""
    pass
```

## Etape 0.3 - Creer le module de metriques

Fichier : `src/metrics.py`

Fonctions attendues :

```python
def compute_returns(prices):
    pass


def annualized_return(returns, periods_per_year=252):
    pass


def annualized_volatility(returns, periods_per_year=252):
    pass


def sharpe_ratio(returns, risk_free_rate=0.0, periods_per_year=252):
    pass


def max_drawdown(equity_curve):
    pass
```

## Etape 0.4 - Verifier le socle

Checklist :

- [x] Le repo s'ouvre dans VS Code.
- [x] L'environnement virtuel fonctionne.
- [x] Les dependances s'installent sans erreur.
- [x] Les donnees se telechargent.
- [x] Les donnees se sauvegardent localement.
- [x] Les rendements sont calcules.
- [x] Une courbe de capital peut etre affichee.

## Critere de validation

Tu peux passer au Projet 1 quand tu sais produire une courbe de performance a partir d'une serie de prix.

---

# Projet 1 - Benchmark buy & hold

## Resume

Avant de tester une strategie active, tu dois construire un benchmark passif. Ce benchmark sera la reference contre laquelle toutes tes strategies seront comparees.

## Objectif

Simuler un portefeuille simple qui achete un ETF World et le conserve.

## Pourquoi c'est important

Beaucoup de strategies semblent bonnes seules, mais ne battent pas un simple buy & hold apres frais, fiscalite et stress psychologique. Le benchmark est ton arbitre.

## Duree indicative

1 semaine.

## Fichiers a creer

- `notebooks/02_benchmark_buy_hold.ipynb`
- fonctions supplementaires dans `src/backtest.py`
- fonctions supplementaires dans `src/metrics.py`

## Etape 1.1 - Charger les prix

Dans le notebook :

```python
from src.data_loader import load_prices

prices = load_prices("data/processed/prices.parquet")
benchmark = prices["CW8.PA"]
```

## Etape 1.2 - Calculer les rendements

```python
returns = benchmark.pct_change().dropna()
equity_curve = (1 + returns).cumprod()
```

## Etape 1.3 - Ajouter les metriques

Calculer :

- CAGR.
- Volatilite annualisee.
- Sharpe ratio.
- Max drawdown.
- Pire annee.
- Meilleure annee.

## Etape 1.4 - Ajouter un DCA mensuel optionnel

Tu peux comparer deux cas :

- achat initial de 10 000 euros ;
- versement mensuel fixe.

Le DCA est plus proche d'une vraie demarche d'investissement.

## Etape 1.5 - Rediger la conclusion du benchmark

Exemple de conclusion attendue :

```text
Le benchmark buy & hold sert de reference. Toute strategie active devra justifier son interet par une amelioration du drawdown, de la volatilite ou du ratio rendement/risque, pas seulement par un rendement final legerement superieur.
```

## Checklist

- [x] Le benchmark est calcule.
- [x] Les metriques sont affichees.
- [x] La courbe de capital est tracee.
- [x] Le drawdown est tracee.
- [ ] Les resultats sont sauvegardes dans `reports/`. (dossier encore vide au 6 juillet 2026)
- [ ] La conclusion formelle du benchmark est sauvegardee. (non encore redigee)
- [x] Variante DCA mensuel (Projet 1B). (`main.py dca`, `reports/dca_report.md`)

## Critere de validation

Tu peux passer au Projet 2 quand tu as un benchmark clair et documente.

---

# Projet 2 - Strategie ETF momentum defensive PEA

## Resume

C'est le premier vrai projet d'allocation. L'idee est de selectionner chaque mois les ETF les plus forts, tout en evitant ceux qui sont sous leur tendance longue.

## Objectif

Construire une strategie mensuelle de type momentum + filtre de tendance.

## Hypothese financiere

Les actifs qui ont bien performe sur plusieurs mois ont tendance a continuer a mieux performer a court/moyen terme, sauf lorsque leur tendance longue est cassee.

## Frequence

Mensuelle. Pas d'intraday.

## Univers d'actifs de depart

Exemples a verifier :

- `CW8.PA` - proxy ETF MSCI World PEA.
- `EWLD.PA` - proxy ETF World alternatif.
- `ESE.PA` - proxy ETF S&P 500 PEA.
- `PAEEM.PA` - proxy emergents PEA, a verifier.

## Strategie v1

Chaque fin de mois :

1. Calculer le momentum 12 mois.
2. Retirer le dernier mois du calcul pour eviter l'effet court terme.
3. Calculer la moyenne mobile 10 mois.
4. Garder uniquement les actifs dont le prix est au-dessus de la moyenne mobile.
5. Choisir l'actif avec le meilleur momentum.
6. Appliquer le signal le mois suivant.
7. Si aucun actif n'est valide, rester en cash.

## Fichiers a creer

- `notebooks/03_momentum_pea.ipynb`
- `src/features.py`
- `src/signals.py`
- `src/backtest.py`

## Etape 2.1 - Transformer les prix en donnees mensuelles

```python
monthly_prices = prices.resample("ME").last()
```

## Etape 2.2 - Calculer les features

Dans `src/features.py` :

```python
def compute_momentum(prices, lookback_months=12, skip_months=1):
    raw_momentum = prices.pct_change(lookback_months)
    recent_return = prices.pct_change(skip_months)
    return raw_momentum - recent_return


def compute_moving_average(prices, window=10):
    return prices.rolling(window).mean()


def compute_trend_filter(prices, moving_average):
    return prices > moving_average
```

## Etape 2.3 - Generer les signaux

Dans `src/signals.py` :

```python
def select_best_asset(momentum, trend_filter):
    filtered_momentum = momentum.where(trend_filter)
    return filtered_momentum.idxmax(axis=1)
```

## Etape 2.4 - Eviter le look-ahead bias

Point critique : le signal calcule a la fin du mois M doit etre applique au mois M+1.

```python
signals_to_trade = selected_asset.shift(1)
```

## Etape 2.5 - Backtester

Comparer :

- Buy & hold ETF World.
- Momentum 12 mois seul.
- Momentum 12 mois + moyenne mobile 10 mois.
- Momentum 6 mois + moyenne mobile 10 mois.
- Momentum combine 6 et 12 mois.

## Etape 2.6 - Integrer les frais

Frais a tester :

- 0 % pour verifier la logique pure.
- 0,10 % par transaction.
- 0,20 % par transaction.
- 0,30 % par transaction.

## Etape 2.7 - Tester la robustesse

Parametres a tester :

- Momentum 3 mois.
- Momentum 6 mois.
- Momentum 12 mois.
- Moyenne mobile 6 mois.
- Moyenne mobile 10 mois.
- Moyenne mobile 12 mois.
- Selection du meilleur actif.
- Selection des 2 meilleurs actifs.

## Ce qu'il faut regarder

Ne choisis pas la strategie qui a le meilleur rendement final. Choisis celle qui a le meilleur compromis entre :

- drawdown raisonnable ;
- performance stable ;
- frais limites ;
- turnover limite ;
- parametres robustes ;
- logique economique explicable.

## Livrable final

Un rapport `reports/momentum_pea_report.md` contenant :

- description de la strategie ;
- univers d'actifs ;
- hypothese ;
- parametres ;
- frais ;
- comparaison au benchmark ;
- drawdown ;
- performances annuelles ;
- conclusion ;
- limites.

## Checklist

- [x] Les donnees mensuelles sont propres.
- [x] Les signaux sont decales d'un mois.
- [x] Les frais sont inclus.
- [x] La strategie est comparee au buy & hold.
- [x] Plusieurs parametres sont testes.
- [x] Les resultats sont documentes. (`reports/momentum_pea_report.md`)
- [x] Tu sais expliquer la strategie simplement.

## Critere de validation

Tu peux passer au Projet 3 quand la strategie momentum est robuste et clairement comparee au benchmark.

---

# Projet 3 - Volatility targeting et controle du risque

## Resume

Ce projet ajoute une gestion dynamique de l'exposition. Au lieu d'etre toujours investi a 100 %, tu ajustes la taille de position selon la volatilite realisee.

## Objectif

Reduire l'exposition quand le marche devient trop volatil.

## Hypothese financiere

Les periodes de forte volatilite sont souvent associees a un risque de perte plus important. Reduire l'exposition peut ameliorer le profil de risque, meme si cela peut parfois faire rater une reprise.

## Formule de base

```text
exposition = volatilite_cible / volatilite_realisee
exposition = min(exposition, exposition_max)
```

Version prudente :

```text
exposition_max = 100 %
pas de levier
```

## Fichiers a creer

- `notebooks/04_volatility_targeting.ipynb`
- fonctions dans `src/features.py`
- fonctions dans `src/portfolio.py`

## Etape 3.1 - Calculer la volatilite realisee

```python
def rolling_annualized_volatility(returns, window=60, periods_per_year=252):
    return returns.rolling(window).std() * (periods_per_year ** 0.5)
```

## Etape 3.2 - Calculer l'exposition cible

```python
def compute_target_exposure(realized_vol, target_vol=0.10, max_exposure=1.0):
    exposure = target_vol / realized_vol
    return exposure.clip(upper=max_exposure).fillna(0)
```

## Etape 3.3 - Combiner momentum et vol targeting

Regle :

```text
Si le signal momentum selectionne un actif :
    investir selon l'exposition cible
Sinon :
    rester en cash
```

Exemple :

```text
Signal = ETF World
Volatilite realisee = 18 %
Volatilite cible = 10 %
Exposition = 10 / 18 = 55 %
Cash = 45 %
```

## Etape 3.4 - Tester plusieurs volatilites cibles

A tester :

- 6 %
- 8 %
- 10 %
- 12 %

## Etape 3.5 - Comparer les resultats

Comparer :

- Buy & hold.
- Momentum defensif.
- Momentum defensif + volatility targeting.

## Points de vigilance

- Le volatility targeting peut vendre apres une baisse deja commencee.
- Il peut reduire l'exposition juste avant une reprise.
- Il est utile pour controler le risque, pas pour predire le marche.
- Il faut verifier si l'amelioration du drawdown justifie une eventuelle baisse de rendement.

## Checklist

- [x] La volatilite realisee est calculee sans information future.
- [x] L'exposition est plafonnee a 100 %.
- [x] Les frais sont inclus.
- [x] Les variations d'exposition sont visualisees.
- [x] Le drawdown est compare a celui du momentum simple.
- [x] La strategie reste comprehensible.

## Critere de validation

Tu peux passer au Projet 4 quand tu sais generer une allocation cible mensuelle propre.

---

# Projet 4 - Rapport mensuel et dashboard de decision

## Resume

Ce projet transforme ton lab en outil concret. Chaque mois, tu generes un rapport indiquant les signaux, l'allocation cible, la performance et les risques.

## Objectif

Avoir un outil d'aide a la decision mensuel, sans execution automatique.

## Format recommande au debut

Commence par un rapport Markdown :

```text
reports/monthly/2026-06-report.md
```

Plus tard, tu peux faire une app Streamlit.

## Fichiers a creer

- `src/reporting.py`
- `notebooks/05_monthly_report.ipynb`
- `main.py`

## Contenu du rapport mensuel

Le rapport doit contenir :

- date du rapport ;
- strategie suivie ;
- univers d'actifs ;
- signaux momentum ;
- signaux tendance ;
- volatilite actuelle ;
- allocation cible ;
- allocation precedente ;
- operations theoriques a faire ;
- performance depuis le debut ;
- comparaison au benchmark ;
- drawdown actuel ;
- alerte de risque ;
- commentaire automatique ;
- decision finale manuelle.

## Exemple de sortie

```text
Rapport du 30/06/2026

Strategie : Momentum defensif PEA

Signal principal : positif
Actif selectionne : ETF World
Volatilite realisee : moderee
Exposition cible : 75 %
Cash cible : 25 %

Commentaire :
Le marche reste en tendance positive. La volatilite justifie une exposition partielle plutot qu'une exposition maximale.

Decision manuelle :
A valider par l'investisseuse avant tout ordre.
```

## Etape 4.1 - Creer la fonction de synthese

Dans `src/reporting.py` :

```python
def generate_signal_summary(signals, weights, metrics):
    pass
```

## Etape 4.2 - Creer la fonction de rapport Markdown

```python
def generate_markdown_report(report_data, output_path):
    pass
```

## Etape 4.3 - Ajouter les graphiques

Graphiques utiles :

- courbe de capital ;
- courbe de drawdown ;
- allocation dans le temps ;
- volatilite glissante ;
- rendements annuels ;
- comparaison avec benchmark.

## Etape 4.4 - Ajouter une commande CLI

Exemple :

```bash
python main.py --strategy momentum_pea --report-date 2026-06-30
```

## Checklist

- [x] Le rapport se genere en une commande. (`python main.py monthly-report`)
- [x] Les signaux sont lisibles.
- [x] L'allocation cible est claire.
- [x] Le benchmark est affiche.
- [x] Les risques sont visibles.
- [x] La decision finale reste manuelle. (`manual_decision.status = PENDING`)
- [x] Snapshot JSON versionne genere (contrat de donnees). (`reports/monthly/*.json`)

## Critere de validation

Le rapport mensuel est utilisable sans ouvrir les notebooks (CLI + Markdown + JSON).
Prochaine etape : **Projet 4B — paper trading** (au moins 3 mois) avant d'envisager
le Projet 5 (ML), qui reste dans le backlog sans urgence.

---

# Projet 5 - Machine learning pour regimes de marche

## Resume

Ce projet ajoute une couche ML. On ne cherche pas a predire le prix exact. On cherche a classifier le contexte de marche : favorable, neutre ou defavorable.

## Objectif

Construire un modele qui aide a moduler l'exposition actions en fonction du regime de marche.

## Principe

Le modele prend des features connues a une date donnee et estime la probabilite que les 3 prochains mois soient favorables.

Exemple de decision :

```text
Probabilite favorable > 60 % : exposition actions 100 %
Probabilite entre 50 % et 60 % : exposition actions 60 %
Probabilite entre 40 % et 50 % : exposition actions 30 %
Probabilite < 40 % : cash ou defensif
```

## Pourquoi ne pas commencer par ce projet

Le ML est seduisant mais dangereux si le socle de backtest n'est pas solide. Les risques de data leakage et d'overfitting sont eleves.

## Donnees possibles

Donnees de marche :

- rendement 1 mois ;
- rendement 3 mois ;
- rendement 6 mois ;
- rendement 12 mois ;
- volatilite 1 mois ;
- volatilite 3 mois ;
- drawdown courant ;
- distance a la moyenne mobile 200 jours.

Donnees macro :

- taux courts ;
- taux longs ;
- pente de la courbe des taux ;
- inflation ;
- chomage ;
- indicateurs de stress.

## Fichiers a creer

- `notebooks/06_market_regime_ml.ipynb`
- `src/features.py`
- `src/ml_dataset.py` optionnel
- `src/portfolio.py`

## Etape 5.1 - Construire le dataset mensuel

Chaque ligne correspond a une date de decision mensuelle.

Colonnes :

```text
date
return_1m
return_3m
return_6m
return_12m
vol_3m
drawdown
distance_ma200
future_return_3m
target
```

## Etape 5.2 - Construire la cible

Exemple :

```python
future_return_3m = prices.pct_change(3).shift(-3)
target = (future_return_3m > 0).astype(int)
```

Attention : `future_return_3m` sert uniquement a construire la cible. Les features ne doivent jamais regarder le futur.

## Etape 5.3 - Faire un split temporel

Interdit : split aleatoire.

Correct :

```text
Train : 2010-2018
Validation : 2019-2021
Test : 2022-2026
```

## Etape 5.4 - Commencer par un modele simple

Ordre recommande :

1. Logistic Regression.
2. Random Forest.
3. Gradient Boosting.
4. XGBoost ou LightGBM plus tard.
5. Hidden Markov Model plus tard.

## Etape 5.5 - Evaluer deux dimensions

Dimension ML :

- accuracy ;
- precision ;
- recall ;
- matrice de confusion ;
- ROC AUC.

Dimension financiere :

- CAGR ;
- volatilite ;
- Sharpe ;
- max drawdown ;
- turnover ;
- performance par annee.

## Etape 5.6 - Comparer aux strategies precedentes

Comparer :

- Buy & hold.
- Momentum defensif.
- Momentum + volatility targeting.
- ML seul.
- ML + momentum.

## Points de vigilance majeurs

- Les donnees macro ont des dates de publication. Ne pas utiliser une donnee qui n'etait pas disponible a la date de decision.
- Ne pas multiplier les features sans logique economique.
- Ne pas choisir le modele uniquement parce qu'il donne la meilleure performance en backtest.
- Ne pas faire confiance a une seule periode de test.

## Checklist

- [x] Le split est temporel. (split fixe purgé + walk-forward à fenêtre expansive)
- [x] Les features ne regardent pas le futur. (tests de non-dépendance aux prix futurs)
- [ ] Les donnees macro sont traitees avec prudence. (aucune donnée macro utilisée à ce stade)
- [x] Un modele simple sert de baseline. (régression logistique + classe majoritaire)
- [x] Les resultats ML et financiers sont tous les deux presentes. (`reports/market_regime_report.md`)
- [x] Le modele est interpretable. (logistique, importance des features de la forêt)
- [x] Les limites sont documentees.

## Critere de validation

Ce projet est reussi si le modele apporte une amelioration du profil de risque hors echantillon, pas seulement une belle accuracy.

---

# Projet 6 - Crypto risk-on / risk-off BTC/ETH

## Resume

Ce projet applique la logique quantitative a une petite poche crypto. Il ne s'agit pas de faire du trading agressif, mais de gerer l'exposition a BTC/ETH selon la tendance et la volatilite.

## Objectif

Construire une strategie prudente qui decide quand etre exposee a BTC/ETH et quand rester en cash.

## Univers de depart

- BTC.
- ETH.
- Cash.

Pas d'altcoins au debut.

## Strategie simple

Regle :

```text
Si BTC > moyenne mobile 200 jours et momentum 90 jours positif :
    exposition crypto autorisee
Sinon :
    cash
```

Allocation prudente :

```text
70 % BTC
30 % ETH
```

Mais cette poche ne doit representer qu'une petite partie du patrimoine total.

## Taille de poche recommandee au debut

- Paper trading : 100 % fictif.
- Puis eventuellement 1 % a 3 % du patrimoine.
- Maximum experimental initial : 5 %.

## Fichiers a creer

- `notebooks/07_crypto_risk_on_off.ipynb`
- `src/crypto_signals.py`
- fonctions supplementaires dans `src/backtest.py`

## Etape 6.1 - Telecharger les donnees

Sources possibles :

- `yfinance` pour demarrer simplement avec `BTC-USD` et `ETH-USD`.
- `ccxt` plus tard pour donnees d'exchanges.

## Etape 6.2 - Calculer les features

Features :

- return 30 jours ;
- return 90 jours ;
- volatilite 30 jours ;
- moyenne mobile 200 jours ;
- distance a la MA200 ;
- drawdown courant.

## Etape 6.3 - Construire les signaux

```python
def trend_signal(price, moving_average):
    return price > moving_average


def momentum_signal(price, window=90):
    return price.pct_change(window) > 0
```

## Etape 6.4 - Backtester

Comparer :

- Buy & hold BTC.
- Buy & hold 70/30 BTC/ETH.
- Risk-on/risk-off BTC.
- Risk-on/risk-off BTC/ETH.
- Risk-on/risk-off + volatility targeting.

## Etape 6.5 - Simuler l'effet patrimonial

Tester :

```text
95 % portefeuille classique + 5 % crypto risk-managed
90 % portefeuille classique + 10 % crypto risk-managed
```

## Points de vigilance

- La crypto peut perdre 70 % ou plus.
- Les plateformes peuvent presenter des risques operationnels.
- Les frais et spreads peuvent etre importants.
- La fiscalite doit etre suivie proprement.
- Pas de levier.
- Pas de bot d'execution.

## Checklist

- [x] La strategie est testee sans levier.
- [x] La poche crypto est limitee. (simulations 5 % et 10 %)
- [x] Les drawdowns sont analyses.
- [x] Les frais sont inclus. (0,25 % par unité de turnover)
- [x] L'impact sur le portefeuille global est simule.
- [x] La decision reste manuelle. (recherche uniquement, non branchée sur le rapport mensuel)

## Critere de validation

Ce projet est utile si la poche crypto ameliore le couple rendement/risque du portefeuille global sans augmenter le drawdown a un niveau psychologiquement inacceptable.

---

# Finalité patrimoniale du projet

L'objectif final ne consiste pas uniquement à produire de beaux backtests. Il s'agit de construire progressivement un **système d'aide à la décision** pour répartir l'épargne entre plusieurs usages :

- cœur long terme en PEA ;
- diversification éventuelle en compte-titres (CTO) ;
- poche de sécurité et liquidités ;
- éventuelle exposition obligataire ou monétaire ;
- petite poche crypto satellite ;
- versements périodiques ;
- contrôle du risque global ;
- arbitrages validés manuellement.

Pour devenir réellement utile, le projet devra ultérieurement intégrer :

- la fiscalité propre à chaque enveloppe ;
- les frais réels ;
- les contraintes de liquidité ;
- l'horizon d'investissement ;
- le montant d'épargne disponible ;
- la tolérance personnelle au drawdown ;
- les projets nécessitant du capital à court ou moyen terme.

« Le système génère des informations et des propositions d'allocation. La décision finale reste humaine tant que les phases de validation et de paper trading ne sont pas terminées. »

---

# Extensions futures — Backlog produit

> **Ces extensions ne doivent pas être commencées avant que les Projets 2, 3 et 4 soient suffisamment stables.**

Elles sont documentées ici uniquement pour ne pas être oubliées. Ce ne sont pas des tâches immédiates et elles ne sont pas encore implémentées.

## Projet 7 — Allocation patrimoniale multi-enveloppes

Objectif :

- combiner PEA, CTO, liquidités et crypto ;
- définir une allocation cible globale ;
- intégrer les versements mensuels ;
- intégrer les limites de risque par enveloppe ;
- simuler plusieurs profils : prudent, équilibré, dynamique ;
- comparer la stratégie à une allocation passive simple.

Livrables possibles :

- `src/wealth_allocation.py`
- `notebooks/08_global_allocation.ipynb`
- rapport d'allocation patrimoniale ;
- journal des versements et arbitrages.

La décision finale doit rester manuelle.

## Projet 8 — Automatisation open source

Objectif : automatiser uniquement les tâches répétitives :

- téléchargement des données ;
- validation de qualité ;
- recalcul des signaux ;
- génération du rapport mensuel ;
- archivage des résultats ;
- création d'alertes en cas d'échec.

Progression recommandée :

1. Script CLI local.
2. Planification Windows Task Scheduler ou cron.
3. Orchestrateur Python open source si nécessaire.
4. Hébergement sur un petit serveur ou une machine personnelle.
5. Monitoring et journalisation des exécutions.

Outils à évaluer plus tard (ne pas tout installer, en choisir **un seul** quand le besoin sera réel) :

- Prefect ;
- Dagster ;
- APScheduler ;
- GitHub Actions pour certains contrôles non sensibles ;
- Docker pour rendre les exécutions reproductibles.

Fonctions attendues à terme :

- planification mensuelle ou quotidienne ;
- retries contrôlés ;
- logs ;
- statut d'exécution ;
- alerte en cas de données absentes ;
- historique des rapports ;
- impossibilité de déclencher silencieusement des ordres réels.

## Projet 9 — Notifications

Objectif : recevoir une information uniquement lorsqu'un événement significatif se produit.

Exemples :

- nouveau rapport mensuel disponible ;
- changement de l'actif sélectionné ;
- passage en régime défensif ;
- dépassement d'un seuil de volatilité ;
- drawdown anormal ;
- échec du téléchargement des données ;
- incohérence ou donnée manquante.

Solutions à étudier :

- ntfy ;
- e-mail ;
- notification locale ;
- webhook ;
- notification push via la future application.

Règles :

- éviter les notifications quotidiennes inutiles ;
- ne pas notifier une microvariation ;
- distinguer information, avertissement et erreur ;
- ne jamais transformer une notification en ordre automatique au début ;
- conserver une trace de chaque alerte envoyée.

Trois niveaux à prévoir :

- INFO ;
- WARNING ;
- CRITICAL.

## Projet 10 — Application iPhone

Objectif : créer une application Apple permettant de consulter les résultats du laboratoire quantitatif.

Architecture envisagée :

- moteur quantitatif Python séparé ;
- API de lecture entre le moteur et l'application ;
- application iOS en Swift et SwiftUI ;
- authentification locale ou sécurisée ;
- données en lecture seule au début.

Écrans possibles :

- tableau de bord ;
- allocation actuelle ;
- allocation cible ;
- signaux ;
- performance ;
- drawdown ;
- rapport mensuel ;
- journal de décision ;
- historique des alertes.

La première version ne doit contenir **aucune exécution d'ordre**.

## Projet 11 — Widget Apple

Objectif : afficher sur l'écran d'accueil une information concise et utile.

Informations possibles :

- état de la stratégie ;
- actif sélectionné ;
- exposition cible ;
- niveau de risque ;
- date du dernier calcul ;
- statut du pipeline ;
- prochaine date de révision.

Exemples de texte :

- « Momentum positif — exposition 75 % »
- « Régime défensif — exposition réduite »
- « Rapport mensuel disponible »
- « Données non actualisées — vérification nécessaire »

Contraintes à documenter :

- le widget ne doit pas être considéré comme une source temps réel garantie ;
- afficher systématiquement la date et l'heure de dernière actualisation ;
- ne pas afficher de bouton d'achat ou de vente dans la première version ;
- ouvrir l'application pour consulter le détail ;
- prévoir un état explicite lorsque les données sont anciennes.

Technologies Apple à étudier ultérieurement :

- SwiftUI ;
- WidgetKit ;
- App Intents ;
- BackgroundTasks ;
- notifications push.

## Projet 12 — Automatisation encadrée des ordres (option très lointaine)

Ce projet est **facultatif et non prioritaire**.

Conditions préalables obligatoires :

- stratégie robuste ;
- paper trading suffisamment long ;
- logs complets ;
- gestion des erreurs ;
- validation des frais ;
- limites de montant ;
- kill switch ;
- approbation humaine ;
- conformité avec les règles du courtier ;
- aucune clé secrète dans le dépôt ;
- environnement de simulation séparé.

Progression éventuelle :

1. génération d'une proposition d'ordre ;
2. validation humaine ;
3. génération d'un fichier ou formulaire ;
4. éventuellement API de courtier en sandbox ;
5. jamais d'exécution totalement autonome avant une validation approfondie.

## Architecture cible à long terme

```text
Sources de données
      |
      v
Data loader et validation
      |
      v
Features et signaux
      |
      v
Backtest / allocation / risque
      |
      v
Rapport et base de résultats
      |
      +-------------------+
      |                   |
      v                   v
Notifications         API en lecture
                          |
                          v
                  Application iPhone
                          |
                          v
                    Widget Apple
```

Le moteur Python doit rester **indépendant** de l'application mobile : l'application ne fait que lire des résultats déjà calculés, elle ne recalcule rien et ne déclenche aucun ordre.

---

# Règle anti-dispersion

- une seule phase active à la fois ;
- aucune application mobile avant le rapport mensuel ;
- aucune notification avant la stabilisation des signaux ;
- aucun ML avant la validation du Momentum ;
- aucun ordre automatique avant le paper trading ;
- chaque projet doit respecter sa Definition of Done ;
- chaque phase doit se terminer par tests, documentation et commit Git.

« Les idées futures sont conservées dans ce backlog afin de ne pas les oublier, mais elles ne constituent pas des tâches immédiates. »

---

# Roadmap detaillee sur 12 semaines

## Semaine 1 - Installation et structure

Objectif : repo propre.

A faire :

- [ ] Creer le dossier projet.
- [ ] Creer l'environnement virtuel.
- [ ] Installer les librairies.
- [ ] Creer l'arborescence.
- [ ] Creer `README.md`.
- [ ] Creer `assets.yaml`.
- [ ] Faire un premier commit Git.

Livrable : repo VS Code pret.

## Semaine 2 - Donnees

Objectif : telecharger et sauvegarder les donnees.

A faire :

- [ ] Coder `data_loader.py`.
- [ ] Telecharger les prix des ETF.
- [ ] Sauvegarder en CSV ou Parquet.
- [ ] Gerer les valeurs manquantes.
- [ ] Creer un notebook d'exploration.

Livrable : dataset local propre.

## Semaine 3 - Metriques

Objectif : mesurer correctement une strategie.

A faire :

- [ ] Coder les rendements.
- [ ] Coder CAGR.
- [ ] Coder volatilite.
- [ ] Coder Sharpe.
- [ ] Coder Sortino.
- [ ] Coder max drawdown.
- [ ] Ajouter des tests unitaires.

Livrable : `metrics.py` fiable.

## Semaine 4 - Benchmark

Objectif : creer la reference passive.

A faire :

- [ ] Backtester buy & hold ETF World.
- [ ] Afficher courbe de capital.
- [ ] Afficher drawdown.
- [ ] Sauvegarder resultats.
- [ ] Rediger conclusion.

Livrable : benchmark officiel du projet.

## Semaine 5 - Momentum v1

Objectif : premiere strategie active.

A faire :

- [ ] Calculer momentum 12 mois.
- [ ] Calculer moyenne mobile 10 mois.
- [ ] Selectionner meilleur actif.
- [ ] Decaler le signal d'un mois.
- [ ] Backtester.

Livrable : premier backtest momentum.

## Semaine 6 - Robustesse momentum

Objectif : verifier que la strategie n'est pas fragile.

A faire :

- [ ] Tester plusieurs lookbacks.
- [ ] Tester plusieurs moyennes mobiles.
- [ ] Ajouter frais.
- [ ] Ajouter turnover.
- [ ] Comparer au benchmark.
- [ ] Rediger rapport.

Livrable : rapport momentum robuste.

## Semaine 7 - Volatility targeting

Objectif : controler l'exposition.

A faire :

- [ ] Calculer volatilite realisee.
- [ ] Calculer exposition cible.
- [ ] Plafonner a 100 %.
- [ ] Combiner avec momentum.
- [ ] Comparer les resultats.

Livrable : strategie defensive complete.

## Semaine 8 - Rapport mensuel

Objectif : rendre le projet utilisable.

A faire :

- [ ] Coder `reporting.py`.
- [ ] Generer un rapport Markdown.
- [ ] Ajouter graphiques.
- [ ] Ajouter allocation cible.
- [ ] Ajouter commentaire automatique.

Livrable : premier rapport mensuel automatique.

## Semaine 9 - Dataset ML

Objectif : preparer le machine learning.

A faire :

- [ ] Construire features mensuelles.
- [ ] Creer cible rendement futur 3 mois.
- [ ] Faire split train/validation/test temporel.
- [ ] Documenter les risques de leakage.

Livrable : dataset ML propre.

## Semaine 10 - Modele ML v1

Objectif : premier modele interpretable.

A faire :

- [ ] Logistic regression.
- [ ] Random forest simple.
- [ ] Evaluation ML.
- [ ] Evaluation financiere.
- [ ] Feature importance.

Livrable : premier modele regimes de marche.

## Semaine 11 - Crypto

Objectif : ajouter BTC/ETH prudemment.

A faire :

- [ ] Telecharger BTC/ETH.
- [ ] Creer signaux MA200 + momentum.
- [ ] Backtester risk-on/risk-off.
- [ ] Tester allocation 5 % et 10 %.
- [ ] Documenter les risques.

Livrable : module crypto experimental.

## Semaine 12 - Synthese

Objectif : choisir une strategie a suivre en paper trading.

A faire :

- [ ] Comparer toutes les strategies.
- [ ] Rediger limites.
- [ ] Choisir une strategie principale.
- [ ] Creer un rapport final.
- [ ] Nettoyer le README.
- [ ] Preparer une presentation eventuelle pour CV/entretien.

Livrable : rapport final + strategie paper trading.

---

# Definition of Done generale

Une phase est terminee seulement si :

- [ ] Le code fonctionne de bout en bout.
- [ ] Les fonctions critiques sont dans `src/`, pas uniquement dans un notebook.
- [ ] Les donnees sont sauvegardees localement.
- [ ] Les resultats sont reproductibles.
- [ ] Les frais sont inclus quand necessaire.
- [ ] Les signaux sont correctement decales.
- [ ] La strategie est comparee a un benchmark.
- [ ] Les limites sont documentees.
- [ ] Le README est mis a jour.
- [ ] Un commit Git a ete fait.

---

# Journal de decision mensuel

A copier dans chaque rapport mensuel.

```markdown
# Journal de decision - AAAA-MM

## Strategie suivie

## Signal actuel

## Allocation cible

## Allocation actuelle

## Ecart a corriger

## Arguments pour agir

## Arguments contre agir

## Risques identifies

## Decision finale

## Emotion / niveau de confiance

## Ce que je verifierai le mois prochain
```

Pourquoi c'est utile : ce journal t'oblige a separer le signal quantitatif de ta psychologie du moment.

---

# Prompts utiles pour Claude Code ou Codex

## Prompt 1 - Creer la structure du projet

```text
Create a clean Python project structure for a personal quantitative investment lab.

The project should include:
- data loading
- feature engineering
- signal generation
- monthly backtesting
- performance metrics
- reporting
- unit tests

Use pandas, numpy, matplotlib, yfinance and scikit-learn.
Add type hints, docstrings and a clear README.
Do not implement trading execution.
```

## Prompt 2 - Verifier les biais du backtest

```text
Review this backtest code for financial backtesting biases.

Focus especially on:
- look-ahead bias
- survivorship bias
- data leakage
- wrong signal shifting
- unrealistic transaction costs
- incorrect benchmark comparison
- overfitting risks

Explain each issue clearly and suggest corrections.
```

## Prompt 3 - Refactoriser un notebook

```text
Refactor this Jupyter notebook into clean Python modules.

Create:
- data_loader.py
- features.py
- signals.py
- backtest.py
- metrics.py
- plotting.py

Keep the notebook only for exploration.
Add unit tests for the metrics.
```

## Prompt 4 - Generer un rapport mensuel

```text
Create a Python function that generates a monthly Markdown report for a quantitative strategy.

The report should include:
- current date
- selected asset
- current signal
- target allocation
- performance metrics
- drawdown
- benchmark comparison
- warnings and limitations
```

## Prompt 5 - Creer des tests unitaires

```text
Write pytest unit tests for the financial metrics module.

Test:
- returns calculation
- annualized return
- annualized volatility
- Sharpe ratio
- max drawdown

Use small deterministic arrays where the expected result can be calculated manually.
```

---

# Lab v5 — profil, plans d'investissement et refonte du tableau de bord

- **Profil investisseur** (`main.py profile --questionnaire`, page « Mon profil ») : situation,
  objectif, horizon, réaction à une baisse, temps disponible, zones, options, enveloppes.
  Fichier personnel `config/profil.yaml`.
- **Plans d'investissement** (`main.py plans`, page « Plans ») : sept plans types sur PEA,
  assurance-vie, CTO et crypto, projetés par bootstrap (frais, fiscalité par enveloppe,
  inflation, scénario prudent), rejoués sur le vrai passé et confrontés au profil.
- **Fiches de stratégies** (`main.py strategies`) et **robustesse** (`main.py robustness`) :
  verdicts de fiabilité, de surperformance et de protection, corrigés des tests multiples.
- **Tableau de bord** repensé : accueil, navigation en cinq sections, thème clair et sombre.

Rien de tout cela ne passe d'ordre ni ne modifie la stratégie suivie.

# Checklist avant toute utilisation avec argent reel

Avant de placer meme une petite somme selon le systeme :

- [ ] La strategie a ete testee sur plusieurs periodes.
- [ ] Le benchmark est battu ou complete de facon utile.
- [ ] Le drawdown est acceptable.
- [ ] Les frais sont inclus.
- [ ] La fiscalite est comprise.
- [ ] Le volume et la liquidite sont suffisants.
- [ ] Le systeme ne depend pas d'un seul parametre magique.
- [ ] La strategie a ete suivie en paper trading pendant au moins 3 mois.
- [ ] Le montant engage est faible au debut.
- [ ] La decision finale reste humaine.

---

# Sources et outils de donnees utiles

Ces ressources sont a utiliser pour la recherche, le backtesting et l'apprentissage. Il faut toujours verifier les conditions d'utilisation et les limites de chaque source.

## yfinance

Usage : prix historiques Yahoo Finance pour recherche et education.  
Lien : https://ranaroussi.github.io/yfinance/  
Attention : yfinance n'est pas une API officielle de Yahoo Finance et ne doit pas etre consideree comme une source professionnelle garantie.

## FRED API

Usage : donnees macroeconomiques, taux, inflation, chomage, indicateurs economiques.  
Lien : https://fred.stlouisfed.org/docs/api/fred/

## Stooq

Usage : historiques CSV gratuits pour certains marches.  
Lien : https://stooq.com/db/h/

## CCXT

Usage : donnees crypto et interfaces uniformisees vers des exchanges.  
Lien : https://docs.ccxt.com/

## vectorbt

Usage : backtesting vectorise rapide avec pandas/NumPy.  
Lien : https://vectorbt.dev/

## backtesting.py

Usage : backtesting plus simple et pedagogique.  
Lien : https://kernc.github.io/backtesting.py/

---

# Strategie finale recommandee pour demarrer

Ne pars pas directement sur un modele ML complexe. La trajectoire la plus rationnelle est :

```text
1. Buy & hold benchmark
2. Momentum defensif PEA
3. Volatility targeting
4. Rapport mensuel
5. ML regime de marche
6. Crypto satellite
```

La premiere strategie exploitable a construire est :

```text
Momentum defensif PEA + controle de volatilite
```

Pourquoi :

- Elle est comprehensible.
- Elle est codable.
- Elle est testable.
- Elle est compatible avec une logique long terme.
- Elle n'a pas besoin de predire les prix exactement.
- Elle t'apprend les bases importantes de la finance quantitative.

---

# Prochaine action immediate

Le socle (Projet 0) et le cœur du benchmark (Projet 1) sont déjà en place. La suite n'est donc plus de créer le projet depuis zéro, mais de fermer le jalon en cours puis de démarrer le Momentum.

1. **Fermer le jalon Projets 0 et 1 :**
   - vérifier Git (`git status`, `git diff`) ;
   - exécuter les tests (`python -m pytest -q`) ;
   - exécuter le notebook Buy & Hold de bout en bout ;
   - documenter la conclusion du benchmark ;
   - faire un commit dédié.
2. **Commencer le Projet 2 :**
   - définir précisément l'univers ETF PEA ;
   - créer `src/features.py` ;
   - coder les données mensuelles ;
   - coder le momentum ;
   - coder la moyenne mobile ;
   - créer des tests simples ;
   - ne pas encore coder tout le backtest Momentum en une seule fois.

« La prochaine session de développement doit exclusivement porter sur les premières features du Momentum défensif PEA. »

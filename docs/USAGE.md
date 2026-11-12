# Mode d'emploi — personal-quant-lab

Guide pratique pour installer, lancer et utiliser le laboratoire chaque mois.

> **Rappel** : outil éducatif et de paper trading. Aucune commande ne passe d'ordre.
> Les propositions d'allocation ne sont pas des conseils en investissement ; la
> décision reste toujours humaine.

Toutes les commandes se lancent **depuis la racine du projet**, dans PowerShell :

```powershell
cd "C:\Users\degar\OneDrive - De Vinci Higher Education (DVHE)\Perso\Projet Investissement\personal-quant-lab"
```

Les exemples utilisent `.venv\Scripts\python.exe`. Tu peux aussi activer l'environnement
une fois par session (`.venv\Scripts\Activate.ps1`) puis taper simplement `python main.py ...`.

---

## 1. Installation (une seule fois)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

Le script crée `.venv` si besoin, installe `requirements-dev.txt`, enregistre le noyau
Jupyter « Python (quant-lab) » et lance les tests. Si le dossier du projet a été déplacé
et que `.venv` ne fonctionne plus : `scripts\setup.ps1 -Recreate`.

Installation manuelle équivalente :

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

- `requirements.txt` : moteur et CLI uniquement.
- `requirements-dev.txt` : + tests, notebooks, tableau de bord, lint.

## 2. Premier lancement

```powershell
.venv\Scripts\python.exe main.py status
```

`status` indique la fraîcheur des données, le dernier rapport, les décisions en attente
et **les prochaines commandes à lancer**. C'est le bon point de départ à chaque session.

Fichiers personnels (facultatifs, jamais versionnés) à créer depuis leurs modèles :

```powershell
Copy-Item config\positions.example.yaml config\positions.yaml   # parts détenues (plan de versement)
Copy-Item config\holdings.example.yaml config\holdings.yaml     # valeurs des livrets / autres enveloppes
Copy-Item config\notify.example.yaml config\notify.yaml         # notifications ntfy (désactivées)
```

Renseigne aussi le **barème de ton courtier** dans `config/strategy_params.yaml > costs`
(forfait, minimum par ordre) : il sert au plan de versement et à la simulation DCA.

Puis décris ta situation et tes préférences (une fois, à revoir chaque année) :

```powershell
.venv\Scripts\python.exe main.py profile --questionnaire   # ou la page « Mon profil » du tableau de bord
.venv\Scripts\python.exe main.py plans                     # plans d'investissement simulés pour ce profil
```

## 3. Routine mensuelle (≈ 10 minutes, entre le 1er et le 5 du mois)

Le signal officiel utilise le **dernier mois civil complet** : lance la routine en début
de mois, une fois le mois précédent clôturé.

1. **Générer le mois** (télécharge les prix, calcule, écrit le rapport, crée l'entrée
   du journal, compare avec le mois précédent ; `--html` produit aussi un résumé d'une page
   pour le téléphone, `reports/monthly/YYYY-MM-resume.html`, personnel) :

   ```powershell
   .venv\Scripts\python.exe main.py run-month --refresh-data --html
   ```

   Le rapport suit la stratégie de ta **politique d'investissement** (`config/policy.yaml`,
   §8 bis) et compare toutes les stratégies du registre.

2. **Lire le rapport** `reports/monthly/YYYY-MM-report.md` (ou le tableau de bord, §6) :
   statut, alertes, allocation cible, graphiques.
3. **Remplir le journal de décision** en bas du rapport (arguments pour/contre, émotion,
   ce que tu vérifieras le mois prochain).
4. **Enregistrer la décision fictive** (la commande exacte est affichée par `run-month`),
   avec les champs du journal de décision :

   ```powershell
   .venv\Scripts\python.exe main.py paper-decision --month 2026-10 --status APPROVED_PAPER --strategy allocation_fixe --confidence 4 --pros "plan simple et diversifié" --cons "subit les baisses du marché" --next-check "régularité des versements" --comment "Politique Monde + émergents"
   ```

   Statuts : `PENDING`, `APPROVED_PAPER`, `REJECTED`, `SKIPPED`, `NEEDS_REVIEW`.
   Stratégies : toutes celles du registre (`benchmark`, `momentum`, `momentum_vt`,
   `inverse_vol`, `static_80_20`, `static_60_40`, `dual_momentum`, `top3_trend`,
   `core_satellite`). Confiance : 1 (faible) à 5 (forte).
5. **Préparer le versement du mois** (proposition d'achats en parts entières, frais inclus,
   sans vente, à partir de tes positions et de la dernière décision approuvée ; si une part
   du véhicule préféré dépasse le budget, bascule vers un ETF de même exposition, ex.
   CW8.PA → WPEA.PA) :

   ```powershell
   .venv\Scripts\python.exe main.py plan-contribution --record
   ```

   Le plan est écrit dans `reports/contributions/YYYY-MM-plan.md` (non versionné) ; `--record`
   ajoute les achats proposés à `config/pending_orders.csv` (statut `PROPOSE`). **Aucun ordre
   n'est passé** : saisis toi-même les ordres chez ton courtier, puis reporte les ordres
   **réellement exécutés** (prix et frais réels) dans `config/transactions.csv` (§8 ter).
6. **Suivre le portefeuille réel** : `main.py portfolio` (valeur, TRI, TWR, frais, jalons du
   PEA) et `main.py patrimoine` (le PEA est valorisé à partir du journal).
7. **Suivre la valeur de tes décisions** : `main.py paper-performance` compare tes choix à la
   proposition du système et au Buy & Hold (aussi affiché par `run-month`).
8. Vérifier que tout est à jour : `main.py status` doit afficher « Rien à faire ».

La règle du guide impose **au moins 3 mois de journal renseigné** avant d'envisager
l'argent réel ; `status` affiche le compteur.

## 4. Référence des commandes

| Commande | Rôle | Exemple |
| -------- | ---- | ------- |
| `status` | État du lab et prochaines actions | `main.py status` |
| `run-month` | Routine complète : rapport + entrée du journal + comparaison + performance paper | `main.py run-month --refresh-data --html --notify` |
| `monthly-report` | Rapport seul (Markdown + JSON + graphiques, `--html` pour un HTML autonome) | `main.py monthly-report --report-date 2026-06-30` |
| `refresh-data` | Mise à jour **incrémentale** des prix, contrôles qualité, archive brute (`--full` : tout retélécharger ; `--long` : historique long par proxys) | `main.py refresh-data --long` |
| `paper-performance` | Performance fictive de mes décisions vs système vs benchmark | `main.py paper-performance` |
| `plan-contribution` | Proposition d'achats du versement (parts entières, frais, sans vente) ; suit l'allocation fixe de la politique ; `--frequency N` : achat tous les N mois (réglage permanent : `patrimoine.yaml > profil > frequence_achat_mois`), `--month AAAA-MM` | `main.py plan-contribution --frequency 2` |
| `costs` | Sensibilité des stratégies aux frais (0,10 / 0,20 / 0,30 % et barème réel) | `main.py costs` |
| `research` | Robustesse : grille walk-forward, stratégies alternatives, intervalles de confiance (`--long` : historique long) | `main.py research --portfolio 10000` |
| `policy` | Politique d'investissement et contrôles informatifs | `main.py policy` |
| `portfolio` | Portefeuille réel depuis `transactions.csv` : TWR, TRI, frais, PEA (rapport personnel) | `main.py portfolio` |
| `vehicles` | Expositions, véhicules achetables, écart de suivi des proxys | `main.py vehicles` |
| `stress` | Crises 2008-2022 et distribution des versements sur l'horizon (historique long) | `main.py stress --sims 2000` |
| `profile` | Profil investisseur : questionnaire (`--questionnaire`), repères indicatifs | `main.py profile --questionnaire` |
| `plans` | Plans d'investissement simulés pour le profil (projection, vrai passé, adéquation, sensibilité) ; `--scenario historique\|central\|defavorable` (`--prudent` = défavorable), `--monthly`, `--years`, `--goal`, `--only` | `main.py plans --scenario defavorable` |
| `frais` | Audit des frais : ordres réels du plan de versement, frais des ETF, fiscalité PEA vs compte-titres, comparaison de barèmes (rapport personnel) | `main.py frais` |
| `rendement-max` | Gains et pertes possibles d'options plus risquées (Nasdaq, momentum concentré, levier x2), dans les trois scénarios (pédagogique) | `main.py rendement-max` |
| `universe` | Identité des ETF (ISIN vérifié, frais, éligibilité PEA, date de vérification) et points d'attention | `main.py universe` |
| `strategies` | Fiches détaillées des stratégies (mécanisme, temps, forces, faiblesses, mesures, crises) | `main.py strategies` |
| `robustness` | Verdicts de fiabilité, surperformance et protection sur historique long | `main.py robustness` |
| `paper-init` | Crée une entrée de journal depuis un snapshot | `main.py paper-init --snapshot reports/monthly/2026-09-report.json` |
| `paper-list` | Liste le journal | `main.py paper-list` |
| `paper-decision` | Enregistre la décision humaine (fictive) | voir §3 |
| `compare-reports` | Compare deux rapports | `main.py compare-reports --from 2026-07 --to 2026-09` |
| `patrimoine` | Rapport patrimonial (enveloppes, dérive, projections) | `main.py patrimoine` |
| `dca` | Simulation des versements mensuels (Projet 1B) | `main.py dca --monthly 400 --start 2020-01-31` |
| `regime` | Étude ML des régimes de marché (Projet 5) | `main.py regime` |
| `validate` | Vérifie `config/strategy_params.yaml` | `main.py validate` |

Options utiles : `--report-date YYYY-MM-DD` rejoue une date passée sans aucune donnée
postérieure ; `--data`, `--assets`, `--config`, `--output-dir`, `--paper-dir` changent
les fichiers utilisés ; `--html` (rapport) exporte un fichier HTML autonome lisible sur
téléphone ; `--notify` (run-month) envoie les notifications si elles sont activées.
`main.py <commande> --help` liste toutes les options.

### Codes de sortie

| Code | Signification |
| ---- | ------------- |
| 0 | Succès (rapport sans alerte critique) |
| 1 | Erreur technique ou commande mal saisie |
| 2 | Rapport généré mais statut `CRITICAL` : lire les alertes avant toute décision |

## 5. Lire le rapport mensuel

- **Statut du pipeline** : `OK`, `OK_WITH_WARNINGS` (à lire) ou `CRITICAL` (validation
  humaine obligatoire, par exemple données de plus de 30 jours).
- **Date du signal** : dernier mois complet. Le mois en cours est exclu (alerte
  `PARTIAL_MONTH`, normale en milieu de mois).
- **Allocation actuelle théorique** : allocation cible de la stratégie suivie
  (Momentum + VT par défaut). La part `CASH` est explicite ; elle est rémunérée au
  rendement du fonds monétaire CSH2.PA quand il est disponible.
- **Graphiques** : capital théorique, drawdown, allocation dans le temps, volatilité.

Alertes les plus fréquentes :

| Code | Niveau | Que faire |
| ---- | ------ | --------- |
| `STALE_DATA` | WARNING / CRITICAL | Relancer avec `--refresh-data` |
| `UNIVERSE_MISMATCH` | WARNING | Un ticker d'`assets.yaml` n'a pas de prix : `main.py refresh-data` |
| `ASSET_EXCLUDED` | WARNING | Historique trop court (< 34 mois) : normal pour WPEA.PA et GWT.PA |
| `REDUCED_EXPOSURE` / `FULL_CASH` | WARNING | Le VT réduit fortement l'exposition : vérifier la volatilité |
| `HIGH_VOLATILITY` / `HIGH_DRAWDOWN` | WARNING | Marché agité : relire les arguments contre agir |
| `DATA_ANOMALY` | WARNING | Saut > 15 %, ticker figé ou trou de cotation récent : vérifier la source, relancer `refresh-data --full` si besoin |
| `PARTIAL_MONTH`, `DATA_NOT_REFRESHED` | INFO | Informatif |

Le snapshot JSON (`YYYY-MM-report.json`) est décrit dans
[snapshot_schema.md](snapshot_schema.md).

## 6. Tableau de bord

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dashboard.ps1
# ou
.venv\Scripts\python.exe -m streamlit run app\dashboard.py
```

S'ouvre sur http://localhost:8501 (thème clair ou sombre selon le système ; bascule dans le
menu ⋮ > Settings). La barre latérale indique la fraîcheur des données et les actions à faire.

| Section | Pages |
| ------- | ----- |
| Accueil | Chiffres clés, actions du mois, allocation proposée, tes trois plans les mieux adaptés |
| Ce mois-ci | Rapport du mois, Plan de versement, Journal de décision |
| Mon argent | Portefeuille réel, Patrimoine, Performance paper |
| Construire mon plan | **Mon profil** (questionnaire), **Plans d'investissement** (simulation en direct : change le versement, l'horizon, l'objectif ou active le scénario prudent sans modifier ton profil), **Stratégies** (fiches) |
| Laboratoire | Robustesse, Recherche, Stress tests, Historique, Politique |

Le tableau de bord ne passe aucun ordre. Il n'écrit qu'un seul fichier : ton profil
(`config/profil.yaml`, personnel) quand tu enregistres le questionnaire. Les autres pages
lisent les fichiers produits par la CLI : après un `run-month`, un `robustness` ou un
`stress`, recharge la page. `Ctrl+C` dans le terminal pour l'arrêter.

## 7. Notebooks

```powershell
.venv\Scripts\python.exe -m jupyter lab
```

Choisir le noyau « Python (quant-lab) ». Notebooks de recherche : `02` benchmark, `03`
momentum, `04` volatility targeting, `05` rapport mensuel, `06` paper trading, `07` / `07b`
univers et rôles, `08` patrimoine, `09` ML régimes, `10` crypto risk-on / risk-off (recherche,
télécharge BTC-EUR / ETH-EUR au premier lancement), `11` robustesse des stratégies. Exécution non interactive :

```powershell
.venv\Scripts\python.exe -m nbconvert --to notebook --execute --inplace notebooks\09_market_regime_ml.ipynb
```

## 8. Configuration

| Fichier | Contenu |
| ------- | ------- |
| `config/assets.yaml` | Univers ETF : `ticker`, `universe_active`, `role` (`candidate` / `defensive` / `cash_proxy`) |
| `config/strategy_params.yaml` | Momentum (12-1, MA10, top 1), VT (cible 10 %, fenêtre 3 mois), frais du backtest (0,10 %), barème réel `costs`, section `universe` |
| `config/patrimoine.yaml` | Profil (horizon, versement mensuel, tolérance, inflation), `fiscalite`, enveloppes, allocation cible |
| `config/positions.yaml` | **Tes parts détenues** par enveloppe et liquidités (non versionné ; modèle `positions.example.yaml`) |
| `config/holdings.yaml` | **Tes valeurs** des autres enveloppes (non versionné ; modèle `holdings.example.yaml`) |
| `config/notify.yaml` | Notifications ntfy (non versionné ; modèle `notify.example.yaml`, `enabled: false`) |
| `config/policy.yaml` | **Ta politique d'investissement** : stratégie suivie, cœur/satellite, drawdown maximal accepté (§8 bis) |
| `config/transactions.csv` | **Tes opérations réelles** (non versionné ; modèle `transactions.example.csv`, §8 ter) |
| `config/long_history.yaml` | Chaînes de proxys de l'historique long (recherche uniquement, §8 quater) |

Frais réels (`costs`) : `frais d'un ordre = max(minimum_per_order, fixed_per_order + proportional × montant) + demi-spread`.
Avec un forfait, un petit versement coûte proportionnellement cher : `main.py costs` et
`main.py dca` en montrent l'effet.

Fiscalité (`fiscalite`, simplifiée, pas un conseil fiscal) : PEA de plus de 5 ans =
prélèvements sociaux 18,6 % (taux 2026) sur le gain au retrait ; avant 5 ans, CTO et crypto = prélèvement forfaitaire 31,4 % ; assurance-vie : 17,2 % (épargnée par la hausse de 2026).
Les rapports DCA, patrimoine et crypto affichent des valeurs nettes d'impôt.

Section `universe` de `strategy_params.yaml` :

- `defensive_as_candidates: true` : l'obligataire (OBLI.PA) est classé avec les actions
  (comportement historique). `false` : actions seules.
- `use_cash_proxy_return: true` : la poche cash est rémunérée au rendement de CSH2.PA.

Après toute modification : `main.py validate`, puis `main.py run-month`.

## 8 bis. Politique d'investissement (`config/policy.yaml`)

La politique est **ton choix** : le laboratoire la lit, ne la modifie jamais.

- `strategie_suivie` : stratégie du registre suivie par le rapport, le journal, le plan de
  versement et le tableau de bord (défaut `momentum_vt` ; choix actuel : `allocation_fixe`) ;
- `allocation_fixe` : si `strategie_suivie: allocation_fixe`, poids cibles fixes (somme = 1),
  par exemple `CW8.PA: 0.85` et `PAEEM.PA: 0.15` (plan « Monde + émergents »). Le plan de
  versement utilise alors **directement** cette allocation (pas besoin du journal) et achète
  WPEA.PA quand une part de CW8.PA dépasse le budget ; `plan_suivi` rappelle le plan choisi ;
- `regle_krach` : `texte` (ton engagement, écrit à froid et avec tes mots) et `seuil_baisse`
  (ex. 0.30). La règle figure dans chaque rapport, le résumé HTML, la page Politique et
  l'accueil du tableau de bord ; au-delà du seuil de baisse de la stratégie suivie, une alerte
  `CRASH_RULE` te demande de la relire avant toute décision ;
- `coeur_satellite` : si `strategie_suivie: core_satellite`, part cœur en Buy & Hold et
  stratégie satellite (ex. 80 % benchmark + 20 % momentum_vt) ;
- `drawdown_max_accepte` : baisse maximale supportable (ex. 0.25) ;
- `reequilibrage` (`mensuel` / `bandes`), `bande_tolerance_pct`, `revue`.

Avant de la changer : lis `reports/research/strategy_research_report.md` (données réelles
depuis 2019), `strategy_research_report_long.md` et `stress_report.md` (historique long,
partiellement synthétique), puis `main.py policy` affiche les contrôles (limite de drawdown,
écart de Sharpe significatif ou non).

## 8 ter. Journal de transactions réelles (`config/transactions.csv`)

Fichier personnel (ignoré par Git), modèle `config/transactions.example.csv` :

```
date,enveloppe,type,ticker,parts,prix,montant,frais,commentaire
2026-10-01,pea,VERSEMENT,,,,400,0,Versement mensuel
2026-10-03,pea,ACHAT,WPEA.PA,56,7.08,,0.40,Ordre exécuté
```

Types : `VERSEMENT`, `RETRAIT`, `ACHAT`, `VENTE`, `FRAIS`, `DIVIDENDE`. Le journal est
prioritaire sur `positions.yaml` (écarts signalés). Renseigne aussi
`patrimoine.yaml > pea > date_ouverture` pour le jalon fiscal des 5 ans et le plafond de
150 000 € de versements.

## 8 quater. Historique long et stress tests

`main.py refresh-data --long` construit des prix mensuels en euros depuis 2004 en prolongeant
chaque ETF PEA par des proxys de même exposition (`config/long_history.yaml` ; USD convertis
avec EURUSD). Ces mois sont **synthétiques** et toujours signalés ; le rapport mensuel ne les
utilise jamais. Ensuite : `main.py research --long` et `main.py stress`.

## 8 quinquies. Profil investisseur et plans d'investissement

1. **Profil** (`config/profil.yaml`, personnel ; modèle `config/profil.example.yaml`) : capital
   de départ, versement, objectif, horizon, capital visé, réaction à une baisse de 30 %, temps
   disponible, zones, options (crypto, ESG, poche sécurisée), expérience, enveloppes ouvertes.
   `main.py profile` affiche les repères déduits : baisse supportable retenue (marge de 5 points
   pour un débutant), classe de risque, complexité acceptable, remarques de budget.
2. **Plans** (`config/plans.yaml`, génériques et versionnés) : chaque plan répartit le versement
   entre des poches (ETF, stratégie du registre, fonds euros, crypto) logées dans des
   enveloppes (PEA, assurance-vie, CTO, crypto). `main.py plans` produit pour chacun :
   - une **projection** : 2 000 scénarios par bootstrap par blocs de 12 mois de l'historique
     long, frais d'ordre, frais d'assurance-vie, fiscalité de sortie par enveloppe, plafond du
     PEA (surplus sur un CTO), inflation ; valeur nette en euros d'aujourd'hui (défavorable /
     médiane / favorable), revenu mensuel soutenable (règle des 3,5 %), pire baisse,
     probabilité d'atteindre l'objectif ;
   - le **vrai passé** : le plan lancé à chaque date de départ possible (pire, médiane, meilleur) ;
   - l'**adéquation** au profil (adapté / avec réserves / peu adapté) et la **routine mensuelle**.
   Le rapport (`reports/plans/`, personnel, ignoré par Git) contient les graphiques.
3. **Scénarios de rendement explicites** (`config/plans.yaml > scenarios`, défaut `central`) :
   - `historique` rejoue 2005-2026 (~9 %/an pour le MSCI World en EUR, période très favorable) ;
   - `central` (actions 6 %/an, défensif 2,5 %/an) et `defavorable` (3,5 % / 2 %) gardent **les
     mêmes krachs, la même volatilité et les mêmes écarts entre zones**, mais un rendement moyen
     plus modeste, et supposent **aucune surperformance** des stratégies actives (même Sharpe que
     le Buy & Hold) puisque l'étude de robustesse n'en démontre aucune.
   Ordres de grandeur sourcés dans le fichier (hypothèses 2026 de grands gérants), à réviser
   chaque année. La section « Sensibilité » compare les trois scénarios pour chaque plan.
4. **Contrôle du modèle** : pour chaque plan, la médiane du vrai passé est placée dans la
   distribution simulée sur le même historique ; en dehors du cœur (25-75 %), le plan est marqué
   « divergent ». Le vrai passé ne contient qu'environ 1,4 période indépendante de 15 ans : aucune
   des deux mesures n'est une preuve.
5. **Crypto** : 5 %/an en **espérance** (moyenne), volatilité historique conservée ; le scénario
   le plus probable pour la poche crypto est alors une forte perte (`crypto_hypothese`).
6. Les seuils d'adéquation (35 % / 65 %) sont des **conventions** modifiables, pas des résultats.

## 8 septies. Identité des ETF et données

- `main.py universe` affiche pour chaque ETF son ISIN (clé de contrôle vérifiée), son nom
  officiel, ses frais, son éligibilité au PEA, la date et la source de vérification
  (`config/assets.yaml > fiche`), puis les points d'attention. À revérifier une fois par an.
- Constats du 2026-09-25 : ESE.PA suit le S&P 500 classique (pas ESG) ; GWT.PA est un MSCI
  Europe Growth (pas un MSCI World Small Cap) ; OBLI.PA est devenu un fonds monétaire €STR vers
  2024-11 (la poche « obligataire » des stratégies 60/40, 80/20 et dual momentum est donc du
  cash dans le PEA) ; l'éligibilité PEA de CSH2.PA n'est pas confirmée.
- Historique long : avant 2009, l'indice MSCI World de prix reçoit un rendement de dividende
  estimé (`dividend_yield_pct`, 1,5 %/an net de frais, calibré sur CW8 : écart résiduel
  -0,05 point par an).
- Résultats JSON : format commun décrit dans [results_schema.md](results_schema.md).

## 8 sexies. Stratégies et robustesse

- `main.py robustness` (historique long) donne trois verdicts par stratégie : **fiabilité**
  (Sharpe probabiliste et dégonflé, sous-périodes, pire fenêtre de 5 ans, plateau de
  paramètres, walk-forward, frais triplés), **surperformance** face au Buy & Hold (après
  correction des tests multiples) et **protection** contre les baisses.
  Rapport : `reports/research/robustness_report.md`.
- `main.py strategies` écrit les fiches (`reports/research/strategy_cards.md`) : principe,
  règles exactes, temps, complexité, forces, faiblesses, pour qui, erreurs fréquentes, mesures
  et crises. À relancer après `robustness` et `stress`.
- Aucun réglage n'est modifié automatiquement : un réglage « plateau » différent du défaut est
  une piste à tester en paper trading.

## 9. Automatisation (facultative)

`scripts\run_monthly.ps1` lance `run-month --refresh-data`, écrit la sortie dans
`logs\YYYY-MM.log` et renvoie le code de sortie de la CLI. Test manuel :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_monthly.ps1
```

Pour le planifier le 3 de chaque mois à 9 h (à lancer **toi-même**, une seule fois,
dans PowerShell) :

```powershell
schtasks /Create /TN "PersonalQuantLab\RunMonthly" /SC MONTHLY /D 3 /ST 09:00 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\Users\degar\OneDrive - De Vinci Higher Education (DVHE)\Perso\Projet Investissement\personal-quant-lab\scripts\run_monthly.ps1\""
```

- Vérifier : `schtasks /Query /TN "PersonalQuantLab\RunMonthly"`
- Lancer tout de suite : `schtasks /Run /TN "PersonalQuantLab\RunMonthly"`
- Supprimer : `schtasks /Delete /TN "PersonalQuantLab\RunMonthly" /F`

Le PC doit être allumé à l'heure prévue. La tâche prépare le rapport et une entrée
`PENDING` : la lecture et la décision restent manuelles.

### Notifications sur téléphone (ntfy, facultatif)

1. Installer l'application **ntfy** et s'abonner à un sujet long et difficile à deviner.
2. Dans `config/notify.yaml` : `enabled: true`, `topic: <ton sujet>`, `min_level: INFO`
   (ou `WARNING` / `CRITICAL` pour être moins sollicité).
3. `run-month --notify` (déjà utilisé par `scripts\run_monthly.ps1`) envoie : rapport
   disponible, changement d'actif, passage en cash total, rapport CRITICAL, échec de la
   routine. Historique : `logs\notifications.jsonl`. Une notification n'est jamais un ordre.

## 10. Tests et qualité

```powershell
.venv\Scripts\python.exe -m pytest -m "not slow"   # mode rapide (~45 s sur ce poste)
.venv\Scripts\python.exe -m pytest -n auto         # suite complète en parallèle, hors-ligne
powershell -ExecutionPolicy Bypass -File scripts\check.ps1          # ruff + tests + couverture (htmlcov\)
powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -Fast    # idem sans les tests lents
```

- **Tests par propriétés** (`tests/test_properties.py`, hypothesis) : poids valides pour toutes
  les stratégies, aucune information future, planificateur sans dépassement ni vente, journal
  sans position négative, sur des données générées.
- **Non-régression golden** (`tests/test_golden.py`) : le snapshot d'un jeu de données figé
  doit rester identique. Après un changement **volontaire** du calcul :
  `python -m pytest tests/test_golden.py --update-golden`, relis le diff de
  `tests/golden/monthly_snapshot.json`, puis commite.

### Sauvegarde hors du PC et intégration continue (à faire soi-même)

Le dépôt n'a pas de remote : il n'existe que sur ce PC / OneDrive. Pour une sauvegarde privée
sur GitHub (compte requis, dépôt **privé** conseillé) :

```powershell
gh repo create personal-quant-lab --private --source . --remote origin
git push -u origin master
git push origin lab-v2 lab-v3 lab-v4
```

Sans l'outil `gh` : créer un dépôt privé vide sur github.com, puis
`git remote add origin <url>` et `git push -u origin master`. Les fichiers personnels
(`config/positions.yaml`, `holdings.yaml`, `transactions.csv`, `notify.yaml`, données) sont
ignorés par Git et ne partent pas. Le workflow `.github/workflows/tests.yml` lance alors
automatiquement ruff, mypy et les tests rapides à chaque push (suite complète le lundi).

### Hooks pre-commit (facultatif)

```powershell
.venv\Scripts\Activate.ps1
python -m pre_commit install      # ruff + tests rapides avant chaque commit
python -m pre_commit run --all-files
```

Typage : `python -m mypy` (mode souple, configuration dans `pyproject.toml`).

## 11. Dépannage

| Symptôme | Cause probable / solution |
| -------- | ------------------------- |
| `Données locales introuvables` | Lancer `main.py refresh-data` |
| Erreur `clé inconnue` / `doit être un entier` | Corriger la clé indiquée dans le fichier cité (faute de frappe, guillemets autour d'un nombre) |
| Alerte `DATA_ANOMALY` ou historique ajusté | `main.py refresh-data --full` pour tout retélécharger ; les archives brutes sont dans `data\raw\` |
| Plan de versement : « une part coûte plus que le budget » | Le plan bascule déjà vers un véhicule de même exposition s'il existe (`main.py vehicles`) ; sinon accumuler plusieurs versements |
| `stress` / `research --long` : « Historique long absent » | Lancer `main.py refresh-data --long` |
| `portfolio` : « Vente de N … alors que … détenues » | Une vente dépasse les parts du journal : vérifier les lignes `ACHAT` / `VENTE` de `transactions.csv` |
| Test golden en échec après une modification volontaire | `python -m pytest tests/test_golden.py --update-golden`, relire le diff, commiter |
| Statut `CRITICAL` + `STALE_DATA` | Données de plus de 30 jours : `run-month --refresh-data` |
| `refresh-data` échoue ou un ticker manque | yfinance indisponible ou ticker retiré : réessayer plus tard ; vérifier le ticker sur Yahoo Finance ; sinon `universe_active: false` dans `assets.yaml` |
| `Entrée déjà approuvée` | Normal : une décision enregistrée n'est jamais écrasée. `paper-decision` permet de la modifier |
| Accents illisibles dans la console | Utiliser PowerShell ou Windows Terminal ; les fichiers sont toujours en UTF-8 |
| `pip` ou `python` du venv cassé après un déplacement | `scripts\setup.ps1 -Recreate` |
| Le tableau de bord n'affiche pas le nouveau mois | Recharger la page (F5) après `run-month` |

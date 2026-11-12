# Comprendre la couche de données (`src/data_loader.py`)

Ce document explique les **5 points techniques les plus importants** du chargeur
de données. Objectif : comprendre *pourquoi* le code est écrit ainsi, pas
seulement *ce qu'il fait*. Chaque section part de zéro (aucune connaissance
préalable de MultiIndex, DatetimeIndex, Parquet ou pytest n'est supposée).

Les 5 fonctions concernées :

- `download_prices` — télécharge les prix depuis yfinance.
- `validate_prices` — nettoie et valide un DataFrame de prix.
- `save_prices` / `load_prices` — sauvegarde et relecture sur disque.
- `load_tickers_from_yaml` — lit l'univers de tickers depuis `config/assets.yaml`.

---

## 1. La gestion du MultiIndex dans `download_prices`

### C'est quoi un MultiIndex ?

Normalement, un `DataFrame` pandas a **un seul niveau** de noms de colonnes :

```
            Close
2024-01-01  100.0
2024-01-02  101.0
```

Un **MultiIndex** = des colonnes à **plusieurs niveaux** (des colonnes
« empilées »). Au lieu d'un nom, chaque colonne est identifiée par un *tuple* :

```
Price        Close            Open
Ticker       CW8.PA  BTC-USD  CW8.PA  BTC-USD
2024-01-01   100.0   40000.0  99.0    39000.0
2024-01-02   101.0   41000.0  100.0   40000.0
```

Ici une colonne s'appelle par exemple `("Close", "CW8.PA")` : le premier niveau
est le **type de prix** (`Close`, `Open`, `High`...), le second est le **ticker**.

### Pourquoi yfinance renvoie un MultiIndex ?

Parce que pour chaque ticker, yfinance fournit **plusieurs séries** (Open, High,
Low, Close, Volume). Avec plusieurs tickers, il faut donc deux informations pour
désigner une colonne : *quel prix* et *quel actif* → d'où le MultiIndex.

- **Un seul ticker** → colonnes simples : `Open, High, Low, Close, Volume`.
- **Plusieurs tickers** → colonnes MultiIndex : `(Close, CW8.PA)`, `(Close, BTC-USD)`, etc.

C'est exactement la difficulté que `download_prices` doit absorber : on veut
**toujours** la même sortie propre (un ticker par colonne, valeurs = clôture),
quel que soit le nombre de tickers.

### Pourquoi on extrait `Close` ?

Pour un backtest, on travaille sur **le prix de clôture**. Avec `auto_adjust=True`
(le défaut), cette colonne `Close` est déjà **ajustée** des dividendes et splits :
c'est le bon prix pour calculer des rendements « total return ».

### Comment le code le fait réellement

Le travail est isolé dans le helper `_extract_close_prices`. Version simplifiée :

```python
if isinstance(data.columns, pd.MultiIndex):
    # plusieurs tickers : on prend la "tranche" Close, tous tickers confondus
    prices = data.xs("Close", axis=1, level=0)
else:
    # un seul ticker : colonnes simples
    prices = data[["Close"]].copy()
    prices.columns = tickers   # ex. ["CW8.PA"]
```

Ligne par ligne :

- `isinstance(data.columns, pd.MultiIndex)` : on **teste** si on est dans le cas
  multi-tickers.
- `data.xs("Close", axis=1, level=0)` : `xs` = *cross-section*. On découpe une
  **tranche** des colonnes là où le niveau 0 vaut `"Close"`. Résultat : un
  DataFrame avec **un ticker par colonne**.
  - On préfère `xs(...)` à `data["Close"]` car c'est robuste si yfinance range
    le niveau « type de prix » en position 0 *ou* en dernière position (le code
    gère les deux via `level=0` puis `level=-1`).
- Cas mono-ticker : `data[["Close"]]` garde la seule colonne Close, puis on la
  **renomme** avec le nom du ticker pour avoir la même forme que le cas multi.

Le code lève aussi une `ValueError` claire si aucune colonne `Close` n'existe, ou
si yfinance renvoie des colonnes simples alors qu'on a demandé plusieurs tickers
(situation ambiguë : impossible d'associer les prix aux bons tickers).

### Mini-exemple

```python
# 1 ticker  -> colonnes simples
download_prices("CW8.PA", start="2024-01-01")
#             CW8.PA
# 2024-01-01  100.0
# 2024-01-02  101.0

# 2 tickers -> MultiIndex en entrée, mais SORTIE identique en forme
download_prices(["CW8.PA", "BTC-USD"], start="2024-01-01")
#             CW8.PA   BTC-USD
# 2024-01-01  100.0    40000.0
# 2024-01-02  101.0    41000.0
```

**À retenir :** la fonction encaisse la complexité de yfinance (MultiIndex ou non)
et renvoie toujours un format propre et prévisible.

---

## 2. La validation du `DatetimeIndex` (`load_prices` / `validate_prices`)

### Pourquoi un `DatetimeIndex` est indispensable

L'**index** d'un DataFrame, ce sont les « étiquettes de lignes ». Pour une série
financière, ces étiquettes sont des **dates**. Un `DatetimeIndex` est un index
dont pandas sait que ce sont de **vraies dates** (pas du texte `"2024-01-01"`).

C'est ce qui débloque toute la boîte à outils temporelle :

- `prices.resample("ME")` → rééchantillonner en fin de mois.
- `prices.loc["2024"]` → sélectionner une année.
- `pct_change()`, calcul de drawdown, rendements annuels... s'appuient sur l'ordre
  chronologique des lignes.

Si l'index est du **texte**, pandas trie « alphabétiquement » et le
rééchantillonnage n'existe même pas. D'où, dans le code :

```python
prices.index = pd.to_datetime(prices.index)   # force de vraies dates
...
if not isinstance(prices.index, pd.DatetimeIndex):
    raise ValueError("L'index doit être un DatetimeIndex.")
```

### Pourquoi `sort_index()` est important

Beaucoup de calculs financiers comparent **chaque ligne à la précédente**.
`pct_change()` fait littéralement `(valeur_du_jour / valeur_de_la_ligne_au-dessus) - 1`.
Si les lignes ne sont **pas dans l'ordre des dates**, le « jour précédent » n'est
pas le bon → rendements faux.

```python
prices = prices.sort_index()   # garantit l'ordre chronologique
```

### Pourquoi les dates dupliquées sont dangereuses

Une même date qui apparaît deux fois peut venir d'une fusion de fichiers ou d'un
glitch fournisseur. Conséquences : un `pct_change()` à 0 % artificiel entre les
deux doublons, ou un `reindex`/`resample` qui plante ou double-compte.

Le code supprime les doublons en **gardant la dernière valeur** (souvent la plus
corrigée) :

```python
prices = prices[~prices.index.duplicated(keep="last")]
```

- `prices.index.duplicated(keep="last")` renvoie `True` pour chaque doublon
  **sauf le dernier**.
- Le `~` inverse le masque → on garde tout sauf les doublons à éliminer.

### Exemple d'ordre faux et sa conséquence

```python
import pandas as pd

# Dates VOLONTAIREMENT dans le désordre
idx = pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-02"])
prices = pd.Series([102, 100, 101], index=idx)

prices.pct_change()
# 2024-01-03      NaN
# 2024-01-01    -0.0196   <- "rendement" entre le 03 et le 01 : ABSURDE
# 2024-01-02     0.0100
```

Le premier « rendement » compare le 1er janvier au 3 janvier : un retour dans le
passé. Après `sort_index()`, l'ordre devient 01 → 02 → 03 et les rendements
redeviennent corrects. C'est pour cela que `validate_prices` **trie d'abord**,
puis **dé-duplique**, avant de rendre les données.

> Détail important : `load_prices` ne se contente plus de trier — il appelle
> `validate_prices`. Un CSV relu subit donc **exactement les mêmes garanties**
> (tri, doublons, colonnes vides) que des données fraîchement téléchargées.

---

## 3. La logique de sauvegarde CSV / Parquet

### CSV vs Parquet en une phrase

- **CSV** = un fichier texte, une ligne par date, des valeurs séparées par des
  virgules. Lisible par un humain, ouvrable dans Excel ou un éditeur de texte.
- **Parquet** = un format **binaire** et **colonne par colonne**, compressé,
  pensé pour les gros volumes de données et la lecture rapide.

### Pourquoi CSV est simple

On peut l'ouvrir, le lire, le diff dans git, le coller dans un tableur. Idéal
pour de petits jeux de données et pour **inspecter** ce qu'on a téléchargé.
Inconvénients : fichiers plus lourds, et les types (dates, nombres) ne sont pas
mémorisés — ils doivent être **re-déduits** à la relecture (d'où `parse_dates`).

### Pourquoi Parquet est plus efficace

- **Compressé** → fichiers nettement plus petits.
- **Orienté colonnes** → lire seulement `CW8.PA` sans tout charger.
- **Types conservés** → une date reste une date, un float reste un float.

Idéal dès que les données grossissent (des années de cotations, beaucoup de
tickers, intervalle intraday).

### Quand utiliser quoi

| Situation | Format conseillé |
|---|---|
| Petit échantillon, à inspecter à l'œil | **CSV** |
| Données partagées / ouvertes dans Excel | **CSV** |
| Historique long, multi-tickers, intraday | **Parquet** |
| Relectures fréquentes et rapides | **Parquet** |

### Comment `save_prices` choisit le format

Le choix se fait sur **l'extension du fichier** :

```python
path = Path(path)
suffix = path.suffix.lower()           # ".csv", ".parquet"...

if suffix not in SUPPORTED_PRICE_EXTENSIONS:   # {".csv", ".parquet"}
    raise ValueError("Format non supporté...") # on refuse AVANT toute écriture

path.parent.mkdir(parents=True, exist_ok=True) # crée les dossiers manquants

if suffix == ".csv":
    prices.to_csv(path)
elif suffix == ".parquet":
    prices.to_parquet(path)
```

Points clés, ligne par ligne :

- `path.suffix.lower()` → l'extension, en minuscules (donc `.CSV` fonctionne aussi).
- La vérification d'extension se fait **avant** `mkdir`. Conséquence voulue : une
  extension invalide **ne crée aucun dossier parasite** (c'est testé).
- `mkdir(parents=True, exist_ok=True)` → crée `data/processed/` s'il manque, sans
  planter si le dossier existe déjà.

### Parquet a besoin de `pyarrow`

`to_parquet` / `read_parquet` délèguent à un **moteur** : `pyarrow` (ou
`fastparquet`). S'il n'est pas installé, ces appels lèvent une erreur. À installer
au besoin :

```bash
pip install pyarrow
```

> Dans ce projet, aucun moteur Parquet n'est installé pour l'instant : c'est
> pourquoi le test Parquet est **ignoré** automatiquement (voir section 5).

---

## 4. Les erreurs `ValueError` / `FileNotFoundError`

### Échouer fort plutôt que renvoyer de mauvaises données

En finance quantitative, une donnée silencieusement fausse est **pire** qu'une
erreur visible : elle se propage dans les rendements, le Sharpe, le drawdown... et
on prend une décision sur un backtest faux **sans le savoir**. La règle du code :

> Mieux vaut un `raise` bruyant tout de suite qu'un résultat faux plus tard.

### Quand `FileNotFoundError` ?

Quand on demande de **lire un fichier qui n'existe pas**. C'est l'exception
standard de Python pour ce cas — la réutiliser rend l'intention évidente.

```python
if not path.exists():
    raise FileNotFoundError(f"Fichier introuvable : {path}")
```

### Quand `ValueError` ?

Quand le fichier/les données existent mais sont **invalides ou inexploitables** :
mauvais format, contenu vide, structure inattendue. La valeur fournie est
« du mauvais type de valeur » → `ValueError`.

### Les 5 cas concrets dans le code

```python
# 1. Fichier manquant
load_prices("inexistant.csv")          # -> FileNotFoundError

# 2. Extension non supportée
save_prices(prices, "prices.txt")      # -> ValueError (format non supporté)

# 3. Téléchargement vide
download_prices(["XXXX"], "2024-01-01")  # data.empty -> ValueError

# 4. YAML mal structuré (liste au lieu d'un dictionnaire de catégories)
load_tickers_from_yaml("assets.yaml")  # -> ValueError

# 5. Aucune colonne de prix valide (toutes NaN)
validate_prices(df_tout_NaN)           # -> ValueError
```

Détails utiles :

- **(3)** `download_prices` vérifie `data.empty`, puis `validate_prices` re-vérifie
  après nettoyage : double filet de sécurité.
- **(4)** `load_tickers_from_yaml` exige un **dictionnaire** `catégorie: [tickers]`.
  Une simple liste, une catégorie scalaire (`pea: CW8.PA` au lieu d'une liste), ou
  un ticker non-texte (`- 123`) → `ValueError` explicite.
- **(5)** `validate_prices` supprime les colonnes entièrement vides ; s'il ne reste
  **aucune** colonne, il lève une `ValueError` plutôt que de rendre un DataFrame vide.

### Pourquoi c'est crucial en backtesting

Un backtest est une **chaîne** : données → rendements → métriques → décision. Si la
première brique laisse passer une donnée fausse, **tout le reste est faux mais
paraît normal**. Lever une erreur tôt = couper la chaîne avant de produire un
résultat trompeur.

---

## 5. Les tests avec pytest et `tmp_path`

### Pourquoi éviter les appels internet réels

Tester `download_prices` en appelant **vraiment** yfinance serait :

- **lent** (réseau),
- **fragile** (l'API peut être en panne, ou hors-ligne en examen/CI),
- **non reproductible** (les valeurs changent chaque jour).

Un test doit être **déterministe** : même entrée → même résultat, à chaque exécution.

### Comment on remplace yfinance : `monkeypatch`

On **remplace** `yf.download` par une fausse fonction qui renvoie un DataFrame
fixe. Aucun réseau, résultat constant :

```python
def test_download_prices_extracts_close_from_multiindex(monkeypatch):
    columns = pd.MultiIndex.from_product(
        [["Open", "Close"], ["BTC-USD", "CW8.PA"]], names=["Price", "Ticker"]
    )
    def fake_download(**kwargs):
        return pd.DataFrame([[40000, 100, 41000, 101]], columns=columns,
                            index=pd.to_datetime(["2024-01-01"]))
    monkeypatch.setattr("src.data_loader.yf.download", fake_download)  # on branche le faux

    result = download_prices(["CW8.PA", "BTC-USD"], start="2024-01-01")
    assert list(result.columns) == ["CW8.PA", "BTC-USD"]
```

`monkeypatch.setattr(...)` échange la vraie fonction contre `fake_download` **le
temps du test seulement**. C'est ce qui permet de tester la logique MultiIndex de
la section 1 **sans internet**.

### C'est quoi `tmp_path` ?

`tmp_path` est une **fixture** pytest : un **dossier temporaire neuf**, fourni
automatiquement à chaque test qui le demande, et **supprimé après**. On y écrit des
fichiers sans polluer le projet ni écraser de vraies données.

```python
def test_save_and_load_csv_roundtrip(tmp_path, sample_prices):
    path = tmp_path / "prices.csv"      # chemin dans le dossier temporaire
    save_prices(sample_prices, path)    # on écrit...
    loaded = load_prices(path)          # ...puis on relit
    pd.testing.assert_frame_equal(loaded, sample_prices)  # identique ?
```

Ce test « aller-retour » (*roundtrip*) vérifie que **ce qu'on sauvegarde est
exactement ce qu'on relit**.

### Tester les cas limites

```python
# Fichier manquant -> FileNotFoundError
def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_prices(tmp_path / "nope.csv")

# Extension non supportée -> ValueError (et aucun dossier créé)
def test_bad_extension(tmp_path, sample_prices):
    path = tmp_path / "nested" / "prices.txt"
    with pytest.raises(ValueError):
        save_prices(sample_prices, path)
    assert not path.parent.exists()

# Dates dupliquées -> on garde la dernière
def test_duplicated_dates():
    idx = pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02"])
    out = validate_prices(pd.DataFrame({"A": [1.0, 99.0, 2.0]}, index=idx))
    assert out.loc["2024-01-01", "A"] == 99.0

# Colonnes entièrement vides -> supprimées
def test_empty_columns():
    idx = pd.to_datetime(["2024-01-01", "2024-01-02"])
    out = validate_prices(pd.DataFrame({"A": [1.0, 2.0], "B": [None, None]}, index=idx))
    assert list(out.columns) == ["A"]

# YAML invalide (liste au lieu de dict) -> ValueError
def test_invalid_yaml(tmp_path):
    path = tmp_path / "assets.yaml"
    path.write_text("- CW8.PA\n- ESE.PA\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_tickers_from_yaml(path)
```

`pytest.raises(...)` = « ce bloc **doit** lever cette exception ». Si l'exception
n'est pas levée, le test échoue : c'est ainsi qu'on teste que le code **échoue bien
quand il le doit** (lien direct avec la section 4).

### Le cas Parquet : ignorer proprement

Comme Parquet a besoin de `pyarrow` (section 3), le test est **sauté** si aucun
moteur n'est présent, au lieu d'échouer :

```python
HAS_PARQUET = importlib.util.find_spec("pyarrow") is not None \
    or importlib.util.find_spec("fastparquet") is not None

@pytest.mark.skipif(not HAS_PARQUET, reason="Aucun moteur Parquet installé.")
def test_save_and_load_parquet_roundtrip(tmp_path, sample_prices):
    ...
```

Résultat à l'exécution : `15 passed, 1 skipped` — le test Parquet est *skipped*,
pas en échec.

---

## Points à vérifier dans le code

Le code et cette explication sont alignés. Quelques nuances à garder en tête :

- **`xs("Close")` plutôt que `data["Close"]`.** L'extraction réelle passe par le
  helper `_extract_close_prices`, qui utilise `data.xs("Close", axis=1, level=0)`
  (et tente aussi `level=-1`). C'est plus robuste que `data["Close"]` selon l'ordre
  des niveaux renvoyé par yfinance. Si une version de yfinance changeait cet ordre,
  c'est ce helper qu'il faudrait revérifier.
- **`download_prices` accepte une chaîne unique.** `download_prices("CW8.PA", ...)`
  fonctionne (normalisé en liste par `_normalise_tickers`), pas seulement une liste.
- **`load_prices` valide, il ne fait pas que trier.** Il appelle `validate_prices`,
  donc un CSV relu peut être *modifié* (tri, suppression de doublons et de colonnes
  vides) ou *rejeté* (vide → `ValueError`). À ne pas oublier si un fichier relu
  « perd » une colonne : elle était sans doute entièrement NaN.
- **Parquet non disponible par défaut.** `pyarrow`/`fastparquet` ne sont pas
  installés ici → toute sauvegarde `.parquet` échouerait tant qu'on n'a pas fait
  `pip install pyarrow`. Le test correspondant est *skipped*, pas vert.
- **Pas de forward-fill.** Le chargeur n'aligne pas les calendriers (ETF vs crypto
  7j/7). Cet alignement reste à gérer au niveau de la stratégie/backtest.

---

## Ce que je dois avoir compris avant de passer à l'étape suivante

- [ ] Je sais ce qu'est un **MultiIndex** et pourquoi yfinance en renvoie un pour
      plusieurs tickers.
- [ ] Je comprends pourquoi `download_prices` extrait `Close` et renvoie **toujours**
      le même format (un ticker par colonne), mono ou multi-ticker.
- [ ] Je sais pourquoi un **`DatetimeIndex` trié** est indispensable, et ce que
      `pct_change()` calcule de faux si l'ordre est mauvais.
- [ ] Je comprends pourquoi les **dates dupliquées** sont dangereuses et comment le
      code les supprime (`keep="last"`).
- [ ] Je sais choisir entre **CSV et Parquet**, et comment `save_prices` décide via
      l'extension (et que Parquet exige `pyarrow`).
- [ ] Je distingue **`FileNotFoundError`** (fichier absent) de **`ValueError`**
      (donnée invalide), et je vois pourquoi « échouer fort » protège un backtest.
- [ ] Je comprends pourquoi les tests **n'appellent pas internet** (`monkeypatch`),
      ce qu'apporte **`tmp_path`**, et comment `pytest.raises` teste les erreurs.
- [ ] Je sais lancer la suite : `python -m pytest tests/test_data_loader.py -q`.

- [ ] Je sais que `load_tickers_from_yaml` aplatit les catégories, retire les doublons
      et préserve l'ordre d'apparition.
- [ ] Je comprends que le chargeur ne forward-fill pas les valeurs manquantes :
      les NaN partiels restent visibles pour le backtest.
- [ ] Je sais qu'un univers mixte ETF/crypto peut mélanger des calendriers de cotation
      différents, et que cet alignement doit être décidé dans la stratégie/backtest.
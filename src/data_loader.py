from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import yaml
import yfinance as yf

SUPPORTED_PRICE_EXTENSIONS = {".csv", ".parquet"}


def _normalise_tickers(tickers: str | Sequence[str]) -> list[str]:
    if isinstance(tickers, str):
        normalised = [tickers]
    else:
        normalised = list(tickers)

    normalised = [ticker.strip() for ticker in normalised]
    if not normalised or any(not ticker for ticker in normalised):
        raise ValueError("La liste de tickers ne doit pas etre vide.")

    return normalised


def _extract_close_prices(data: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if isinstance(data.columns, pd.MultiIndex):
        if "Close" in data.columns.get_level_values(0):
            prices = data.xs("Close", axis=1, level=0)
        elif "Close" in data.columns.get_level_values(-1):
            prices = data.xs("Close", axis=1, level=-1)
        else:
            raise ValueError(
                "Les donnees telechargees ne contiennent pas de colonne Close."
            )

        if isinstance(prices, pd.Series):
            prices = prices.to_frame()

        requested_columns = [ticker for ticker in tickers if ticker in prices.columns]
        other_columns = [
            column for column in prices.columns if column not in requested_columns
        ]
        prices = prices.loc[:, requested_columns + other_columns]
        prices.columns.name = None
        return prices.copy()

    if "Close" not in data.columns:
        raise ValueError(
            "Les donnees telechargees ne contiennent pas de colonne Close."
        )

    if len(tickers) != 1:
        raise ValueError(
            "yfinance a renvoye des colonnes simples pour plusieurs tickers ; "
            "impossible d'associer les prix aux tickers."
        )

    prices = data[["Close"]].copy()
    prices.columns = tickers
    return prices


def validate_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Valide et nettoie un DataFrame de prix.

    Vérifie que le DataFrame n'est pas vide, que l'index est temporel,
    trie les dates, supprime les dates dupliquées (on garde la dernière)
    et retire les colonnes entièrement vides.

    Parameters
    ----------
    prices:
        DataFrame de prix indexé par date.

    Returns
    -------
    pd.DataFrame
        DataFrame nettoyé.

    Raises
    ------
    ValueError
        Si le DataFrame est vide, si l'index n'est pas un DatetimeIndex,
        ou s'il ne reste aucune colonne valide après nettoyage.
    """

    if prices.empty:
        raise ValueError("Le DataFrame de prix est vide.")

    if not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("L'index doit être un DatetimeIndex.")

    # Trier par date
    prices = prices.sort_index()

    # Supprimer les dates dupliquées en gardant la dernière occurrence
    prices = prices[~prices.index.duplicated(keep="last")]

    # Retirer les colonnes entièrement vides
    prices = prices.dropna(axis=1, how="all")

    if prices.shape[1] == 0:
        raise ValueError("Aucune colonne valide après nettoyage.")

    return prices


def download_prices(
    tickers: str | Sequence[str],
    start: str,
    end: str | None = None,
    auto_adjust: bool = True,
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Télécharge les prix de clôture pour une liste de tickers via yfinance.

    Parameters
    ----------
    tickers:
        Liste de tickers Yahoo Finance.
        Exemple : ["CW8.PA", "ESE.PA", "BTC-USD"]

    start:
        Date de début au format "YYYY-MM-DD".

    end:
        Date de fin au format "YYYY-MM-DD".
        Si None, yfinance va jusqu'à la date la plus récente disponible.

    auto_adjust:
        Si True, yfinance ajuste les prix pour dividendes/splits.

    interval:
        Granularité des données ("1d", "1wk", "1mo"...).

    Returns
    -------
    pd.DataFrame
        DataFrame indexé par date, avec un ticker par colonne (prix de clôture).

    Raises
    ------
    ValueError
        Si aucune donnée n'est téléchargée ou si les prix sont vides
        après nettoyage.
    """

    tickers = _normalise_tickers(tickers)

    # 1. Télécharger les données avec yfinance
    data = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        auto_adjust=auto_adjust,
        interval=interval,
        progress=False,
    )

    # 2. Cas où yfinance ne renvoie rien
    if data.empty:
        raise ValueError(
            "Aucune donnée téléchargée. Vérifie les tickers ou les dates."
        )

    # 3. Extraire les prix de clôture.
    # Avec auto_adjust=True, "Close" correspond déjà au prix ajusté.
    # Pour plusieurs tickers, yfinance renvoie des colonnes MultiIndex.
    prices = _extract_close_prices(data, tickers)

    # 4. S'assurer que l'index est bien temporel avant validation
    prices.index = pd.to_datetime(prices.index)

    # 5. Nettoyage et validation
    return validate_prices(prices)


def save_prices(prices: pd.DataFrame, path: str | Path) -> None:
    """
    Sauvegarde un DataFrame de prix en CSV ou Parquet.

    Parameters
    ----------
    prices:
        DataFrame de prix à sauvegarder.

    path:
        Chemin de sortie. Exemple : "data/processed/prices.csv"

    Raises
    ------
    ValueError
        Si l'extension du fichier n'est ni .csv ni .parquet.
    """

    path = Path(path)
    suffix = path.suffix.lower()

    if suffix not in SUPPORTED_PRICE_EXTENSIONS:
        raise ValueError(
            f"Format non supporté : '{path.suffix}'. Utilise .csv ou .parquet."
        )

    # Crée le dossier parent s'il n'existe pas
    path.parent.mkdir(parents=True, exist_ok=True)

    if suffix == ".csv":
        prices.to_csv(path)
    elif suffix == ".parquet":
        prices.to_parquet(path)


def load_prices(path: str | Path) -> pd.DataFrame:
    """
    Charge un fichier de prix sauvegardé en CSV ou Parquet.

    Parameters
    ----------
    path:
        Chemin du fichier à charger.

    Returns
    -------
    pd.DataFrame
        DataFrame de prix avec un DatetimeIndex trié.

    Raises
    ------
    FileNotFoundError
        Si le fichier n'existe pas.
    ValueError
        Si le format n'est pas supporté ou si le DataFrame chargé est vide.
    """

    path = Path(path)
    suffix = path.suffix.lower()

    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")

    if suffix == ".csv":
        # La première colonne contient les dates.
        prices = pd.read_csv(path, index_col=0, parse_dates=True)
    elif suffix == ".parquet":
        prices = pd.read_parquet(path)
    else:
        raise ValueError(
            f"Format non supporté : '{path.suffix}'. Utilise .csv ou .parquet."
        )

    # Sécurité : s'assurer que l'index est bien une date, puis valider
    prices.index = pd.to_datetime(prices.index)

    return validate_prices(prices)


def load_tickers_from_yaml(path: str | Path) -> list[str]:
    """
    Charge une liste de tickers depuis un fichier YAML.

    Le format courant contient une clé ``universe`` avec une liste d'actifs
    structurés. Seuls ceux dont ``universe_active`` vaut ``true`` sont renvoyés :

        universe:
          - ticker: CW8.PA
            name: MSCI World
            category: monde
            universe_active: true
            notes: ""

    Le format historique par catégories reste accepté pour assurer la
    rétrocompatibilité :

        pea:
          - CW8.PA
          - ESE.PA
        crypto:
          - BTC-USD
          - ETH-USD

    Parameters
    ----------
    path:
        Chemin du fichier de configuration YAML.

    Returns
    -------
    list[str]
        Liste de tickers dédupliquée.

    Raises
    ------
    FileNotFoundError
        Si le fichier de configuration n'existe pas.
    ValueError
        Si le contenu du YAML n'est pas un dictionnaire de catégories.
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")

    with open(path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError(
            "Le YAML doit être un dictionnaire contenant 'universe' ou des catégories."
        )

    if "universe" in config:
        assets = config["universe"]
        if not isinstance(assets, list):
            raise ValueError("La clé 'universe' doit contenir une liste d'actifs.")

        tickers: list[str] = []
        for position, asset in enumerate(assets):
            if not isinstance(asset, dict):
                raise ValueError(
                    f"L'actif universe[{position}] doit être un dictionnaire."
                )

            ticker = asset.get("ticker")
            if not isinstance(ticker, str) or not ticker.strip():
                raise ValueError(
                    f"L'actif universe[{position}] doit contenir un ticker valide."
                )

            active = asset.get("universe_active", True)
            if not isinstance(active, bool):
                raise ValueError(
                    f"universe_active doit être un booléen pour '{ticker.strip()}'."
                )
            if active:
                tickers.append(ticker.strip())

        return list(dict.fromkeys(tickers))

    # Compatibilité avec l'ancien format ``catégorie: [tickers]``.
    tickers = []
    for category, values in config.items():
        if not values:  # ignore les catégories vides (None ou liste vide)
            continue

        if not isinstance(values, list):
            raise ValueError(
                f"La categorie '{category}' doit contenir une liste de tickers."
            )

        for ticker in values:
            if not isinstance(ticker, str) or not ticker.strip():
                raise ValueError(
                    f"La categorie '{category}' contient un ticker invalide."
                )

            tickers.append(ticker.strip())

    # Supprime les doublons en gardant l'ordre d'apparition
    return list(dict.fromkeys(tickers))

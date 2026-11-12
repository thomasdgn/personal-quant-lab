import importlib.util

import pandas as pd
import pytest

from src.data_loader import (
    download_prices,
    load_prices,
    load_tickers_from_yaml,
    save_prices,
    validate_prices,
)

# Parquet a besoin d'un moteur (pyarrow ou fastparquet) : on skip s'il manque.
HAS_PARQUET = (
    importlib.util.find_spec("pyarrow") is not None
    or importlib.util.find_spec("fastparquet") is not None
)


@pytest.fixture
def sample_prices() -> pd.DataFrame:
    """Petit DataFrame de prix avec un DatetimeIndex trié."""
    index = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    return pd.DataFrame(
        {"CW8.PA": [100.0, 101.0, 102.0], "BTC-USD": [40000.0, 41000.0, 42000.0]},
        index=index,
    )


# --------------------------------------------------------------------------- #
# save_prices / load_prices
# --------------------------------------------------------------------------- #
def test_save_and_load_csv_roundtrip(tmp_path, sample_prices):
    path = tmp_path / "prices.csv"

    save_prices(sample_prices, path)
    loaded = load_prices(path)

    assert isinstance(loaded.index, pd.DatetimeIndex)
    pd.testing.assert_frame_equal(loaded, sample_prices)


def test_save_prices_creates_parent_directories(tmp_path, sample_prices):
    path = tmp_path / "nested" / "dir" / "prices.csv"

    save_prices(sample_prices, path)

    assert path.exists()


@pytest.mark.skipif(not HAS_PARQUET, reason="Aucun moteur Parquet installé.")
def test_save_and_load_parquet_roundtrip(tmp_path, sample_prices):
    path = tmp_path / "prices.parquet"

    save_prices(sample_prices, path)
    loaded = load_prices(path)

    assert isinstance(loaded.index, pd.DatetimeIndex)
    pd.testing.assert_frame_equal(loaded, sample_prices)


def test_load_prices_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_prices(tmp_path / "does_not_exist.csv")


def test_save_prices_unsupported_extension_raises(tmp_path, sample_prices):
    path = tmp_path / "nested" / "prices.txt"

    with pytest.raises(ValueError):
        save_prices(sample_prices, path)

    assert not path.parent.exists()


def test_load_prices_unsupported_extension_raises(tmp_path):
    path = tmp_path / "prices.txt"
    path.write_text("whatever", encoding="utf-8")

    with pytest.raises(ValueError):
        load_prices(path)


def test_load_prices_empty_file_raises(tmp_path):
    path = tmp_path / "empty.csv"
    # En-tête sans aucune ligne de données -> DataFrame vide.
    pd.DataFrame(columns=["CW8.PA"]).to_csv(path)

    with pytest.raises(ValueError):
        load_prices(path)


def test_load_prices_validates_loaded_csv(tmp_path):
    path = tmp_path / "prices.csv"
    index = pd.to_datetime(["2024-01-02", "2024-01-01", "2024-01-01"])
    prices = pd.DataFrame(
        {"CW8.PA": [102.0, 100.0, 101.0], "EMPTY": [None, None, None]},
        index=index,
    )
    prices.to_csv(path)

    loaded = load_prices(path)

    expected = pd.DataFrame(
        {"CW8.PA": [101.0, 102.0]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
    )
    pd.testing.assert_frame_equal(loaded, expected)


# --------------------------------------------------------------------------- #
# download_prices
# --------------------------------------------------------------------------- #
def test_download_prices_accepts_single_ticker_string(monkeypatch):
    index = pd.to_datetime(["2024-01-02", "2024-01-01"])

    def fake_download(**kwargs):
        assert kwargs["tickers"] == ["CW8.PA"]
        return pd.DataFrame(
            {"Open": [101.0, 100.0], "Close": [102.0, 101.0]},
            index=index,
        )

    monkeypatch.setattr("src.data_loader.yf.download", fake_download)

    result = download_prices("CW8.PA", start="2024-01-01")

    expected = pd.DataFrame(
        {"CW8.PA": [101.0, 102.0]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
    )
    pd.testing.assert_frame_equal(result, expected)


def test_download_prices_extracts_close_from_multiindex(monkeypatch):
    index = pd.to_datetime(["2024-01-01", "2024-01-02"])
    columns = pd.MultiIndex.from_product(
        [["Open", "Close"], ["BTC-USD", "CW8.PA"]],
        names=["Price", "Ticker"],
    )

    def fake_download(**kwargs):
        assert kwargs["tickers"] == ["CW8.PA", "BTC-USD"]
        return pd.DataFrame(
            [
                [40000.0, 100.0, 41000.0, 101.0],
                [42000.0, 102.0, 43000.0, 103.0],
            ],
            columns=columns,
            index=index,
        )

    monkeypatch.setattr("src.data_loader.yf.download", fake_download)

    result = download_prices(["CW8.PA", "BTC-USD"], start="2024-01-01")

    expected = pd.DataFrame(
        {"CW8.PA": [101.0, 103.0], "BTC-USD": [41000.0, 43000.0]},
        index=index,
    )
    pd.testing.assert_frame_equal(result, expected)


def test_download_prices_missing_close_raises(monkeypatch):
    def fake_download(**kwargs):
        return pd.DataFrame(
            {"Open": [100.0]},
            index=pd.to_datetime(["2024-01-01"]),
        )

    monkeypatch.setattr("src.data_loader.yf.download", fake_download)

    with pytest.raises(ValueError, match="Close"):
        download_prices("CW8.PA", start="2024-01-01")


# --------------------------------------------------------------------------- #
# validate_prices
# --------------------------------------------------------------------------- #
def test_validate_prices_sorts_dates():
    index = pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-02"])
    prices = pd.DataFrame({"A": [3.0, 1.0, 2.0]}, index=index)

    result = validate_prices(prices)

    assert list(result.index) == sorted(result.index)
    assert list(result["A"]) == [1.0, 2.0, 3.0]


def test_validate_prices_removes_duplicated_dates_keeping_last():
    index = pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02"])
    prices = pd.DataFrame({"A": [1.0, 99.0, 2.0]}, index=index)

    result = validate_prices(prices)

    assert len(result) == 2
    # La dernière occurrence (99.0) est conservée pour la date dupliquée.
    assert result.loc["2024-01-01", "A"] == 99.0


def test_validate_prices_removes_fully_empty_columns():
    index = pd.to_datetime(["2024-01-01", "2024-01-02"])
    prices = pd.DataFrame({"A": [1.0, 2.0], "B": [None, None]}, index=index)

    result = validate_prices(prices)

    assert list(result.columns) == ["A"]


def test_validate_prices_empty_dataframe_raises():
    with pytest.raises(ValueError):
        validate_prices(pd.DataFrame())


def test_validate_prices_non_datetime_index_raises():
    prices = pd.DataFrame({"A": [1.0, 2.0]}, index=[0, 1])

    with pytest.raises(ValueError):
        validate_prices(prices)


def test_validate_prices_all_columns_empty_raises():
    index = pd.to_datetime(["2024-01-01", "2024-01-02"])
    prices = pd.DataFrame({"A": [None, None]}, index=index)

    with pytest.raises(ValueError):
        validate_prices(prices)


# --------------------------------------------------------------------------- #
# load_tickers_from_yaml
# --------------------------------------------------------------------------- #
def test_load_tickers_from_structured_universe(tmp_path):
    content = (
        "universe:\n"
        "  - ticker: CW8.PA\n"
        "    name: MSCI World\n"
        "    category: monde\n"
        "    universe_active: true\n"
        "    notes: ''\n"
        "  - ticker: ESE.PA\n"
        "    name: S&P 500 ESG\n"
        "    category: us_esg\n"
        "    universe_active: true\n"
        "    notes: ''\n"
    )
    path = tmp_path / "assets.yaml"
    path.write_text(content, encoding="utf-8")

    assert load_tickers_from_yaml(path) == ["CW8.PA", "ESE.PA"]


def test_load_tickers_filters_inactive_structured_assets(tmp_path):
    content = (
        "universe:\n"
        "  - ticker: CW8.PA\n"
        "    universe_active: true\n"
        "  - ticker: GOVF.PA\n"
        "    universe_active: false\n"
    )
    path = tmp_path / "assets.yaml"
    path.write_text(content, encoding="utf-8")

    assert load_tickers_from_yaml(path) == ["CW8.PA"]


def test_load_tickers_structured_asset_without_ticker_raises(tmp_path):
    path = tmp_path / "assets.yaml"
    path.write_text(
        "universe:\n  - name: Actif sans ticker\n    universe_active: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ticker valide"):
        load_tickers_from_yaml(path)


def test_load_tickers_flattens_and_dedupes(tmp_path):
    content = (
        "pea:\n"
        "  - CW8.PA\n"
        "  - ESE.PA\n"
        "crypto:\n"
        "  - BTC-USD\n"
        "  - ETH-USD\n"
        "benchmarks:\n"
        "  - CW8.PA\n"  # doublon volontaire
        "empty_category:\n"  # catégorie vide (None)
    )
    path = tmp_path / "assets.yaml"
    path.write_text(content, encoding="utf-8")

    tickers = load_tickers_from_yaml(path)

    assert tickers == ["CW8.PA", "ESE.PA", "BTC-USD", "ETH-USD"]


def test_load_tickers_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_tickers_from_yaml(tmp_path / "missing.yaml")


def test_load_tickers_invalid_structure_raises(tmp_path):
    path = tmp_path / "assets.yaml"
    # Une liste au lieu d'un dictionnaire de catégories.
    path.write_text("- CW8.PA\n- ESE.PA\n", encoding="utf-8")

    with pytest.raises(ValueError):
        load_tickers_from_yaml(path)


def test_load_tickers_scalar_category_raises(tmp_path):
    path = tmp_path / "assets.yaml"
    path.write_text("pea: CW8.PA\n", encoding="utf-8")

    with pytest.raises(ValueError):
        load_tickers_from_yaml(path)


def test_load_tickers_invalid_ticker_raises(tmp_path):
    path = tmp_path / "assets.yaml"
    path.write_text("pea:\n  - CW8.PA\n  - 123\n", encoding="utf-8")

    with pytest.raises(ValueError):
        load_tickers_from_yaml(path)

"""Messages d'erreur de configuration explicites (fichier, clé, valeur attendue)."""

import pytest

import main
from src.monthly_pipeline import load_config


def _write(tmp_path, body):
    path = tmp_path / "strategy_params.yaml"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.parametrize("body, message", [
    ("momentum:\n  lookback: 12\n", "clé inconnue 'momentum.lookback'"),
    ("momentum:\n  lookback_months: '12'\n", "'momentum.lookback_months' doit être un entier"),
    ("volatility_targeting:\n  enabled: oui\n", "'volatility_targeting.enabled' doit être true ou false"),
    ("backtest:\n  transaction_cost: cher\n", "'backtest.transaction_cost' doit être un nombre"),
    ("momentum: 12\n", "la section 'momentum' doit être un dictionnaire"),
    ("benchmark:\n  ticker: 12\n", "benchmark.ticker doit être un texte"),
    ("volatility_targeting:\n  target_volatility: -0.1\n", "volatility targeting invalides"),
])
def test_config_errors_name_file_key_and_expectation(tmp_path, body, message):
    path = _write(tmp_path, body)
    with pytest.raises(ValueError) as exc:
        load_config(path)
    assert message in str(exc.value) and str(path) in str(exc.value)


def test_cli_reports_config_error_without_traceback(tmp_path, capsys):
    path = _write(tmp_path, "momentum:\n  lookback: 12\n")
    assert main.main(["validate", "--config", str(path)]) == 1
    assert "clé inconnue" in capsys.readouterr().err


def test_integer_accepted_for_float_fields(tmp_path):
    assert load_config(_write(tmp_path, "backtest:\n  cash_return: 0\n")).backtest.cash_return == 0

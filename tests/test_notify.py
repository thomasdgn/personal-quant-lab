"""Notifications ntfy : désactivées par défaut, client HTTP toujours simulé."""

import json

import numpy as np
import pandas as pd
import pytest

import main
import src.notify as notify
from src.notify import NotifyConfig, build_events, load_notify_config, send_events


class FakePost:
    def __init__(self, status=200, fail=False):
        self.calls, self.status, self.fail = [], status, fail

    def __call__(self, url, data, headers, timeout):
        self.calls.append((url, data.decode("utf-8"), headers))
        if self.fail:
            raise OSError("réseau indisponible")
        return self.status


@pytest.fixture(autouse=True)
def no_real_http(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Aucune requête HTTP réelle ne doit partir pendant les tests.")
    monkeypatch.setattr(notify, "_urllib_post", forbidden)


def _snapshot(month="2026-09", selected=("PAASI.PA",), cash=0.58, status="OK_WITH_WARNINGS", alerts=()):
    return {"metadata": {"report_month": month, "signal_date": "2026-08-31", "pipeline_status": status},
            "momentum_strategy": {"selected_assets": list(selected), "cash_weight": 0.0, "invested_exposure": 1.0},
            "volatility_targeted_strategy": {"enabled": True, "target_weights": {"CASH": cash},
                                             "cash_weight": cash, "invested_exposure": 1 - cash},
            "alerts": list(alerts)}


def test_config_defaults_and_validation(tmp_path):
    assert load_notify_config(tmp_path / "absent.yaml").enabled is False
    with pytest.raises(ValueError, match="topic"):
        NotifyConfig(enabled=True, topic="")
    with pytest.raises(ValueError, match="https"):
        NotifyConfig(server="http://ntfy.sh")
    with pytest.raises(ValueError):
        NotifyConfig(min_level="DEBUG")
    path = tmp_path / "notify.yaml"
    path.write_text("enabled: true\ntopic: mon-sujet\nmin_level: WARNING\n", encoding="utf-8")
    config = load_notify_config(path)
    assert config.url == "https://ntfy.sh/mon-sujet" and config.min_level == "WARNING"


def test_events_for_report_selection_change_full_cash_and_critical():
    events = build_events(_snapshot(), _snapshot(month="2026-08", selected=("ESE.PA",)))
    assert [e["code"] for e in events] == ["REPORT_READY", "SELECTION_CHANGED"]
    cash = build_events(_snapshot(cash=1.0))
    assert "FULL_CASH" in [e["code"] for e in cash]
    critical = build_events(_snapshot(status="CRITICAL", alerts=[{"level": "CRITICAL", "code": "STALE_DATA"}]))
    assert critical[-1]["level"] == "CRITICAL" and "STALE_DATA" in critical[-1]["message"]
    assert build_events(None, failure="yfinance")[0]["code"] == "RUN_FAILED"
    assert build_events(_snapshot(), _snapshot())[1:] == []  # pas de micro-variation


def test_disabled_config_never_calls_http(tmp_path):
    fake = FakePost()
    results = send_events(build_events(_snapshot()), NotifyConfig(), log_path=tmp_path / "log.jsonl", http_post=fake)
    assert fake.calls == [] and results[0]["status"] == "disabled"
    assert json.loads((tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()[0])["status"] == "disabled"


def test_send_filters_by_level_and_logs(tmp_path):
    fake = FakePost()
    config = NotifyConfig(enabled=True, topic="t", min_level="WARNING")
    events = build_events(_snapshot(), _snapshot(month="2026-08", selected=("ESE.PA",)))
    results = send_events(events, config, log_path=tmp_path / "log.jsonl", http_post=fake)
    assert [r["status"] for r in results] == ["filtered", "sent"]
    url, body, headers = fake.calls[0]
    assert url == "https://ntfy.sh/t" and "ESE.PA -> PAASI.PA" in body and headers["Priority"] == "4"
    assert len((tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_http_failure_is_logged_not_raised(tmp_path):
    results = send_events(build_events(_snapshot()), NotifyConfig(enabled=True, topic="t"),
                          log_path=tmp_path / "log.jsonl", http_post=FakePost(fail=True))
    assert results[0]["status"] == "error" and "réseau" in results[0]["detail"]
    assert send_events(build_events(_snapshot()), NotifyConfig(enabled=True, topic="t"),
                       log_path=tmp_path / "l2.jsonl", http_post=FakePost(status=500))[0]["status"] == "error"


@pytest.mark.slow
def test_run_month_notify_uses_config_and_reports_failures(tmp_path, monkeypatch, capsys):
    index = pd.bdate_range("2016-01-01", "2026-08-31")
    rng = np.random.default_rng(3)
    prices = pd.DataFrame({"CW8.PA": 100 * np.cumprod(1 + rng.normal(0.0004, 0.01, len(index))),
                           "ESE.PA": 100 * np.cumprod(1 + rng.normal(0.0003, 0.012, len(index)))}, index=index)
    data = tmp_path / "prices.csv"
    prices.rename_axis("Date").to_csv(data)
    assets = tmp_path / "assets.yaml"
    assets.write_text("universe:\n  - {ticker: CW8.PA, name: W, category: monde, universe_active: true, notes: ''}\n"
                      "  - {ticker: ESE.PA, name: S, category: us, universe_active: true, notes: ''}\n",
                      encoding="utf-8")
    config = tmp_path / "notify.yaml"
    config.write_text("enabled: true\ntopic: test\n", encoding="utf-8")
    fake = FakePost()
    monkeypatch.setattr(notify, "_urllib_post", fake)
    common = ["--data", str(data), "--assets", str(assets), "--output-dir", str(tmp_path / "m"),
              "--paper-dir", str(tmp_path / "p"), "--notify-config", str(config), "--log-dir", str(tmp_path / "logs")]
    assert main.main(["run-month", "--report-date", "2026-08-31", "--notify", *common]) in (0, 2)
    assert fake.calls and "Notifications : " in capsys.readouterr().out
    n_calls = len(fake.calls)
    assert main.main(["run-month", "--report-date", "2026-08-31", *common]) in (0, 2)
    assert len(fake.calls) == n_calls  # sans --notify : rien n'est envoyé
    assert main.main(["run-month", "--notify", *common[:-6], "--data", str(tmp_path / "absent.csv"),
                      "--notify-config", str(config), "--log-dir", str(tmp_path / "logs")]) == 1
    last = json.loads((tmp_path / "logs" / "notifications.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert last["code"] == "RUN_FAILED" and last["status"] == "sent" and fake.calls[-1][2]["Priority"] == "5"

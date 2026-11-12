import json

import pytest

import main as cli
from src.paper_trading import (
    PAPER_STATUSES,
    PaperTradingError,
    compare_monthly_reports,
    create_paper_entry_from_snapshot,
    list_monthly_snapshots,
    load_monthly_snapshot,
    load_paper_entries,
    save_paper_entry,
    update_manual_decision,
)


# --------------------------------------------------------------------------- #
# Fabrique de snapshots synthétiques (schéma identique au pipeline mensuel)
# --------------------------------------------------------------------------- #
def _snapshot(month="2026-07", *, mom_assets=("ESE.PA",), mom_weights=None,
              vt_enabled=True, vt_cash=0.16, vt_exposure=0.84, status="OK_WITH_WARNINGS",
              alert_codes=("DATA_NOT_REFRESHED",), realized_vol=0.09, drawdown=-0.14,
              capital=22000.0):
    mom_weights = mom_weights or {"CW8.PA": 0.0, "ESE.PA": 1.0, "CASH": 0.0}
    signal = f"{month}-01"
    vt = {
        "name": "Momentum + Volatility Targeting" if vt_enabled else "Volatility Targeting désactivé",
        "selected_assets": list(mom_assets) if vt_enabled else [],
        "target_weights": {"CW8.PA": 0.0, "ESE.PA": vt_exposure, "CASH": vt_cash} if vt_enabled else None,
        "cash_weight": vt_cash if vt_enabled else None,
        "invested_exposure": vt_exposure if vt_enabled else None,
        "realized_volatility": realized_vol if vt_enabled else None,
        "max_drawdown": drawdown if vt_enabled else None,
        "theoretical_capital": capital if vt_enabled else None,
        "target_volatility": 0.10 if vt_enabled else None,
        "enabled": vt_enabled,
        "status": "ACTIVE" if vt_enabled else "DISABLED",
    }
    return {
        "schema_version": "1.0",
        "metadata": {
            "schema_version": "1.0", "report_month": month, "report_date": f"{month}-05",
            "signal_date": signal, "pipeline_status": status,
        },
        "benchmark": {"target_weights": {"CW8.PA": 1.0, "CASH": 0.0}, "selected_assets": ["CW8.PA"]},
        "momentum_strategy": {
            "selected_assets": list(mom_assets), "target_weights": mom_weights,
        },
        "volatility_targeted_strategy": vt,
        "alerts": [{"level": "INFO" if c == "DATA_NOT_REFRESHED" else "WARNING", "code": c,
                    "message": f"alerte {c}"} for c in alert_codes],
        "manual_decision": {"status": "PENDING", "selected_strategy": None,
                            "approved_weights": None, "comment": None, "validated_at": None},
    }


def _write(path, snapshot):
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# 5.1 / 5.2 — snapshots
# --------------------------------------------------------------------------- #
def test_list_snapshots_empty_dir(tmp_path):
    assert list_monthly_snapshots(tmp_path) == []
    assert list_monthly_snapshots(tmp_path / "absent") == []


def test_list_snapshots_sorted_and_ignores_temp(tmp_path):
    _write(tmp_path / "2026-07-report.json", _snapshot("2026-07"))
    _write(tmp_path / "2026-06-report.json", _snapshot("2026-06"))
    # Fichiers/dossiers à ignorer.
    (tmp_path / "check-june").mkdir()
    _write(tmp_path / "check-june" / "2026-06-report.json", _snapshot("2026-06"))
    _write(tmp_path / "comparison-2026-06-2026-07.json", {"x": 1})
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")

    result = list_monthly_snapshots(tmp_path)
    assert [p.name for p in result] == ["2026-06-report.json", "2026-07-report.json"]


def test_list_snapshots_ignores_unreadable(tmp_path):
    _write(tmp_path / "2026-07-report.json", _snapshot("2026-07"))
    (tmp_path / "2026-08-report.json").write_text("{not json", encoding="utf-8")
    result = list_monthly_snapshots(tmp_path)
    assert [p.name for p in result] == ["2026-07-report.json"]


def test_load_snapshot_valid(tmp_path):
    path = _write(tmp_path / "2026-07-report.json", _snapshot())
    data = load_monthly_snapshot(path)
    assert data["schema_version"] == "1.0"


def test_load_snapshot_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_monthly_snapshot(tmp_path / "nope.json")


def test_load_snapshot_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{invalid", encoding="utf-8")
    with pytest.raises(PaperTradingError):
        load_monthly_snapshot(path)


def test_load_snapshot_missing_schema_version(tmp_path):
    snap = _snapshot()
    del snap["schema_version"]
    path = _write(tmp_path / "2026-07-report.json", snap)
    with pytest.raises(PaperTradingError):
        load_monthly_snapshot(path)


def test_load_snapshot_missing_manual_decision(tmp_path):
    snap = _snapshot()
    del snap["manual_decision"]
    path = _write(tmp_path / "2026-07-report.json", snap)
    with pytest.raises(PaperTradingError):
        load_monthly_snapshot(path)


def test_load_snapshot_rejects_nan(tmp_path):
    path = tmp_path / "nan.json"
    path.write_text('{"schema_version":"1.0","metadata":{},"manual_decision":{},"x":NaN}', encoding="utf-8")
    with pytest.raises(PaperTradingError):
        load_monthly_snapshot(path)


# --------------------------------------------------------------------------- #
# 5.3 / 5.4 / 5.5 — entrée de journal
# --------------------------------------------------------------------------- #
def test_create_entry_defaults_pending():
    entry = create_paper_entry_from_snapshot(_snapshot(), "reports/monthly/2026-07-report.json",
                                             "reports/monthly/2026-07-report.md",
                                             created_at="2026-07-09T00:00:00")
    assert entry["manual_decision_status"] == "PENDING"
    assert entry["manual_selected_strategy"] is None
    assert entry["manual_approved_weights"] is None
    assert entry["selected_strategy"] is None


@pytest.mark.parametrize("source_status", ["APPROVED_PAPER", "PENDING", "REJECTED"])
def test_create_entry_always_resets_source_decision_to_pending(source_status):
    snap = _snapshot()
    snap["manual_decision"]["status"] = source_status
    snap["manual_decision"]["selected_strategy"] = "momentum"

    entry = create_paper_entry_from_snapshot(snap, "s.json")

    assert entry["manual_decision_status"] == "PENDING"
    assert entry["manual_selected_strategy"] is None
    assert entry["manual_approved_weights"] is None


def test_create_entry_captures_suggestion_weights_alerts_sources():
    snap = _snapshot(alert_codes=("DATA_NOT_REFRESHED", "ASSET_EXCLUDED"))
    entry = create_paper_entry_from_snapshot(snap, "s.json", "s.md", created_at="2026-07-09T00:00:00")
    assert entry["system_suggested_strategy"] == "momentum_vt"
    assert entry["available_strategies"] == ["benchmark", "momentum", "momentum_vt"]
    assert entry["target_weights"]["momentum"] == {"CW8.PA": 0.0, "ESE.PA": 1.0, "CASH": 0.0}
    assert entry["alerts_summary"]["total"] == 2
    assert entry["alerts_summary"]["counts"]["WARNING"] == 1
    assert entry["source_snapshot_json"] == "s.json"
    assert entry["source_report_markdown"] == "s.md"
    assert entry["report_month"] == "2026-07"


def test_create_entry_vt_disabled_suggests_momentum():
    entry = create_paper_entry_from_snapshot(_snapshot(vt_enabled=False), "s.json")
    assert entry["system_suggested_strategy"] == "momentum"
    assert "momentum_vt" not in entry["available_strategies"]
    assert entry["target_weights"]["momentum_vt"] is None


def test_create_entry_legacy_vt_weights_without_enabled_are_active():
    snap = _snapshot()
    del snap["volatility_targeted_strategy"]["enabled"]

    entry = create_paper_entry_from_snapshot(snap, "s.json")

    assert entry["system_suggested_strategy"] == "momentum_vt"
    assert "momentum_vt" in entry["available_strategies"]


def test_create_entry_legacy_vt_without_weights_is_inactive():
    snap = _snapshot()
    del snap["volatility_targeted_strategy"]["enabled"]
    snap["volatility_targeted_strategy"]["target_weights"] = None

    entry = create_paper_entry_from_snapshot(snap, "s.json")

    assert entry["system_suggested_strategy"] == "momentum"
    assert "momentum_vt" not in entry["available_strategies"]


def test_create_entry_explicitly_disabled_vt_overrides_present_weights():
    snap = _snapshot(vt_enabled=False)
    snap["volatility_targeted_strategy"]["target_weights"] = {"ESE.PA": 0.84, "CASH": 0.16}

    entry = create_paper_entry_from_snapshot(snap, "s.json")

    assert entry["system_suggested_strategy"] == "momentum"
    assert "momentum_vt" not in entry["available_strategies"]


def test_save_and_load_entry_roundtrip(tmp_path):
    entry = create_paper_entry_from_snapshot(_snapshot(), "s.json", created_at="2026-07-09T00:00:00")
    path = save_paper_entry(entry, tmp_path / "sub" / "2026-07-paper-entry.json")
    assert path.exists()
    entries = load_paper_entries(tmp_path / "sub")
    assert len(entries) == 1
    assert entries[0]["report_month"] == "2026-07"


def test_save_entry_no_nan_and_utf8(tmp_path):
    entry = create_paper_entry_from_snapshot(_snapshot(), "s.json", created_at="2026-07-09T00:00:00")
    path = save_paper_entry(entry, tmp_path / "e.json")
    raw = path.read_text(encoding="utf-8")
    assert "NaN" not in raw and "Infinity" not in raw
    json.loads(raw)  # JSON standard valide


def test_save_entry_does_not_overwrite_approved_without_force(tmp_path):
    entry = create_paper_entry_from_snapshot(_snapshot(), "s.json", created_at="2026-07-09T00:00:00")
    approved = update_manual_decision(entry, "APPROVED_PAPER", strategy="momentum",
                                      validated_at="2026-07-09T00:00:00")
    path = tmp_path / "2026-07-paper-entry.json"
    save_paper_entry(approved, path)
    with pytest.raises(PaperTradingError):
        save_paper_entry(entry, path)  # écrasement refusé
    save_paper_entry(entry, path, force=True)  # autorisé avec force


def test_load_entries_empty_dir(tmp_path):
    assert load_paper_entries(tmp_path) == []
    assert load_paper_entries(tmp_path / "absent") == []


# --------------------------------------------------------------------------- #
# 5.6 — comparaison
# --------------------------------------------------------------------------- #
def test_compare_detects_asset_change():
    prev = _snapshot("2026-06", mom_assets=("CW8.PA",), mom_weights={"CW8.PA": 1.0, "ESE.PA": 0.0, "CASH": 0.0})
    cur = _snapshot("2026-07", mom_assets=("ESE.PA",))
    comp = compare_monthly_reports(prev, cur)
    assert comp["momentum_selected_changed"] is True
    assert comp["momentum_weights_changed"] is True
    assert comp["previous_month"] == "2026-06" and comp["current_month"] == "2026-07"


def test_compare_detects_cash_and_exposure_change():
    prev = _snapshot("2026-06", vt_cash=0.10, vt_exposure=0.90)
    cur = _snapshot("2026-07", vt_cash=0.40, vt_exposure=0.60)
    comp = compare_monthly_reports(prev, cur)
    assert comp["vt_cash_change"] == pytest.approx(0.30)
    assert comp["vt_exposure_change"] == pytest.approx(-0.30)


def test_compare_detects_alert_changes():
    prev = _snapshot("2026-06", alert_codes=("DATA_NOT_REFRESHED",))
    cur = _snapshot("2026-07", alert_codes=("DATA_NOT_REFRESHED", "STALE_DATA"))
    comp = compare_monthly_reports(prev, cur)
    assert comp["new_alert_codes"] == ["STALE_DATA"]
    assert comp["resolved_alert_codes"] == []
    assert comp["alerts_count_change"] == 1


def test_compare_no_change():
    snap = _snapshot("2026-07")
    comp = compare_monthly_reports(snap, snap)
    assert comp["momentum_selected_changed"] is False
    assert comp["vt_cash_change"] == pytest.approx(0.0)
    assert comp["new_alert_codes"] == []


def test_compare_incomplete_snapshot_is_serializable():
    comp = compare_monthly_reports({}, _snapshot("2026-07"))
    json.dumps(comp, allow_nan=False)  # sérialisable sans NaN
    assert comp["previous_month"] is None
    assert comp["vt_cash_change"] is None  # valeur absente -> None


# --------------------------------------------------------------------------- #
# décision manuelle
# --------------------------------------------------------------------------- #
def test_update_decision_approved_captures_strategy_and_weights():
    entry = create_paper_entry_from_snapshot(_snapshot(), "s.json", created_at="2026-07-09T00:00:00")
    updated = update_manual_decision(entry, "APPROVED_PAPER", strategy="momentum",
                                     comment="paper only", validated_at="2026-07-09T12:00:00")
    assert updated["manual_decision_status"] == "APPROVED_PAPER"
    assert updated["selected_strategy"] == "momentum"
    assert updated["manual_approved_weights"] == {"CW8.PA": 0.0, "ESE.PA": 1.0, "CASH": 0.0}
    # L'entrée d'origine n'est pas mutée.
    assert entry["manual_decision_status"] == "PENDING"


def test_update_decision_rejects_invalid_status():
    entry = create_paper_entry_from_snapshot(_snapshot(), "s.json", created_at="2026-07-09T00:00:00")
    with pytest.raises(PaperTradingError):
        update_manual_decision(entry, "EXECUTED")


def test_update_decision_rejects_unknown_strategy():
    entry = create_paper_entry_from_snapshot(_snapshot(), "s.json", created_at="2026-07-09T00:00:00")
    with pytest.raises(PaperTradingError):
        update_manual_decision(entry, "APPROVED_PAPER", strategy="crypto")


def test_no_status_means_real_execution():
    assert "EXECUTED" not in PAPER_STATUSES
    assert all("ORDER" not in s and "EXEC" not in s for s in PAPER_STATUSES)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_cli_paper_init_creates_file(tmp_path):
    snap_path = _write(tmp_path / "2026-07-report.json", _snapshot())
    out = tmp_path / "paper"
    code = cli.main(["paper-init", "--snapshot", str(snap_path), "--output-dir", str(out)])
    assert code == 0
    files = list(out.glob("*-paper-entry.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["manual_decision_status"] == "PENDING"


def test_cli_paper_init_no_overwrite_without_force(tmp_path):
    snap_path = _write(tmp_path / "2026-07-report.json", _snapshot())
    out = tmp_path / "paper"
    cli.main(["paper-init", "--snapshot", str(snap_path), "--output-dir", str(out)])
    # Approuve l'entrée (verrou), puis re-init sans --force -> refus (code 1).
    cli.main(["paper-decision", "--month", "2026-07", "--status", "APPROVED_PAPER",
              "--strategy", "momentum", "--paper-dir", str(out)])
    code = cli.main(["paper-init", "--snapshot", str(snap_path), "--output-dir", str(out)])
    assert code == 1
    code_force = cli.main(["paper-init", "--snapshot", str(snap_path), "--output-dir", str(out), "--force"])
    assert code_force == 0


def test_cli_paper_list_empty(tmp_path, capsys):
    code = cli.main(["paper-list", "--paper-dir", str(tmp_path / "empty")])
    assert code == 0
    assert "Aucune" in capsys.readouterr().out


def test_cli_compare_reports_with_two_snapshots(tmp_path):
    p1 = _write(tmp_path / "2026-06-report.json", _snapshot("2026-06", mom_assets=("CW8.PA",)))
    p2 = _write(tmp_path / "2026-07-report.json", _snapshot("2026-07", mom_assets=("ESE.PA",)))
    out = tmp_path / "cmp.json"
    code = cli.main(["compare-reports", "--previous", str(p1), "--current", str(p2), "--output", str(out)])
    assert code == 0
    comp = json.loads(out.read_text(encoding="utf-8"))
    assert comp["momentum_selected_changed"] is True


def test_cli_paper_decision_rejects_unknown_strategy(tmp_path):
    snap_path = _write(tmp_path / "2026-07-report.json", _snapshot())
    out = tmp_path / "paper"
    cli.main(["paper-init", "--snapshot", str(snap_path), "--output-dir", str(out)])
    code = cli.main(["paper-decision", "--month", "2026-07", "--status", "APPROVED_PAPER",
                     "--strategy", "unknown", "--paper-dir", str(out)])
    assert code == 1


def test_cli_paper_decision_invalid_status_exits_nonzero(tmp_path):
    # --status EXECUTED n'est pas un choix argparse valide -> code 1 (erreur
    # d'usage) ; le code 2 reste réservé au statut CRITICAL d'un rapport.
    assert cli.main(["paper-decision", "--month", "2026-07", "--status", "EXECUTED"]) == 1


def test_cli_compare_output_is_console_safe(tmp_path, capsys):
    # Non-régression : la sortie ne doit contenir aucun caractère non encodable
    # par la console Windows (cp1252), sinon la CLI plante à l'affichage.
    p1 = _write(tmp_path / "2026-06-report.json", _snapshot("2026-06", vt_cash=0.10, vt_exposure=0.90))
    p2 = _write(tmp_path / "2026-07-report.json", _snapshot("2026-07", vt_cash=0.40, vt_exposure=0.60))
    cli.main(["compare-reports", "--previous", str(p1), "--current", str(p2)])
    out = capsys.readouterr().out
    out.encode("cp1252")  # ne doit pas lever UnicodeEncodeError


def test_cli_commands_never_mention_real_orders(tmp_path, capsys):
    snap_path = _write(tmp_path / "2026-07-report.json", _snapshot())
    out_dir = tmp_path / "paper"
    cli.main(["paper-init", "--snapshot", str(snap_path), "--output-dir", str(out_dir)])
    cli.main(["paper-list", "--paper-dir", str(out_dir)])
    text = capsys.readouterr().out.lower()
    for word in ("ordre réel", "exécuté un ordre", "buy order", "sell order", "executed order"):
        assert word not in text

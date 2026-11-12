"""Mise à jour incrémentale des prix, contrôles qualité et archives brutes.

- ``incremental_refresh`` : ne télécharge que les jours manquants (plus un
  chevauchement de contrôle). Si les prix du chevauchement ont changé (prix
  ajustés réécrits après un dividende ou un split), l'historique complet du
  ticker est retéléchargé. Un nouveau ticker est téléchargé en entier.
- ``quality_checks`` : sauts journaliers suspects, ticker figé (plus de prix),
  trous de plusieurs séances, sur une fenêtre récente.
- ``archive_raw`` : copie datée du téléchargement brut (``data/raw``, ignoré par
  Git), seules les ``keep`` plus récentes sont conservées.

Aucune donnée n'est inventée (pas de forward-fill) et aucun ordre n'est passé.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd

OVERLAP_DAYS = 10
ADJUSTMENT_TOLERANCE = 0.005
JUMP_THRESHOLD = 0.15
STALE_BUSINESS_DAYS = 5
GAP_MIN_DAYS = 3
RECENT_WINDOW_DAYS = 45

Downloader = Callable[[Sequence[str], str], pd.DataFrame]


def incremental_refresh(
    existing: pd.DataFrame | None,
    tickers: Sequence[str],
    downloader: Downloader,
    *,
    start: str,
    full: bool = False,
    overlap_days: int = OVERLAP_DAYS,
    tolerance: float = ADJUSTMENT_TOLERANCE,
) -> tuple[pd.DataFrame, dict]:
    """Met à jour ``existing`` avec les prix récents de ``tickers``.

    Returns
    -------
    (prices, info)
        ``info`` : ``mode`` (``full`` / ``incremental``), ``raw`` (téléchargements
        bruts concaténés), ``new_rows``, ``new_tickers``, ``adjusted_tickers``,
        ``no_new_data`` (tickers sans prix récent).
    """
    tickers = list(dict.fromkeys(tickers))
    if full or existing is None or existing.empty:
        prices = downloader(tickers, start)
        return prices, {"mode": "full", "raw": prices, "new_rows": int(len(prices)), "new_tickers": list(prices.columns),
                        "adjusted_tickers": [], "no_new_data": [t for t in tickers if t not in prices.columns]}

    existing = existing.sort_index()
    known = [t for t in tickers if t in existing.columns and existing[t].notna().any()]
    new_tickers = [t for t in tickers if t not in known]
    last_date = existing.index.max()
    recent_start = (last_date - pd.Timedelta(days=overlap_days)).strftime("%Y-%m-%d")

    raws = []
    recent = downloader(known, recent_start) if known else pd.DataFrame()
    raws.append(recent)
    adjusted = []
    for ticker in recent.columns:
        overlap = existing.index.intersection(recent.index)
        old, new = existing.loc[overlap, ticker], recent.loc[overlap, ticker]
        both = old.notna() & new.notna()
        if both.any() and ((new[both] / old[both] - 1.0).abs() > tolerance).any():
            adjusted.append(ticker)
    to_full = adjusted + new_tickers
    full_download = downloader(to_full, start) if to_full else pd.DataFrame()
    raws.append(full_download)

    merged = existing.copy()
    if not recent.empty:
        recent_part = recent.drop(columns=[t for t in adjusted if t in recent.columns])
        merged = merged.combine_first(recent_part)
        merged.update(recent_part)  # les valeurs récentes (plus fiables) remplacent le chevauchement
    if not full_download.empty:
        merged = merged.reindex(merged.index.union(full_download.index))
        for ticker in full_download.columns:
            merged[ticker] = full_download[ticker]  # historique complet retéléchargé : remplace l'ancien
    merged = merged.sort_index()
    merged = merged[[c for c in tickers if c in merged.columns] + [c for c in merged.columns if c not in tickers]]
    raw = pd.concat([r for r in raws if not r.empty], axis=1) if any(not r.empty for r in raws) else pd.DataFrame()
    return merged, {
        "mode": "incremental",
        "raw": raw,
        "new_rows": int(len(merged.index.difference(existing.index))),
        "new_tickers": [t for t in new_tickers if t in full_download.columns],
        "adjusted_tickers": adjusted,
        "no_new_data": [t for t in tickers if t not in recent.columns and t not in full_download.columns],
    }


def quality_checks(
    prices: pd.DataFrame,
    *,
    since: pd.Timestamp | str | None = None,
    jump_threshold: float = JUMP_THRESHOLD,
    stale_business_days: int = STALE_BUSINESS_DAYS,
    gap_min_days: int = GAP_MIN_DAYS,
    ignore: Sequence[str] = (),
) -> list[dict]:
    """Anomalies détectées sur la fenêtre ``[since, fin]`` (défaut : 45 derniers jours).

    Chaque anomalie : ``{"ticker", "type", "date", "detail"}`` avec ``type`` parmi
    ``JUMP`` (variation journalière > seuil), ``STALE`` (plus de prix depuis N
    jours ouvrés alors que d'autres tickers cotent), ``GAP`` (trou d'au moins
    ``gap_min_days`` séances au milieu de données).
    """
    if prices.empty:
        return []
    prices = prices.sort_index()
    end = prices.dropna(how="all").index.max()
    since = pd.Timestamp(since) if since is not None else end - pd.Timedelta(days=RECENT_WINDOW_DAYS)
    anomalies: list[dict] = []
    for ticker in prices.columns:
        if ticker in ignore:
            continue
        series = prices[ticker]
        valid = series.dropna()
        if valid.empty:
            continue
        # Sauts : rendement entre deux prix consécutifs disponibles.
        returns = valid.pct_change()
        for date, value in returns[(returns.index >= since) & (returns.abs() > jump_threshold)].items():
            anomalies.append({"ticker": ticker, "type": "JUMP", "date": date.date().isoformat(),
                              "detail": f"variation de {value:+.1%} en une séance"})
        # Ticker figé : dernier prix trop ancien par rapport aux autres.
        lag = len(pd.bdate_range(valid.index.max(), end)) - 1
        if lag >= stale_business_days:
            anomalies.append({"ticker": ticker, "type": "STALE", "date": valid.index.max().date().isoformat(),
                              "detail": f"aucun prix depuis {lag} séances ouvrées"})
        # Trous : séances sans prix entre deux prix, alors que la majorité cote.
        window = prices.loc[(prices.index >= since) & (prices.index >= valid.index.min())
                            & (prices.index <= valid.index.max())]
        others_quoted = window.drop(columns=ticker).notna().mean(axis=1) >= 0.5 if window.shape[1] > 1 else \
            pd.Series(True, index=window.index)
        missing = window[ticker].isna() & others_quoted
        run, run_start = 0, None
        for date, is_missing in missing.items():
            if is_missing:
                run, run_start = run + 1, run_start or date
            else:
                if run >= gap_min_days:
                    anomalies.append({"ticker": ticker, "type": "GAP", "date": run_start.date().isoformat(),
                                      "detail": f"{run} séances sans prix"})
                run, run_start = 0, None
    return anomalies


def archive_raw(raw: pd.DataFrame, raw_dir: str | Path, *, stamp: str | None = None, keep: int = 6) -> Path | None:
    """Archive le téléchargement brut et ne garde que les ``keep`` plus récents."""
    if raw is None or raw.empty:
        return None
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or pd.Timestamp.now().strftime("%Y-%m-%d")
    path = raw_dir / f"{stamp}-prices.csv"
    raw.to_csv(path)
    archives = sorted(raw_dir.glob("*-prices.csv"))
    for old in archives[:-keep] if keep > 0 else archives:
        old.unlink()
    return path


def anomaly_lines(anomalies: list[dict]) -> list[str]:
    return [f"{a['type']:5} {a['ticker']:9} {a['date']} : {a['detail']}" for a in anomalies]

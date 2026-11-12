"""Historique long en EUR prolongé par proxys (recherche uniquement).

Construit des prix **mensuels** en euros depuis ~2004 pour les ETF PEA de
l'univers, en chaînant vers le passé les rendements de proxys de même
exposition (``config/long_history.yaml``). Chaque mois garde la trace de sa
source : le ticker réel ou le proxy utilisé (données **synthétiques**).

Le rapport mensuel n'utilise jamais ces données : elles servent à la
recherche (``research --long``) et aux stress tests (``stress``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.vehicles import tracking_stats

Downloader = Callable[[Sequence[str], str], pd.DataFrame]
MONTH_END = "ME"


def load_long_config(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration d'historique long introuvable : {path}")
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    chains = raw.get("chains")
    if not isinstance(chains, dict) or not chains:
        raise ValueError(f"{path} : 'chains' doit associer chaque ticker à une liste de proxys.")
    for target, chain in chains.items():
        if not isinstance(chain, list) or not chain:
            raise ValueError(f"{path} : chaîne vide ou invalide pour {target}.")
        for link in chain:
            if not isinstance(link, dict) or "ticker" not in link or link.get("currency") not in ("EUR", "USD"):
                raise ValueError(f"{path} : chaque proxy de {target} doit avoir ticker et currency (EUR ou USD).")
            yield_pct = link.get("dividend_yield_pct", 0.0)
            if isinstance(yield_pct, bool) or not isinstance(yield_pct, (int, float)) or not 0 <= yield_pct <= 10:
                raise ValueError(f"{path} : dividend_yield_pct de {link['ticker']} doit être entre 0 et 10.")
    return {"fx_ticker": raw.get("fx_ticker", "EURUSD=X"), "start": str(raw.get("start", "2003-12-01")),
            "chains": chains}


def proxy_tickers(config: dict) -> list[str]:
    tickers = [link["ticker"] for chain in config["chains"].values() for link in chain]
    return list(dict.fromkeys([*tickers, config["fx_ticker"]]))


def to_eur_monthly(daily: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Prix mensuels (fin de mois) en EUR ; USD / (USD par EUR)."""
    monthly = daily.sort_index().resample(MONTH_END).last()
    fx = monthly.get(config["fx_ticker"])
    out = {}
    for chain in config["chains"].values():
        for link in chain:
            ticker = link["ticker"]
            if ticker not in monthly.columns or ticker in out:
                continue
            series = monthly[ticker]
            if link["currency"] == "USD":
                if fx is None:
                    raise ValueError(f"Taux {config['fx_ticker']} manquant pour convertir {ticker}.")
                series = series / fx
            yield_pct = float(link.get("dividend_yield_pct", 0.0))
            if yield_pct:
                # Indice de prix sans dividendes : ajout d'un rendement de dividende estimé, capitalisé chaque mois.
                valid = series.notna().cumsum() > 0
                months = np.where(valid, np.cumsum(valid) - 1, 0)
                series = series * (1.0 + yield_pct / 100.0) ** (months / 12.0)
            out[ticker] = series
    return pd.DataFrame(out)


def build_long_history(real_monthly: pd.DataFrame, proxies_eur: pd.DataFrame, config: dict) -> dict:
    """Chaîne chaque ticker réel avec ses proxys (rendements), du plus récent au plus ancien.

    Returns
    -------
    dict
        ``prices`` (mensuels EUR), ``sources`` (ticker d'origine par mois),
        ``tracking`` (écart de suivi de chaque proxy sur la période commune avec
        la série déjà construite).
    """
    index = real_monthly.index.union(proxies_eur.index).sort_values()
    prices, sources, tracking = {}, {}, []
    for target, chain in config["chains"].items():
        if target not in real_monthly.columns:
            continue
        series = real_monthly[target].reindex(index)
        source = pd.Series(np.where(series.notna(), target, None), index=index, dtype=object)
        for link in chain:
            proxy = proxies_eur.get(link["ticker"])
            if proxy is None or proxy.dropna().empty:
                continue
            proxy = proxy.reindex(index)
            stats = tracking_stats(series, proxy, periods_per_year=12)
            tracking.append({"target": target, "proxy": link["ticker"], "note": link.get("note", ""), **stats})
            first = series.first_valid_index()
            before = proxy.loc[proxy.index < first].dropna() if first is not None else proxy.dropna()
            if before.empty or first is None:
                continue
            anchor = proxy.loc[:first].dropna()
            if anchor.empty:
                continue
            synthetic = series.loc[first] * before / anchor.iloc[-1]
            series = series.combine_first(synthetic)
            source.loc[synthetic.index] = link["ticker"]
        prices[target] = series
        sources[target] = source
    for extra in real_monthly.columns:
        if extra not in prices:
            prices[extra] = real_monthly[extra].reindex(index)
            sources[extra] = pd.Series(np.where(prices[extra].notna(), extra, None), index=index, dtype=object)
    prices_df = pd.DataFrame(prices).loc[lambda df: df.index >= pd.Timestamp(config["start"])]
    sources_df = pd.DataFrame(sources).reindex(prices_df.index)
    return {"prices": prices_df, "sources": sources_df, "tracking": tracking}


def synthetic_mask(sources: pd.DataFrame) -> pd.DataFrame:
    """Vrai quand le prix du mois provient d'un proxy (et non du ticker lui-même)."""
    return pd.DataFrame({c: sources[c].notna() & (sources[c] != c) for c in sources.columns}, index=sources.index)


def synthetic_share(sources: pd.DataFrame) -> dict[str, dict]:
    """Par ticker : première date, première date réelle, part synthétique."""
    mask = synthetic_mask(sources)
    summary = {}
    for column in sources.columns:
        available = sources[column].notna()
        if not available.any():
            continue
        real = available & ~mask[column]
        summary[column] = {
            "start": available[available].index.min().date().isoformat(),
            "real_start": real[real].index.min().date().isoformat() if real.any() else None,
            "synthetic_months": int(mask[column].sum()),
            "synthetic_share": float(mask[column].sum() / available.sum()),
        }
    return summary


def refresh_long_history(real_daily: pd.DataFrame, downloader: Downloader, config: dict,
                         output_prices: str | Path, output_sources: str | Path) -> dict:
    """Télécharge les proxys, construit et sauvegarde l'historique long mensuel."""
    proxies_daily = downloader(proxy_tickers(config), config["start"])
    real_monthly = real_daily.sort_index().resample(MONTH_END).last()
    last_real = real_daily.dropna(how="all").index.max().normalize()
    if len(real_monthly) and last_real < real_monthly.index[-1]:
        real_monthly = real_monthly.iloc[:-1]  # mois en cours incomplet exclu
    proxies_eur = to_eur_monthly(proxies_daily, config).loc[lambda df: df.index <= real_monthly.index.max()]
    built = build_long_history(real_monthly, proxies_eur, config)
    Path(output_prices).parent.mkdir(parents=True, exist_ok=True)
    built["prices"].rename_axis("Date").to_csv(output_prices)
    built["sources"].rename_axis("Date").to_csv(output_sources)
    return built


def load_long_history(prices_path: str | Path, sources_path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    prices_path, sources_path = Path(prices_path), Path(sources_path)
    if not prices_path.exists() or not sources_path.exists():
        raise FileNotFoundError("Historique long absent : lance `python main.py refresh-data --long`.")
    prices = pd.read_csv(prices_path, index_col=0, parse_dates=True)
    sources = pd.read_csv(sources_path, index_col=0, parse_dates=True).reindex(prices.index)
    return prices, sources

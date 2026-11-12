"""Tests par propriétés (hypothesis) : invariants valables pour toute donnée générée."""

import numpy as np
import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.contribution_plan import plan_contribution
from src.costs import FeeModel
from src.ledger import state_at
from src.monthly_pipeline import MonthlyPipelineConfig
from src.strategies import REGISTRY, StrategyContext, build_strategy

SETTINGS = settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
CONFIG = MonthlyPipelineConfig()
TICKERS = ["CW8.PA", "ESE.PA", "PAEEM.PA", "OBLI.PA"]


@st.composite
def price_panels(draw):
    """Prix mensuels positifs ; l'obligataire commence plus tard (NaN initiaux)."""
    n = draw(st.integers(min_value=30, max_value=60))
    returns = draw(st.lists(st.lists(st.floats(-0.25, 0.25, allow_nan=False), min_size=4, max_size=4),
                            min_size=n, max_size=n))
    bond_start = draw(st.integers(min_value=0, max_value=n // 2))
    index = pd.date_range("2015-01-31", periods=n, freq="ME")
    prices = pd.DataFrame(100 * np.cumprod(1 + np.array(returns), axis=0), index=index, columns=TICKERS)
    prices.iloc[:bond_start, 3] = np.nan
    return prices


def _ctx(satellite="momentum"):
    return StrategyContext(config=CONFIG, equities=tuple(TICKERS[:3]), bond="OBLI.PA", satellite=satellite,
                           fixed_allocation=((TICKERS[0], 0.85), (TICKERS[1], 0.15)))


@SETTINGS
@given(prices=price_panels(), name=st.sampled_from(sorted(REGISTRY)))
def test_every_registry_strategy_yields_valid_weights(prices, name):
    bundle = build_strategy(name, prices, _ctx())
    for weights in (bundle["target_weights"], bundle["executed_weights"]):
        values = weights.to_numpy()
        assert not np.isnan(values).any()
        assert (values >= -1e-9).all() and (values <= 1 + 1e-9).all()
        assert np.allclose(weights.sum(axis=1), 1.0)


@SETTINGS
@given(prices=price_panels(), name=st.sampled_from(sorted(REGISTRY)), cut=st.floats(0.3, 0.9),
       shock=st.floats(0.2, 5.0))
def test_future_prices_never_change_past_decisions(prices, name, cut, shock):
    k = int(len(prices) * cut)
    changed = prices.copy()
    changed.iloc[k + 1:] *= shock  # tout ce qui suit le mois k est modifié
    original = build_strategy(name, prices, _ctx())
    perturbed = build_strategy(name, changed, _ctx())
    pd.testing.assert_frame_equal(original["target_weights"].iloc[:k + 1], perturbed["target_weights"].iloc[:k + 1])
    # Le poids exécuté au mois k+1 est décidé en fin de mois k : lui non plus ne bouge pas.
    pd.testing.assert_frame_equal(original["executed_weights"].iloc[:k + 2], perturbed["executed_weights"].iloc[:k + 2])


@SETTINGS
@given(
    quotes=st.lists(st.floats(1.0, 800.0), min_size=3, max_size=3),
    holdings=st.lists(st.integers(0, 50), min_size=3, max_size=3),
    raw_weights=st.lists(st.floats(0.0, 1.0), min_size=4, max_size=4).filter(lambda w: sum(w) > 0.05),
    contribution=st.floats(0.0, 5000.0),
    cash=st.floats(0.0, 2000.0),
    fixed=st.floats(0.0, 5.0),
)
def test_planner_never_overspends_never_sells_whole_shares(quotes, holdings, raw_weights, contribution, cash, fixed):
    tickers = ["A.PA", "B.PA", "C.PA"]
    total = sum(raw_weights)
    target = {t: w / total for t, w in zip([*tickers, "CASH"], raw_weights, strict=True)}
    plan = plan_contribution(dict(zip(tickers, holdings, strict=True)), dict(zip(tickers, quotes, strict=True)),
                             target, contribution=contribution, cash_available=cash,
                             fee_model=FeeModel(proportional=0.001, fixed_per_order=fixed))
    buys = plan["table"]["parts_a_acheter"]
    assert (buys >= 0).all() and all(float(b).is_integer() for b in buys)
    assert plan["total_spent"] <= contribution + cash + 1e-6
    assert plan["cash_after"] >= -1e-6


@st.composite
def transaction_journals(draw):
    """Journaux valides : on ne vend jamais plus que ce qui est détenu."""
    rows, held, day = [], 0.0, pd.Timestamp("2026-01-01")
    for _ in range(draw(st.integers(1, 15))):
        day += pd.Timedelta(days=draw(st.integers(1, 20)))
        kind = draw(st.sampled_from(["VERSEMENT", "ACHAT", "VENTE", "FRAIS", "DIVIDENDE"]))
        if kind == "ACHAT":
            parts = draw(st.integers(1, 20))
            held += parts
            rows.append((day, "ACHAT", "A.PA", parts, draw(st.floats(1, 500)), None))
        elif kind == "VENTE" and held >= 1:
            parts = draw(st.integers(1, int(held)))
            held -= parts
            rows.append((day, "VENTE", "A.PA", parts, draw(st.floats(1, 500)), None))
        elif kind != "VENTE":
            rows.append((day, kind, "", np.nan, np.nan, draw(st.floats(1, 1000))))
    frame = pd.DataFrame(rows, columns=["date", "type", "ticker", "parts", "prix", "montant"])
    frame["enveloppe"], frame["frais"] = "pea", 0.5
    frame.loc[frame["type"].isin(["ACHAT", "VENTE"]), "montant"] = frame["parts"] * frame["prix"]
    return frame


@SETTINGS
@given(journal=transaction_journals())
def test_ledger_positions_never_negative(journal):
    for when in journal["date"]:
        state = state_at(journal, when)
        for envelope in state["enveloppes"].values():
            assert all(parts > 0 for parts in envelope["parts"].values())

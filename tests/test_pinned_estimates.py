"""Pinned border pass-through estimates and the P15 replication gate.

Reads data/published/border_pt_replication.csv and border_pt_event_2018_19.csv (make border-pt);
skipped if not built. Pins are the P15 run (data vintage 2026-10); 2018-19 data change only with
Census revisions, so a pin that moves needs a look, not a new number.
"""

import math

import polars as pl
import pytest

from tpt.models import border_pt as bp

pytestmark = pytest.mark.skipif(not bp.OUT.exists(), reason="run make border-pt")

# (spec, outcome) -> coefficient, P15 run
PINNED = {
    ("main", "uv"): 0.167, ("main", "uv_dut"): 0.942, ("main", "qty"): -1.956,
    ("main", "val"): -1.835,
    ("main_trim3", "uv"): -0.058, ("main_trim3", "uv_dut"): 0.723, ("main_trim3", "qty"): -1.664,
    ("arw", "uv"): -0.107, ("arw", "qty"): -1.122, ("arw", "val"): -1.393,
    ("fgkk", "uv"): 0.156, ("fgkk", "uv_dut"): 0.877, ("fgkk", "qty"): -1.969,
    ("fgkk", "val"): -1.931,
}  # fmt: skip
TOL = {"uv": 0.02, "uv_dut": 0.02, "qty": 0.05, "val": 0.05}


@pytest.fixture(scope="module")
def est() -> dict:
    df = pl.read_csv(bp.OUT)
    return {(r["spec"], r["outcome"]): r for r in df.iter_rows(named=True)}


@pytest.mark.parametrize(("key", "coef"), PINNED.items(), ids=lambda v: str(v))
def test_pinned(est, key, coef):
    assert est[key]["coef"] == pytest.approx(coef, abs=TOL[key[1]])


def test_gate_pre_duty_prices_near_complete_pass_through(est):
    """Every 2018-19 unit-value estimate: foreign exporters absorbed under a quarter of the
    tariff (95% CI above -0.25), as in ARW (-0.003) and FGKK (0.00)."""
    for (spec, outcome), r in est.items():
        if outcome == "uv":
            assert r["ci_low"] > -0.25, spec
            assert abs(r["coef"]) < 0.25, spec


def _z(r: dict) -> float:
    return abs(r["coef"] - r["published_coef"]) / math.hypot(r["se"], r["published_se"])


def test_gate_trade_responses_match_published(est):
    """Quantity and value elasticities within 2 combined SEs of ARW Table 1 / FGKK Table IV."""
    for key in [("arw", "qty"), ("arw", "val"), ("fgkk", "qty"), ("fgkk", "val")]:
        assert _z(est[key]) < 2, key


def test_known_gap_arw_unit_value(est):
    """ARW-exact unit value is 3.3 combined SEs below ARW (-0.107 vs -0.003): documented in
    DATA.md (yuan within 2018 under country x year FE; our sample is 55% of theirs). Fails if
    the gap closes or widens, so the note stays accurate."""
    assert 2.5 < _z(est[("arw", "uv")]) < 4.0


@pytest.fixture(scope="module")
def ev() -> pl.DataFrame:
    if not bp.EVENT_OUT.exists():
        pytest.skip("run make border-pt")
    return pl.read_csv(bp.EVENT_OUT)


def _path(ev: pl.DataFrame, sample: str, outcome: str) -> dict[int, float]:
    p = ev.filter(pl.col("sample") == sample, pl.col("outcome") == outcome)
    return dict(zip(p["k"], p["coef"], strict=True))


def test_event_study_fgkk_sample_no_pre_trend_no_price_decline(ev):
    """FGKK window (to 2019-04): flat pre-period, no fall in pre-duty prices after the tariff,
    duty-inclusive prices up and quantities down (FGKK Figure II)."""
    for o in ("uv", "qty"):
        assert all(abs(c) < 0.05 for k, c in _path(ev, "fgkk", o).items() if k < -1), o
    uv = _path(ev, "fgkk", "uv")
    assert min(c for k, c in uv.items() if k >= 0) > -0.03
    assert _path(ev, "fgkk", "uv_dut")[6] > 0.1
    assert _path(ev, "fgkk", "qty")[0] < -0.2


def test_event_study_full_sample_shows_2019_run_up(ev):
    """Through 2019 the quantity pre-trend (stockpiling before the Sep 2019 actions) is large;
    DATA.md explains it. Fails if it disappears, so the note stays accurate."""
    assert _path(ev, "full", "qty")[-6] < -0.1

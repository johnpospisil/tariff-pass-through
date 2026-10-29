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


# --- P16: 2025-26 (data vintage 2026-10, through 2026-08) ------------------------
# 2025-26 months are revised by Census (annual revision each June) and extended monthly, so
# these pins will drift on refresh; P24 decides whether they warn or fail.

PINNED_25 = {
    ("main", "uv", "all"): 0.041, ("main", "uv_dut", "all"): 0.508,
    ("main", "qty", "all"): -0.706, ("main", "val", "all"): -0.659,
    ("main_trim3", "uv", "all"): -0.039, ("pre_ruling", "uv", "all"): -0.001,
    ("implied_iv", "uv", "all"): 0.086, ("implied_iv", "uv_dut", "all"): 1.061,
    ("china_trim3", "uv", "china"): -0.009, ("authority_trim3", "uv", "s232"): -0.077,
    ("authority_trim3", "uv", "ieepa"): 0.000,
}  # fmt: skip
TOL_25 = {"uv": 0.02, "uv_dut": 0.03, "qty": 0.05, "val": 0.05}


@pytest.fixture(scope="module")
def pt() -> dict:
    if not bp.PT_OUT.exists():
        pytest.skip("run make border-pt-2025")
    df = pl.read_csv(bp.PT_OUT)
    return {(r["period"], r["spec"], r["outcome"], r["group"], r["term"]): r
            for r in df.iter_rows(named=True)}  # fmt: skip


def _get(pt: dict, period: str, spec: str, outcome: str, group: str) -> dict:
    hits = [r for k, r in pt.items() if k[:4] == (period, spec, outcome, group)]
    assert len(hits) == 1, (period, spec, outcome, group)
    return hits[0]


@pytest.mark.parametrize(("key", "coef"), PINNED_25.items(), ids=lambda v: str(v))
def test_pinned_2025(pt, key, coef):
    assert _get(pt, "2025_26", *key)["coef"] == pytest.approx(coef, abs=TOL_25[key[1]])


def test_2025_pre_duty_prices_near_complete_pass_through(pt):
    """Pooled 2025-26 pre-duty unit-value estimates (statutory, trimmed, pre-ruling, IV on the
    implied rate): exporters absorbed under a quarter of the tariff (95% CI above -0.25)."""
    for spec in ("main", "twoway", "main_trim3", "pre_ruling", "implied_iv"):
        r = _get(pt, "2025_26", spec, "uv", "all")
        assert r["ci_low"] > -0.25 and abs(r["coef"]) < 0.25, spec


def test_2018_main_matches_replication_file(pt):
    """border_pt.csv repeats the P15 main estimates; both files come from the same code."""
    for o in ("uv", "qty"):
        assert _get(pt, "2018_19", "main", o, "all")["coef"] == pytest.approx(
            PINNED[("main", o)], abs=TOL[o]
        )


def test_mxp_locality_cross_check_agrees(pt):
    """BLS import prices by origin (before duties) do not fall with tariffs either: 2025-26
    statutory coefficient +0.011 (0.016)."""
    r = pt[("2025_26", "mxp_locality", "mxp", "all", bp.X)]
    assert r["coef"] == pytest.approx(0.011, abs=0.02)
    assert r["ci_low"] > -0.25


@pytest.fixture(scope="module")
def ev25() -> pl.DataFrame:
    if not bp.EVENT25_OUT.exists():
        pytest.skip("run make border-pt-2025")
    return pl.read_csv(bp.EVENT25_OUT)


def test_event_study_2025_front_running_and_no_price_decline(ev25):
    """2025: quantities peak in the month before the tariff (k = -1 is 10-14% above k = -6..-2,
    the stockpiling seen in P14), fall on impact; pre-duty unit values do not fall after the
    tariff; duty-inclusive unit values rise about 10%."""
    qty = _path(ev25, "pre_ruling", "qty")
    assert all(qty[k] < -0.05 for k in range(-6, -1))
    assert qty[0] < -0.1
    uv = _path(ev25, "pre_ruling", "uv")
    assert min(c for k, c in uv.items() if k >= 0) > -0.02
    assert _path(ev25, "pre_ruling", "uv_dut")[0] > 0.07


# --- P17: robustness grid ---------------------------------------------------------

from tpt.models import robustness as rb  # noqa: E402


@pytest.fixture(scope="module")
def grid() -> dict:
    if not rb.OUT.exists():
        pytest.skip("run make robustness")
    df = pl.read_csv(rb.OUT)
    return {(r["period"], r["outcome"], r["cleaning"], r["variant"]): r
            for r in df.iter_rows(named=True)}  # fmt: skip


def test_grid_baseline_reproduces_main(grid):
    assert grid[("2025_26", "uv", "w1", "baseline")]["coef"] == pytest.approx(0.041, abs=0.02)
    assert grid[("2025_26", "uv", "trim3", "baseline")]["coef"] == pytest.approx(-0.039, abs=0.02)
    assert grid[("2018_19", "uv", "w1", "baseline")]["coef"] == pytest.approx(0.167, abs=0.02)


def test_unweighted_grid_never_finds_large_exporter_absorption(grid):
    """Every unweighted 2025-26 pre-duty estimate is between -0.10 and +0.30 (DATA.md P17)."""
    for (p, o, _c, v), r in grid.items():
        if p == "2025_26" and o == "uv" and v != "weighted":
            assert -0.10 < r["coef"] < 0.30, (_c, v)


def test_value_weighted_2025_is_the_documented_outlier(grid):
    """Value-weighted 2025-26 estimates are negative (-0.18 to -0.36), driven by HS 84
    (DATA.md P17). Fails if that changes, so the note stays accurate."""
    for c in rb.CLEANING:
        assert grid[("2025_26", "uv", c, "weighted")]["coef"] < -0.1, c


# --- P19: retail CPI DiD (CPI through 2026-09, exposure through 2026-08) ------------

from tpt.models import retail_did as rd  # noqa: E402

PINNED_RETAIL = {
    ("2025_26", "main"): (0.294, 0.10), ("2025_26", "main_eff"): (0.651, 0.15),
    ("2025_26", "pre_ruling"): (0.237, 0.10), ("2025_26", "diff12"): (0.068, 0.10),
    ("2025_26", "binary"): (0.026, 0.01), ("2025_26", "no_trend"): (-0.760, 0.10),
    ("2018_19", "main"): (0.962, 0.30),
}  # fmt: skip


@pytest.fixture(scope="module")
def retail() -> dict:
    if not rd.OUT.exists():
        pytest.skip("run make retail-did")
    df = pl.read_csv(rd.OUT)
    return {(r["period"], r["spec"]): r for r in df.iter_rows(named=True)}


@pytest.mark.parametrize(("key", "pin"), PINNED_RETAIL.items(), ids=lambda v: str(v))
def test_pinned_retail(retail, key, pin):
    assert retail[key]["coef"] == pytest.approx(pin[0], abs=pin[1])


def test_retail_pass_through_partial_and_below_border(retail):
    """2025-26: retail prices rose by a fraction of the duty cost (theta 0.2-0.7 against each
    item's pre-trend), about 0.6 of the border duty-inclusive response on either duty measure."""
    for spec in ("main", "main_eff", "pre_ruling", "trend_long"):
        assert 0.1 < retail[("2025_26", spec)]["coef"] < 0.8, spec
    for spec in ("main", "main_eff"):
        assert 0.4 < retail[("2025_26", spec)]["retail_vs_border"] < 0.8, spec


def test_retail_without_item_trends_is_biased_by_pre_trends(retail):
    """High-exposure goods were falling relative to low-exposure ones before both episodes;
    without item trends the estimate is negative (DATA.md P19). Fails if that changes."""
    for period in ("2025_26", "2018_19"):
        assert retail[(period, "no_trend")]["coef"] < 0


def test_retail_event_study_flat_before_2025(retail):
    ev = pl.read_csv(rd.EVENT_OUT).filter(
        pl.col("period") == "2025_26", pl.col("trend") == "pre", pl.col("design") == "binary"
    )
    pre = ev.filter(pl.col("k").is_between(-12, -1))["coef"]
    post = ev.filter(pl.col("k").is_between(9, 18))["coef"]
    assert pre.abs().max() < 0.015
    assert post.mean() > 0.02

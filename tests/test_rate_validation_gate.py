"""P11 gate: statutory (P10 panel) vs implied additional duties, explained line by line.

Reads reports/qa/rate_validation_bridge.csv (make validate-rates); skipped if not built."""

import polars as pl
import pytest

from tpt.build import validate_rates as vr

BRIDGE = vr.QA / "rate_validation_bridge.csv"
# Residual gap not assigned to an explained line, in percentage points of import value. Set in P11
# from the observed maximum (0.56 pp, 2025-07 to 2026-08: Section 232 product exclusions, TIB/FTZ
# entries, undated Annex II changes); a refresh that exceeds it needs a new diagnosis.
RESIDUAL_PP = 0.6

pytestmark = pytest.mark.skipif(not BRIDGE.exists(), reason="run make validate-rates")


@pytest.fixture(scope="module")
def bridge() -> pl.DataFrame:
    return pl.read_csv(BRIDGE, try_parse_dates=True)


def test_lines_add_up_to_the_gap(bridge):
    lines = pl.sum_horizontal([f"gap_{c}" for c in vr.CATEGORIES])
    diff = bridge.select((lines - pl.col("gap")).abs().max()).item()
    assert diff < 1e-4  # CSV written to 5 decimals


def test_mfn_term_matches_duties_before_2018(bridge):
    pre = bridge.filter(pl.col("month").dt.year() == 2017)
    assert pre["implied"].abs().max() < 0.0005  # implied additional duty < 0.05 pp


def test_residual_within_gate(bridge):
    worst = bridge.select(pl.col("gap_other").abs().max()).item()
    assert worst * 100 <= RESIDUAL_PP, f"unexplained residual {worst * 100:.2f} pp"


def test_pre_2025_gap_is_section_301_exclusions(bridge):
    pre = bridge.filter(pl.col("month").dt.year().is_between(2018, 2024))
    assert pre["gap"].max() < 0.01
    assert pre["gap_other"].abs().max() < 0.001

"""Invariants of the built rate panel (P10); skipped until `make rates` has run."""

from datetime import date

import polars as pl
import pytest

from tpt.build import tariff_rates as tr

pytestmark = pytest.mark.skipif(not tr.OUT.exists(), reason="run make rates first")


@pytest.fixture(scope="module")
def panel() -> pl.LazyFrame:
    return pl.scan_parquet(tr.OUT)


def test_unique_keys(panel):
    n = panel.select(pl.len()).collect().item()
    u = panel.select(pl.struct("hs10", "cty_code", "month").n_unique()).collect().item()
    assert n == u


def test_rates_in_range_and_total_is_sum(panel):
    cols = [*tr.RATE_COLS, "rate_total", "rate_metal_content", "rate_unidentified"]
    bad = panel.filter(pl.any_horizontal([(pl.col(c) < 0) | (pl.col(c) > 5) for c in cols]))
    assert bad.select(pl.len()).collect().item() == 0
    diff = panel.select((pl.col("rate_total") - pl.sum_horizontal(tr.RATE_COLS)).abs().max())
    assert diff.collect().item() < 1e-9
    over = panel.filter(pl.col("rate_metal_content") > pl.col("rate_s232") + 1e-9)
    assert over.select(pl.len()).collect().item() == 0


def test_ieepa_zero_after_collection_stopped(panel):
    after = panel.filter(pl.col("month") >= date(2026, 3, 1)).select(
        pl.max_horizontal("rate_ieepa_fentanyl", "rate_ieepa_reciprocal", "rate_ieepa_other").max()
    )
    assert after.collect().item() == 0


def test_no_additional_duties_before_2018(panel):
    early = panel.filter(pl.col("month") < date(2018, 2, 1)).select(pl.col("rate_total").max())
    assert early.collect().item() == 0

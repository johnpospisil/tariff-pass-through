"""Invariants of the built import panel (P12); skipped if data/processed/import_panel.parquet
is missing (make import-panel)."""

import polars as pl
import pytest

from tpt.build import import_panel as ip

pytestmark = pytest.mark.skipif(not ip.OUT.exists(), reason="run make import-panel")
REASONS = {"special_provision", "duty_outlier", "no_base", "mixed_units", "no_quantity",
           "unit_change", "trimmed"}  # fmt: skip


@pytest.fixture(scope="module")
def panel() -> pl.LazyFrame:
    return pl.scan_parquet(ip.OUT)


def test_no_duplicate_keys(panel):
    n = panel.select(pl.len(), pl.struct("prod_id", "cty_code", "month").n_unique().alias("k"))
    rows, keys = n.collect().row(0)
    assert rows == keys


def test_rates_in_range(panel):
    r = panel.select(
        pl.col("eff_rate").min().alias("lo"), pl.col("eff_rate").max().alias("hi"),
        pl.col("stat_rate").min().alias("slo"), pl.col("stat_rate").max().alias("shi"),
    ).collect().row(0, named=True)  # fmt: skip
    assert 0 <= r["lo"] and r["hi"] <= 5
    assert 0 <= r["slo"] and r["shi"] <= 5


def test_sample_rows_have_changes_and_known_reasons(panel):
    reasons = set(panel.select(pl.col("drop_reason").unique()).collect()["drop_reason"])
    assert reasons - {None} <= REASONS
    sample = panel.filter(pl.col("drop_reason").is_null())
    nulls = sample.select(pl.col(*ip.CHANGE_COLS, "dln_1p_tau_stat").null_count()).collect()
    assert nulls.sum_horizontal().item() == 0


def test_winsorised_within_raw_range(panel):
    lo, hi = ip.Cleaning().winsor
    s = panel.filter(pl.col("drop_reason").is_null()).select(
        (pl.col("dln_uv").max() - pl.col("dln_uv_raw").quantile(hi)).alias("hi"),
        (pl.col("dln_uv").min() - pl.col("dln_uv_raw").quantile(lo)).alias("lo"),
    ).collect().row(0)  # fmt: skip
    assert abs(s[0]) < 1e-9 and abs(s[1]) < 1e-9


def test_value_reconciles_with_census_detail(panel):
    # all imports for consumption of individual countries are in the panel (flagged or not)
    import duckdb

    total = duckdb.sql(f"""
        select sum(con_val_mo)::double from read_parquet('{ip.IMPORTS}/*/data.parquet',
          hive_partitioning = 1) i
        join (select cty_code from read_csv('{ip.COUNTRIES}', all_varchar = true)
              where is_individual = 'true') using (cty_code)
        where summary_lvl = 'DET' and con_val_mo > 0""").fetchall()[0][0]  # fmt: skip
    ours = panel.select(pl.col("con_val").sum()).collect().item()
    assert ours == pytest.approx(total, rel=1e-9)

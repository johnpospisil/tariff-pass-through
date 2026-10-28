"""BLS PPI commodity indexes, a light goods selection (P05).

Catalog: download.bls.gov wp.series, NSA, active:
  - commodity groups 00-15 (goods) at the group level and one or two digits below it;
  - the final-demand tree (FD4...), which includes the final demand goods aggregates.
Detailed 4-8 digit commodities and the service groups (30+) are left out.

Run: make ingest-bls   (or uv run python -m tpt.ingest.bls_ppi)
"""

import polars as pl

from tpt.ingest import _bls

GOODS_GROUPS = [f"{g:02d}" for g in range(16)]
MAX_DEPTH = 2


def catalog(series: pl.DataFrame, groups: pl.DataFrame, start_year: int) -> pl.DataFrame:
    depth = (
        pl.when(pl.col("item_code").is_in(["-", "000000"]))
        .then(0)
        .otherwise(pl.col("item_code").str.len_chars())
    )
    goods = pl.col("group_code").is_in(GOODS_GROUPS) & (depth <= MAX_DEPTH)
    final_demand = pl.col("group_code").str.starts_with("FD4")
    return (
        series.filter(
            pl.col("seasonal") == "U", _bls.active_since(series, start_year), goods | final_demand
        )
        .join(groups, on="group_code", how="left")
        .select(
            "series_id",
            "group_code",
            "group_name",
            "item_code",
            "seasonal",
            "base_date",
            "series_title",
            "begin_year",
            "begin_period",
            "end_year",
            "end_period",
        )
        .sort("series_id")
    )


def run(start_year: int = _bls.START_YEAR) -> pl.DataFrame:
    cat = catalog(_bls.read_flat("wp/wp.series"), _bls.read_flat("wp/wp.group"), start_year)
    return _bls.run_survey("ppi", cat, start_year)


if __name__ == "__main__":
    run()

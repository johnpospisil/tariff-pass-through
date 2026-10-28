"""BLS CPI-U item indexes, U.S. city average, monthly, NSA and SA (P05).

Catalog: download.bls.gov cu.series (area 0000, periodicity R) joined to cu.item for the item
name and display level (0 = All items ... 8 = most detailed strata). `seasonal` is U (NSA) or S
(SA); many detailed items have NSA only.

Run: make ingest-bls   (or uv run python -m tpt.ingest.bls_cpi)
"""

import polars as pl

from tpt.ingest import _bls


def catalog(series: pl.DataFrame, items: pl.DataFrame, start_year: int) -> pl.DataFrame:
    return (
        series.filter(
            pl.col("area_code") == "0000",
            pl.col("periodicity_code") == "R",
            _bls.active_since(series, start_year),
        )
        .join(
            items.select("item_code", "item_name", "display_level", "selectable"),
            on="item_code",
            how="left",
        )
        .with_columns(pl.col("display_level").cast(pl.Int32))
        .select(
            "series_id",
            "item_code",
            "item_name",
            "display_level",
            "selectable",
            "seasonal",
            "base_period",
            "series_title",
            "begin_year",
            "begin_period",
            "end_year",
            "end_period",
        )
        .sort("series_id")
    )


def run(start_year: int = _bls.START_YEAR) -> pl.DataFrame:
    cat = catalog(_bls.read_flat("cu/cu.series"), _bls.read_flat("cu/cu.item"), start_year)
    return _bls.run_survey("cpi", cat, start_year)


if __name__ == "__main__":
    run()

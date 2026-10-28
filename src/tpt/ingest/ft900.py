"""FT-900 monthly goods trade by country (Census basis, not seasonally adjusted).

Source: https://www.census.gov/foreign-trade/balance/country.xlsx, the country tables behind the
FT-900 release, $ millions, revised with each release. Code 0015 is "World, Not Seasonally
Adjusted", the FT-900 total for imports of goods. Unreleased months are filled with 0.

This is the independent check for the HS10 pull (P04 gate 1): it is published as a separate
product, not derived from our API queries.
"""

from datetime import date

import polars as pl

from tpt import config
from tpt.ingest._http import CachedClient

URL = "https://www.census.gov/foreign-trade/balance/country.xlsx"
WORLD_NSA = "0015"
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

INTERIM_PATH = config.INTERIM_DIR / "ft900_country.parquet"
TOTALS_CSV = config.REFERENCE_DIR / "ft900_totals.csv"


def tidy_country_table(wide: pl.DataFrame) -> pl.DataFrame:
    """Wide year x country table -> long country x month, imports and exports in dollars."""
    frames = []
    for i, m in enumerate(MONTHS, start=1):
        frames.append(
            wide.select(
                pl.col("CTY_CODE").cast(pl.String).alias("cty_code"),
                pl.col("CTYNAME").alias("cty_name"),
                pl.date(pl.col("year").cast(pl.Int32), i, 1).alias("month"),
                (pl.col(f"I{m}").cast(pl.Float64) * 1e6).alias("imports_usd"),
                (pl.col(f"E{m}").cast(pl.Float64) * 1e6).alias("exports_usd"),
            )
        )
    long = pl.concat(frames)
    world = long.filter((pl.col("cty_code") == WORLD_NSA) & (pl.col("imports_usd") > 0))
    latest = world["month"].max() if world.height else None
    if latest is not None:
        long = long.filter(pl.col("month") <= latest)
    return long.sort("cty_code", "month")


def fetch(client: CachedClient | None = None) -> pl.DataFrame:
    """Download the current file (always fresh: same URL, revised every release)."""
    client = client or CachedClient("download")
    resp = client.get(URL, refresh=True)
    wide = pl.read_excel(resp.content, sheet_id=1)
    long = tidy_country_table(wide)
    client.record_rows(resp, long.height)
    return long


def run() -> pl.DataFrame:
    long = fetch()
    INTERIM_PATH.parent.mkdir(parents=True, exist_ok=True)
    long.write_parquet(INTERIM_PATH)
    totals = (
        long.filter(pl.col("cty_code") == WORLD_NSA)
        .select("month", pl.col("imports_usd").alias("ft900_imports_usd"))
        .with_columns(source_url=pl.lit(URL), retrieved_on=pl.lit(date.today()))
    )
    totals.write_csv(TOTALS_CSV)
    print(f"FT-900: {long['cty_code'].n_unique()} codes, "
          f"{totals['month'].min()} to {totals['month'].max()} -> {TOTALS_CSV.name}")  # fmt: skip
    return long


if __name__ == "__main__":
    run()

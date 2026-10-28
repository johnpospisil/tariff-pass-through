"""Low-value import estimates around the end of de minimis (P14, chart 6).

Census reports import transactions valued under $2,000 that cannot be rolled up into commodity
detail as estimates by country under HTS 9999.95.0000, built from electronically filed (ACE),
paper, courier and foreign-trade-zone components (Census, Guide to Foreign Trade Statistics,
section 2, https://www.census.gov/foreign-trade/guide/sec2.html). De minimis (Section 321)
shipments, under $800, were not recorded in Census trade data (Fajgelbaum and Khandelwal, "The
Value of de Minimis Imports", 2025: $54.5bn over 1 billion shipments in 2023). De minimis ended
for China and Hong Kong on 2025-05-02 (EO 14256) and for all countries on 2025-08-29 (EO 14324),
so part of any rise in the 9999.95 line is shipments being recorded for the first time, not more
imports.

Run: make low-value   (writes data/published/low_value_imports.csv)
"""

import duckdb
import polars as pl

from tpt import config
from tpt.build.tariff_rates import IMPORTS

OUT = config.PUBLISHED_DIR / "low_value_imports.csv"
LOW_VALUE = "9999950000"
CHINA_HK = ("5700", "5820")


def series(df: pl.DataFrame) -> pl.DataFrame:
    """df: hs10, cty_code, month, con_val (individual countries, all products)."""
    lv = pl.col("hs10") == LOW_VALUE
    cn = pl.col("cty_code").is_in(list(CHINA_HK))
    return (
        df.group_by("month")
        .agg(
            china_hk_bn=pl.col("con_val").filter(lv & cn).sum() / 1e9,
            rest_bn=pl.col("con_val").filter(lv & ~cn).sum() / 1e9,
            total_bn=pl.col("con_val").filter(lv).sum() / 1e9,
            imports_bn=pl.col("con_val").sum() / 1e9,
        )
        .with_columns(share_of_imports=pl.col("total_bn") / pl.col("imports_bn"))
        .sort("month")
    )


def run() -> pl.DataFrame:
    df = duckdb.sql(f"""
        select hs10, cty_code, month, sum(con_val_mo)::double con_val
        from read_parquet('{IMPORTS}/*/data.parquet', hive_partitioning = 1)
        where summary_lvl = 'DET' and cty_code <> '-' and month >= '2022-01-01'
        group by all""").pl()  # fmt: skip
    out = series(df)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.write_csv(OUT, float_precision=4)
    print(out.tail(20))
    return out


if __name__ == "__main__":
    run()

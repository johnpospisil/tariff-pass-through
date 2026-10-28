"""BLS import price indexes (MXP), measured before duties (P05).

Catalog: download.bls.gov ei.series, import families only:
  CO  by locality of origin (China, Canada, Mexico, EU, Japan, ASEAN, ...; NAICS detail)
  IR  by BEA end use
  IP  by Harmonized System
  IZ  by NAICS
All are not seasonally adjusted. Base periods differ by series (see the catalog).

Run: make ingest-bls   (or uv run python -m tpt.ingest.bls_mxp)
"""

import polars as pl

from tpt.ingest import _bls

FAMILIES = ("CO", "IR", "IP", "IZ")


def catalog(series: pl.DataFrame, index: pl.DataFrame, start_year: int) -> pl.DataFrame:
    return (
        series.filter(pl.col("index_code").is_in(FAMILIES), _bls.active_since(series, start_year))
        .join(index, on="index_code", how="left")
        .select(
            "series_id",
            "index_code",
            "index_name",
            "series_name",
            "series_title",
            "base_period",
            "seasonal",
            "begin_year",
            "begin_period",
            "end_year",
            "end_period",
        )
        .sort("series_id")
    )


def run(start_year: int = _bls.START_YEAR) -> pl.DataFrame:
    cat = catalog(_bls.read_flat("ei/ei.series"), _bls.read_flat("ei/ei.index"), start_year)
    return _bls.run_survey("mxp", cat, start_year)


if __name__ == "__main__":
    run()

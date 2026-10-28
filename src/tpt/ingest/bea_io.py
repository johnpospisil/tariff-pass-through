"""BEA input-output tables, 2017 detail (402 industries), and the PCE bridge (P06).

Sources:
- apps.bea.gov/industry/iTables Static Files/AllTablesSUP.zip
    Supply_2017_DET.xlsx            commodity x (industries, imports MCIF, duties MDTY, totals)
    Use_SUT_Framework_2017_DET.xlsx commodity x (industries, final uses)
    "NAICS Codes" sheet             BEA detail code -> related 2017 NAICS codes
- apps.bea.gov/industry/xls/underlying-estimates/PCEBridge_2017_DET.xlsx
    PCE category (NIPA table 2.4.5U line) x commodity, producers' to purchasers' value
- census.gov/naics/concordances/2022_to_2017_NAICS.xlsx and 2012_to_2017_NAICS.xlsx
    BEA's 2017 tables cite 2017 NAICS; Census HS10 lists carry 2022 NAICS from 2022 and some
    2012 NAICS codes before that

Detail tables exist only for the 2017 benchmark year. Values in $ millions.
Outputs in data/interim/: bea_supply_2017, bea_use_2017, bea_naics, pce_bridge_2017 (.parquet).
"""

import io
import re
import zipfile

import polars as pl

from tpt import config
from tpt.ingest._http import CachedClient

SUP_URL = "https://apps.bea.gov/industry/iTables%20Static%20Files/AllTablesSUP.zip"
BRIDGE_URL = "https://apps.bea.gov/industry/xls/underlying-estimates/PCEBridge_2017_DET.xlsx"
NAICS_2022_2017_URL = "https://www.census.gov/naics/concordances/2022_to_2017_NAICS.xlsx"
NAICS_2012_2017_URL = "https://www.census.gov/naics/concordances/2012_to_2017_NAICS.xlsx"
SUPPLY_FILE = "Supply_2017_DET.xlsx"
USE_FILE = "Use_SUT_Framework_2017_DET.xlsx"
YEAR_SHEET = "2017"

OUT = {
    "supply": config.INTERIM_DIR / "bea_supply_2017.parquet",
    "use": config.INTERIM_DIR / "bea_use_2017.parquet",
    "naics": config.INTERIM_DIR / "bea_naics.parquet",
    "bridge": config.INTERIM_DIR / "pce_bridge_2017.parquet",
    "naics_2022_2017": config.INTERIM_DIR / "naics_2022_2017.parquet",
    "naics_2012_2017": config.INTERIM_DIR / "naics_2012_2017.parquet",
}


def expand_naics_spec(spec: str | None) -> list[str]:
    """'11113-6, 11119' -> ['11113', ..., '11116', '11119']; '23*' -> ['23']."""
    if not spec:
        return []
    out = []
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        if part.endswith("*"):
            out.append(part[:-1])
        elif "-" in part:
            start, end = part.split("-")
            stem = start[: len(start) - len(end)]
            out += [f"{stem}{d}" for d in range(int(start[len(stem) :]), int(end) + 1)]
        else:
            out.append(part)
    return out


def parse_sut_sheet(content: bytes) -> pl.DataFrame:
    """A BEA supply or use sheet -> long (commodity, column, value) with names."""
    raw = pl.read_excel(content, sheet_name=YEAR_SHEET, infer_schema_length=0,
                        read_options={"header_row": None})  # fmt: skip
    names, codes = raw.row(3), raw.row(4)
    body = raw.slice(5).filter(
        pl.col(raw.columns[0]).is_not_null() & pl.col(raw.columns[1]).is_not_null()
    )
    long = (
        body.rename({raw.columns[0]: "commodity_code", raw.columns[1]: "commodity_desc"})
        .unpivot(index=["commodity_code", "commodity_desc"], variable_name="col")
        .with_columns(pl.col("value").str.strip_chars().cast(pl.Float64, strict=False))
        .filter(pl.col("value").is_not_null() & (pl.col("value") != 0))
    )
    lookup = pl.DataFrame(
        {
            "col": raw.columns[2:],
            "column_code": [str(c).strip() for c in codes[2:]],
            "column_name": [str(n).strip() for n in names[2:]],
        }  # fmt: skip
    )
    return (
        long.join(lookup, on="col")
        .drop("col")
        .with_columns(pl.col("commodity_code").str.strip_chars())
    )


def parse_naics_codes(content: bytes) -> pl.DataFrame:
    raw = pl.read_excel(content, sheet_name="NAICS Codes", infer_schema_length=0,
                        read_options={"header_row": None})  # fmt: skip
    detail, title, spec = raw.columns[3], raw.columns[4], raw.columns[6]
    rows = raw.filter(pl.col(detail).str.contains(r"^[0-9A-Z]{6}$", strict=False)).select(
        pl.col(detail).alias("bea_code"), pl.col(title).alias("bea_title"),
        pl.col(spec).alias("naics_spec"),
    )  # fmt: skip
    return rows.with_columns(
        pl.col("naics_spec").map_elements(expand_naics_spec, return_dtype=pl.List(pl.String))
        .alias("naics_prefix")
    ).explode("naics_prefix")  # fmt: skip


def parse_bridge(content: bytes) -> pl.DataFrame:
    raw = pl.read_excel(content, sheet_name=YEAR_SHEET, infer_schema_length=0,
                        read_options={"header_row": None})  # fmt: skip
    cols = ["nipa_line", "pce_category", "commodity_code", "commodity_desc", "producers_value",
            "transport_costs", "wholesale", "retail", "purchasers_value", "year"]  # fmt: skip
    body = raw.slice(5).rename(dict(zip(raw.columns, cols, strict=True)))
    body = body.filter(pl.col("nipa_line").str.contains(r"^\d+$", strict=False))
    values = cols[4:9]
    return body.with_columns(
        pl.col("nipa_line").cast(pl.Int32),
        pl.col("pce_category").str.strip_chars(),
        pl.col(values).str.strip_chars().cast(pl.Float64, strict=False),
    ).drop("year")


def parse_naics_concordance(content: bytes, from_name: str, to_name: str) -> pl.DataFrame:
    """Census NAICS concordance sheet: first column old/new code, third column the other."""
    raw = pl.read_excel(
        content, sheet_id=1, infer_schema_length=0, read_options={"header_row": None}
    )
    body = raw.slice(3).select(
        pl.col(raw.columns[0]).str.strip_chars().alias(from_name),
        pl.col(raw.columns[2]).str.strip_chars().alias(to_name),
    )
    return body.filter(
        pl.col(from_name).str.contains(r"^\d{6}$", strict=False)
        & pl.col(to_name).str.contains(r"^\d{6}$", strict=False)
    ).unique(maintain_order=True)


def _normalise_cols(df: pl.DataFrame) -> pl.DataFrame:
    return df.rename({c: re.sub(r"\s+", "_", c.strip().lower()) for c in df.columns})


def run() -> dict[str, pl.DataFrame]:
    client = CachedClient("download")
    sup = client.get(SUP_URL)
    zf = zipfile.ZipFile(io.BytesIO(sup.content))
    out = {
        "supply": parse_sut_sheet(zf.read(SUPPLY_FILE)),
        "use": parse_sut_sheet(zf.read(USE_FILE)),
        "naics": parse_naics_codes(zf.read(SUPPLY_FILE)),
        "bridge": parse_bridge(client.get(BRIDGE_URL).content),
        "naics_2022_2017": parse_naics_concordance(
            client.get(NAICS_2022_2017_URL).content, "naics_2022", "naics_2017"
        ),
        "naics_2012_2017": parse_naics_concordance(
            client.get(NAICS_2012_2017_URL).content, "naics_2012", "naics_2017"
        ),
    }
    for key, df in out.items():
        df = _normalise_cols(df)
        df.write_parquet(OUT[key])
        print(f"BEA {key}: {df.height:,} rows -> {OUT[key].name}")
    return out


if __name__ == "__main__":
    run()

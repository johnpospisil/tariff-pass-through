"""MFN (HTSUS column 1 general) ad valorem rates by HS10 (P10).

Needed for the "all-in" floors (EU, Japan, Korea, Switzerland deals; forced-labor caps), where
the additional duty is max(0, floor - MFN). Source: the current HTSUS export from hts.usitc.gov
(general rate at HTS8). Specific and compound rates get an ad valorem equivalent: 2024 calculated
duties / imports for consumption from countries paying MFN with no trade agreement and no
special 2024 duties on such goods (EU27, Switzerland, Norway, UK), at HS10, else HS8. HS10 codes
not in the current HTSUS take the mean rate of their P06 family, else of their HS6; else 0.

Output: data/processed/mfn_rates.parquet (hs10, mfn_rate, mfn_source)
"""

import json
import re

import duckdb
import polars as pl

from tpt import config
from tpt.build.hs_lists import SOURCE
from tpt.ingest._http import CachedClient

EXPORT = "https://hts.usitc.gov/reststop/exportList"
OUT = config.PROCESSED_DIR / "mfn_rates.parquet"
AVE_COUNTRIES = ("4120", "4419", "4039")  # UK, Switzerland, Norway (+ EU27 group)


def parse_general(text: str) -> float | None:
    t = re.sub(r"\d/$", "", (text or "").strip())  # footnote markers like "1/"
    if t.startswith("Free"):
        return 0.0
    m = re.fullmatch(r"(\d+(?:\.\d+)?)%", t)
    return float(m.group(1)) / 100 if m else None


def hts8_rates(rows: list[dict]) -> pl.DataFrame:
    """General rate per HTS8; the export puts it on the HTS8 line or, when an HTS8 has a single
    statistical line, on the 10-digit line."""
    out = {}
    for r in rows:
        no = r.get("htsno") or ""
        if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}(\.\d{2})?", no) and (r.get("general") or "").strip():
            out.setdefault(no.replace(".", "")[:8], parse_general(r["general"]))
    return pl.DataFrame({"hs8": list(out), "general": list(out.values())},
                        schema={"hs8": pl.String, "general": pl.Float64})  # fmt: skip


def assign(codes: list[str], hts8: pl.DataFrame, ave: pl.DataFrame,
           families: pl.DataFrame) -> pl.DataFrame:  # fmt: skip
    df = pl.DataFrame({"hs10": codes}).with_columns(hs8=pl.col("hs10").str.slice(0, 8))
    hs8 = pl.col("hs10").str.slice(0, 8).alias("hs8")
    ave8 = ave.group_by(hs8).agg(pl.col("ave").mean().alias("ave8"))
    df = (
        df.join(hts8, on="hs8", how="left")
        .join(ave, on="hs10", how="left")
        .join(ave8, on="hs8", how="left")
        .with_columns(
            pl.coalesce("general", "ave", "ave8").alias("r"),
            pl.when(pl.col("general").is_not_null()).then(pl.lit("hts_general"))
            .when(pl.col("ave").is_not_null() | pl.col("ave8").is_not_null())
            .then(pl.lit("ave_2024"))
            .otherwise(None).alias("mfn_source"),
        )
    )  # fmt: skip
    df = df.join(families, on="hs10", how="left")
    fam = df.group_by("family").agg(pl.col("r").mean().alias("rf"))
    hs6 = df.group_by(pl.col("hs10").str.slice(0, 6).alias("hs6")).agg(
        pl.col("r").mean().alias("r6")
    )
    df = df.join(fam, on="family", how="left").with_columns(hs6=pl.col("hs10").str.slice(0, 6))
    df = df.join(hs6, on="hs6", how="left")
    return df.select(
        "hs10",
        pl.coalesce("r", "rf", "r6", pl.lit(0.0)).alias("mfn_rate"),
        pl.when(pl.col("mfn_source").is_not_null()).then("mfn_source")
        .when(pl.col("rf").is_not_null()).then(pl.lit("family"))
        .when(pl.col("r6").is_not_null()).then(pl.lit("hs6"))
        .otherwise(pl.lit("none")).alias("mfn_source"),
    )  # fmt: skip


def run() -> pl.DataFrame:
    client = CachedClient(SOURCE)
    resp = client.get(EXPORT, {"from": "0100", "to": "9999", "format": "JSON", "styles": "false"})
    hts8 = hts8_rates(json.loads(resp.content))
    eu = pl.read_csv(config.REFERENCE_DIR / "country_groups.csv", infer_schema=False)
    ctys = list(AVE_COUNTRIES) + eu.filter(pl.col("group") == "EU27")["cty_code"].to_list()
    imports = config.INTERIM_DIR / "census_imports" / "year=2024" / "data.parquet"
    ave = duckdb.sql(f"""
        select hs10, sum(cal_dut_mo) / sum(con_val_mo) as ave
        from read_parquet('{imports}') where cty_code in ({",".join(f"'{c}'" for c in ctys)})
        group by hs10 having sum(con_val_mo) > 0
    """).pl()  # fmt: skip
    specific = set(hts8.filter(pl.col("general").is_null())["hs8"])
    ave = ave.filter(pl.col("hs10").str.slice(0, 8).is_in(list(specific)))
    codes = duckdb.sql(f"""select distinct hs10 from
        read_parquet('{config.INTERIM_DIR}/census_imports/*/data.parquet')""").pl()["hs10"]
    fam = pl.read_parquet(config.PROCESSED_DIR / "hs10_families.parquet")
    out = assign(codes.to_list(), hts8, ave, fam)
    out.write_parquet(OUT)
    print(f"{OUT.name}: {out.height:,} HS10; sources:",
          dict(out.group_by("mfn_source").len().iter_rows()))  # fmt: skip
    return out


if __name__ == "__main__":
    run()

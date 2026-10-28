"""Share of Canadian and Mexican imports entered under USMCA, by HS10 x month (P10).

Census rate provision codes (`RP`, record layout IM145): 10-19 free, 61 general rates, 62 column 2,
64 special (FTA) rates, 69/79 Chapter 99 rates (duty / no duty reported). Before 2025, USMCA
claims show as code 18 (free under a special program). From 2025-03-07, when USMCA-qualifying
goods became exempt from the IEEPA duties, most Canadian and Mexican imports show as code 19
(free, entered under the Chapter 99 USMCA exemption headings): 75-77% in 2025-06 against 37-48%
under code 18 in 2024-06. The USMCA-qualifying share is therefore (18 + 19) / total.

Caveat: some code-19 entries may use other Chapter 99 duty-free provisions, and USMCA vehicles
paying the Section 232 duty on non-US content are under code 69 and not counted (so the share is
a lower bound for vehicles). The share is the contemporaneous one, i.e. after importers responded
to the tariffs by claiming USMCA more often.

Output: data/processed/usmca_share.parquet (hs10, cty_code, month, con_val, usmca_share)
Run: make usmca-share        Watch: make ingest-status SOURCE=census_rp
"""

import json
from datetime import date

import polars as pl

from tpt import config
from tpt.ingest._http import CachedClient
from tpt.ingest.progress import ProgressFile, progress_path

URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
COUNTRIES = {"1220": "Canada", "2010": "Mexico"}
START = date(2025, 1, 1)
USMCA_CODES = ("18", "19")
OUT = config.PROCESSED_DIR / "usmca_share.parquet"


def parse(content: bytes) -> pl.DataFrame:
    header, *rows = json.loads(content)
    idx = {h: header.index(h) for h in ("I_COMMODITY", "RP", "CON_VAL_MO", "CTY_CODE", "time")}
    return pl.DataFrame(
        {"hs10": [r[idx["I_COMMODITY"]] for r in rows], "rp": [r[idx["RP"]] for r in rows],
         "con_val": [int(r[idx["CON_VAL_MO"]] or 0) for r in rows],
         "cty_code": [r[idx["CTY_CODE"]] for r in rows],
         "month": [date.fromisoformat(r[idx["time"]] + "-01") for r in rows]},
    )  # fmt: skip


def usmca_share(df: pl.DataFrame) -> pl.DataFrame:
    total = df.filter(pl.col("rp") == "-").select("hs10", "cty_code", "month", "con_val")
    usmca = (
        df.filter(pl.col("rp").is_in(USMCA_CODES))
        .group_by("hs10", "cty_code", "month")
        .agg(pl.col("con_val").sum().alias("usmca_val"))
    )
    return (
        total.filter(pl.col("con_val") > 0)
        .join(usmca, on=["hs10", "cty_code", "month"], how="left")
        .with_columns(usmca_share=(pl.col("usmca_val").fill_null(0) / pl.col("con_val")).clip(0, 1))
        .drop("usmca_val")
    )


def months(last: date) -> list[str]:
    out, y, m = [], START.year, START.month
    while (y, m) <= (last.year, last.month):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def run() -> pl.DataFrame:
    last = pl.read_parquet(config.INTERIM_DIR / "census_totals.parquet")["month"].max()
    client = CachedClient("census")
    jobs = [(cty, m) for cty in COUNTRIES for m in months(last)]
    progress = ProgressFile(progress_path("census_rp"), label="Census rate provisions (CA, MX)")
    progress.start(len(jobs))
    frames = []
    for cty, m in jobs:
        resp = client.get(URL, {"get": "I_COMMODITY,RP,CON_VAL_MO", "CTY_CODE": cty,
                                "COMM_LVL": "HS10", "time": m})  # fmt: skip
        frames.append(usmca_share(parse(resp.content)))
        progress.advance(rows=frames[-1].height, cached=resp.from_cache)
        print(f"  {COUNTRIES[cty]} {m}: {frames[-1].height:,} HS10 lines", flush=True)
    progress.finish()
    out = pl.concat(frames)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(OUT)
    agg = (
        out.group_by("cty_code", "month")
        .agg(
            ((pl.col("usmca_share") * pl.col("con_val")).sum() / pl.col("con_val").sum()).alias(
                "share"
            )
        )
        .sort("cty_code", "month")
    )
    print(agg)
    return out


if __name__ == "__main__":
    run()

"""Product explorer bundle (P23) -> data/published/explorer/.

Layout (JSON, read by report/explore.qmd):
  meta.json         months (YYYY-MM), data month, country names, field notes
  index.json        every HS10 [code, description, imports in the latest 12 months ($m)]
                    and the search aliases (data/reference/explorer_aliases.csv)
  <ch>/<hs4>.json   one file per HS4 heading inside its chapter folder: {hs10: product}

A product holds its five largest sources over the whole window plus "other", each with
monthly arrays from its first to its last traded month (m0 = index into meta months):
v = customs value ($ thousands, imports for consumption, 0 = none), uv = pre-duty unit value
(value / quantity, only rows in the product's latest quantity unit; 0 = not available), and
as change points [[index from m0, value]] carried through months without imports:
e = calculated duties / value (all duties, MFN included) and r = statutory additional duty
rate (P10). Values keep three significant digits. "All countries" is summed
in the browser. Chapters 98/99 (special provisions, low-value estimates) are left out, as in
the panels. One file per heading rather than per chapter: chapter 84 alone would be ~20 MB.
"""

import csv
import json
import math
import re
import sys
import time
from collections.abc import Sequence
from datetime import date

import duckdb
import polars as pl

from tpt import config

OUT_DIR = config.PUBLISHED_DIR / "explorer"
ALIASES = config.REFERENCE_DIR / "explorer_aliases.csv"
TOP_K = 5


def sig(x: float | None, digits: int = 4) -> float | None:
    """Round to significant digits (keeps the bundle small)."""
    if x is None or not math.isfinite(x):
        return None
    if x == 0:
        return 0.0
    return round(x, digits - 1 - math.floor(math.log10(abs(x))))


def rle(values: Sequence[float | None]) -> list[list]:
    """Change points [[index, value], ...] of a step series."""
    out: list[list] = []
    for i, v in enumerate(values):
        if not out or out[-1][1] != v:
            out.append([i, v])
    return out


def num(x: float | None) -> float | int | None:
    """Whole numbers as ints so the JSON drops the trailing '.0'."""
    return int(x) if x is not None and x.is_integer() else x


def ffill(values: list) -> list:
    """Carry the last known value through months without imports (not shown, but keeps the
    change-point encoding short)."""
    out, last = [], None
    for v in values:
        last = v if v is not None else last
        out.append(last)
    return out


def words(text: str) -> list[str]:
    """Lower-case search words with plurals stemmed (mirrors the explorer's JavaScript)."""
    out = []
    for w in re.split(r"[^a-z0-9]+", text.lower().replace("'", "")):
        if len(w) < 2:
            continue
        if w.endswith("sses"):
            w = w[:-2]
        elif w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            w = w[:-1]
        out.append(w)
    return out


def aliases() -> dict[str, str]:
    with ALIASES.open() as f:
        return {r["term"]: r["expansion"] for r in csv.DictReader(f)}


def file_for(hs10: str) -> str:
    return f"{hs10[:2]}/{hs10[:4]}.json"


def product(rows: pl.DataFrame, months: list[date], k: int = TOP_K) -> dict:
    """Encode one HS10. rows: cty_code, month, v (value $), d (duties $), q (quantity), unit,
    r (statutory additional rate), optionally mfn."""
    unit = rows.sort(["month", "v"]).get_column("unit")[-1]
    top = (rows.group_by("cty_code").agg(pl.col("v").sum())
           .sort(["v", "cty_code"], descending=[True, False]).head(k)
           .get_column("cty_code").to_list())  # fmt: skip
    same = (pl.col("unit") == unit) & (pl.col("q") > 0)
    has_r = pl.col("r").is_not_null()
    g = (
        rows.with_columns(
            series=pl.when(pl.col("cty_code").is_in(top))
            .then(pl.col("cty_code"))
            .otherwise(pl.lit("other"))
        )  # fmt: skip
        .group_by(["series", "month"])
        .agg(
            v=pl.col("v").sum(),
            d=pl.col("d").sum(),
            vq=pl.col("v").filter(same).sum(),
            q=pl.col("q").filter(same).sum(),
            rv=(pl.col("r") * pl.col("v")).filter(has_r).sum(),
            wv=pl.col("v").filter(has_r).sum(),
        )  # fmt: skip
    )
    idx = {m: i for i, m in enumerate(months)}
    series = []
    for code in [*top, "other"]:
        sub = g.filter(pl.col("series") == code)
        if sub.is_empty():
            continue
        at = [idx[m] for m in sub.get_column("month")]
        m0, n = min(at), max(at) - min(at) + 1
        v, uv, e, r = [0] * n, [0] * n, [None] * n, [None] * n
        for i, row in zip(at, sub.iter_rows(named=True), strict=True):
            i -= m0
            v[i] = num(sig(row["v"] / 1e3, 3))
            if row["q"] > 0:
                uv[i] = num(sig(row["vq"] / row["q"], 3))
            if row["v"] > 0:
                e[i] = round(row["d"] / row["v"], 2)
            if row["wv"] > 0:
                r[i] = round(row["rv"] / row["wv"], 3)
        series.append({"c": code, "m0": m0, "v": v, "uv": uv, "e": rle(ffill(e)),
                       "r": rle(ffill(r))})  # fmt: skip
    out = {"u": unit, "s": series}
    if "mfn" in rows.columns:
        mfn = rows.filter(pl.col("mfn").is_not_null()).sort("month").get_column("mfn")
        out["mfn"] = round(mfn[-1], 4) if len(mfn) else None
    return out


def _panel_sql(chapter: str) -> str:
    return f"""
        select prod_id as hs10, cty_code, month, con_val as v, coalesce(cal_dut, 0) as d,
               qty as q, unit, stat_rate as r, mfn_rate as mfn
        from '{config.PROCESSED_DIR / "import_panel.parquet"}'
        where level = 'hs10' and substr(prod_id, 1, 2) = '{chapter}'"""


def descriptions() -> pl.DataFrame:
    """Latest-year long description of each HS10."""
    return duckdb.sql(f"""
        select hs10, arg_max(coalesce(desc_long, desc_short), year) as desc
        from '{config.PROCESSED_DIR / "hs10_attributes.parquet"}' group by 1""").pl()


def country_names(codes: set[str]) -> dict[str, str]:
    df = pl.read_csv(config.REFERENCE_DIR / "census_countries.csv", schema_overrides={
        "cty_code": pl.String})  # fmt: skip
    names = dict(zip(df.get_column("cty_code"), df.get_column("cty_name"), strict=True))
    return {c: names.get(c, c).title() for c in sorted(codes)}


def run() -> dict:
    t0 = time.time()
    panel = config.PROCESSED_DIR / "import_panel.parquet"
    span = duckdb.sql(f"select min(month), max(month) from '{panel}' where level = 'hs10'")
    first, last = span.fetchall()[0]
    months = pl.date_range(first, last, "1mo", eager=True).to_list()
    chapters = [r[0] for r in duckdb.sql(f"""
        select distinct substr(prod_id, 1, 2) from '{panel}'
        where level = 'hs10' and substr(prod_id, 1, 2) not in ('98', '99')
        order by 1""").fetchall()]  # fmt: skip
    desc = dict(descriptions().iter_rows())
    recent = months[-12]
    index, codes, n_files = [], set(), 0
    for ch in chapters:
        df = duckdb.sql(_panel_sql(ch)).pl()
        files: dict[str, dict] = {}
        for (hs10,), rows in df.partition_by("hs10", as_dict=True).items():
            p = product(rows, months)
            files.setdefault(file_for(hs10), {})[hs10] = p
            codes.update(s["c"] for s in p["s"] if s["c"] != "other")
            last12 = rows.filter(pl.col("month") >= recent).get_column("v").sum()
            index.append([hs10, desc.get(hs10) or "(no description)", sig(last12 / 1e6, 3)])
        for rel, prods in files.items():
            path = OUT_DIR / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(dict(sorted(prods.items())), separators=(",", ":")))
        n_files += len(files)
        print(f"chapter {ch}: {len(df):,} rows, {len(files)} files, "
              f"{time.time() - t0:.0f}s", flush=True)  # fmt: skip
    index.sort(key=lambda r: r[0])
    (OUT_DIR / "index.json").write_text(json.dumps(
        {"fields": ["hs10", "desc", "imports_12m_musd"], "rows": index,
         "aliases": aliases()}, separators=(",", ":")))  # fmt: skip
    meta = {
        "months": [m.strftime("%Y-%m") for m in months],
        "data_month": last.strftime("%Y-%m"),
        "built_on": date.today().isoformat(),
        "countries": country_names(codes),
        "fields": {
            "v": "customs value, imports for consumption, $ thousands",
            "uv": "pre-duty unit value: customs value / quantity (latest quantity unit only)",
            "e": "calculated duties / customs value (all duties, MFN included)",
            "r": "statutory additional duty rate (P10 timeline), change points",
        },
        "source": "U.S. Census Bureau international trade (HS10 imports for consumption, "
                  "calculated duties); tariff timeline compiled from the Federal Register "
                  "(data/reference/tariff_actions.csv).",
    }  # fmt: skip
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=1))
    size = sum(f.stat().st_size for f in OUT_DIR.rglob("*.json"))
    summary = {"products": len(index), "files": n_files, "mb": round(size / 1e6, 1),
               "seconds": round(time.time() - t0)}  # fmt: skip
    print(summary, flush=True)
    return summary


if __name__ == "__main__":
    sys.exit(0 if run() else 1)

"""Census annual HS10 import code lists with concordances (P06).

Each year's list gives every 10-digit HTS import code with its description, units of quantity,
SITC Rev. 4, end-use, USDA flag, NAICS and high-tech codes.

Sources (no single series covers every year):
- 2017-2022: census.gov/foreign-trade/reference/codes/concordance/impconcordYY.xls(x)
- 2023+:     census.gov/foreign-trade/schedules/b/YYYY/sbsdf.zip -> iconcord.txt (fixed width,
             layout in imp-stru.txt; same fields)

Output: data/interim/hs10_codes.parquet (year, hs10, ...).
"""

import io
import zipfile
from datetime import date

import polars as pl

from tpt import config
from tpt.ingest._http import CachedClient

CONCORD_URL = (
    "https://www.census.gov/foreign-trade/reference/codes/concordance/impconcord{yy}.{ext}"
)
SBSDF_URL = "https://www.census.gov/foreign-trade/schedules/b/{year}/sbsdf.zip"
FIRST_YEAR = 2017
LAST_EXCEL_YEAR = 2022

COLUMNS = ["hs10", "desc_long", "desc_short", "unit_qy1", "unit_qy2", "sitc", "end_use",
           "naics", "usda", "hitech"]  # fmt: skip

# imp-stru.txt layout (1-based inclusive columns converted to 0-based slices)
FIELDS = {
    "hs10": (0, 10),
    "desc_short": (14, 65),
    "desc_long": (69, 219),
    "unit_qy1": (224, 227),
    "unit_qy2": (232, 235),
    "sitc": (240, 245),
    "end_use": (250, 255),
    "usda": (260, 261),
    "naics": (265, 271),
    "hitech": (276, 278),
}
EXCEL_RENAME = {"commodity": "hs10", "descriptn": "desc_long", "abbreviatn": "desc_short"}

INTERIM_PATH = config.INTERIM_DIR / "hs10_codes.parquet"


def _clean(df: pl.DataFrame) -> pl.DataFrame:
    df = df.with_columns(pl.all().cast(pl.String).str.strip_chars())
    return df.with_columns(pl.when(pl.all() == "").then(None).otherwise(pl.all()).name.keep())


def parse_fixed_width(content: bytes) -> pl.DataFrame:
    lines = [ln for ln in content.decode("latin-1").splitlines() if ln.strip()]
    data = {name: [ln[a:b] for ln in lines] for name, (a, b) in FIELDS.items()}
    return _clean(pl.DataFrame(data)).select(COLUMNS)


def parse_excel(content: bytes) -> pl.DataFrame:
    df = pl.read_excel(content, sheet_id=1, infer_schema_length=0)  # first sheet: the list
    return _clean(df.rename(EXCEL_RENAME)).select(COLUMNS)


def fetch_year(client: CachedClient, year: int) -> pl.DataFrame:
    current = year >= date.today().year  # the current year's list is updated in place
    if year <= LAST_EXCEL_YEAR:
        yy = f"{year % 100:02d}"
        ext = "xlsx" if year >= 2020 else "xls"
        resp = client.get(CONCORD_URL.format(yy=yy, ext=ext), refresh=current)
        df = parse_excel(resp.content)
    else:
        resp = client.get(SBSDF_URL.format(year=year), refresh=current)
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        name = next(n for n in zf.namelist() if n.lower() in ("iconcord.txt", "imp-code.txt"))
        df = parse_fixed_width(zf.read(name))
    client.record_rows(resp, df.height)
    return df.with_columns(pl.lit(year, pl.Int32).alias("year"))


def run(last_year: int | None = None) -> pl.DataFrame:
    client = CachedClient("download")
    years = range(FIRST_YEAR, (last_year or date.today().year) + 1)
    df = pl.concat([fetch_year(client, y) for y in years]).select("year", *COLUMNS)
    INTERIM_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(INTERIM_PATH)
    counts = df.group_by("year").len().sort("year")
    print("HS10 code lists:", ", ".join(f"{y}: {n:,}" for y, n in counts.iter_rows()))
    return df


if __name__ == "__main__":
    run()

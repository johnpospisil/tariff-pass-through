"""Shared BLS plumbing: flat-file catalogs (download.bls.gov) and the API v2 (P05).

- Catalogs: `download.bls.gov/pub/time.series/<survey>/<file>`, tab separated with padded
  values. The host returns 403 unless the User-Agent carries a contact email (BLS_CONTACT_EMAIL
  in .env, sent to bls.gov only).
- Data: `api.bls.gov/publicAPI/v2/timeseries/data/`, POST. With a key: 50 series and 20 years per
  request, 500 requests/day. Without: 25 series, 10 years. A body with status other than
  REQUEST_SUCCEEDED (e.g. daily threshold reached) raises and is never cached.
- Values: "-" means unavailable (e.g. October 2025, lapse in appropriations); kept as null with
  the footnote text. Annual averages (M13) are dropped.
"""

import io
import json
import logging
from dataclasses import dataclass
from datetime import date

import polars as pl

from tpt import config
from tpt.ingest._http import CachedClient
from tpt.ingest.progress import ProgressFile, progress_path

log = logging.getLogger("tpt.bls")

DOWNLOAD_BASE = "https://download.bls.gov/pub/time.series/"
API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
START_YEAR = 2015  # two years before the sample so 12-month changes exist from 2017

INTERIM_DIR = config.INTERIM_DIR / "bls"


# --- flat files --------------------------------------------------------------


def parse_flat(content: bytes) -> pl.DataFrame:
    df = pl.read_csv(
        io.BytesIO(content),
        separator="\t",
        infer_schema=False,
        quote_char=None,
        encoding="utf8-lossy",
        truncate_ragged_lines=True,
    )
    df = df.rename({c: c.strip() for c in df.columns})
    return df.with_columns(pl.all().str.strip_chars())


def read_flat(path: str, client: CachedClient | None = None, refresh: bool = True) -> pl.DataFrame:
    """Read a catalog file such as 'cu/cu.series'. Refreshed by default (catalogs change)."""
    client = client or CachedClient("blsdownload")
    resp = client.get(DOWNLOAD_BASE + path, refresh=refresh)
    df = parse_flat(resp.content)
    client.record_rows(resp, df.height)
    return df


def active_since(df: pl.DataFrame, start_year: int) -> pl.Expr:
    return pl.col("end_year").cast(pl.Int32) >= start_year


# --- API ---------------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    series_ids: tuple[str, ...]
    start_year: int
    end_year: int

    def body(self) -> dict:
        return {
            "seriesid": list(self.series_ids),
            "startyear": str(self.start_year),
            "endyear": str(self.end_year),
        }


def plan_requests(ids: list[str], start_year: int, end_year: int, has_key: bool) -> list[Request]:
    per_request, window = (50, 20) if has_key else (25, 10)
    batches = [tuple(ids[i : i + per_request]) for i in range(0, len(ids), per_request)]
    windows = [(y, min(y + window - 1, end_year)) for y in range(start_year, end_year + 1, window)]
    return [Request(b, lo, hi) for b in batches for lo, hi in windows]


def validate_api(content: bytes) -> None:
    payload = json.loads(content)
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError(f"BLS API: {payload.get('status')}: {payload.get('message')}")


def _footnotes(notes: list[dict]) -> str | None:
    text = "; ".join(f"{n['code']}: {n.get('text', '')}" for n in notes if n and n.get("code"))
    return text or None


def parse_api(payload: dict) -> pl.DataFrame:
    rows = []
    for series in payload["Results"]["series"]:
        for obs in series["data"]:
            period = obs["period"]
            if not (period.startswith("M") and period != "M13"):
                continue
            value = obs["value"].strip()
            rows.append(
                {
                    "series_id": series["seriesID"],
                    "month": date(int(obs["year"]), int(period[1:]), 1),
                    "value": float(value) if value not in ("-", "") else None,
                    "footnotes": _footnotes(obs.get("footnotes", [])),
                }
            )
    schema = {"series_id": pl.String, "month": pl.Date, "value": pl.Float64, "footnotes": pl.String}
    return pl.DataFrame(rows, schema=schema)


def fetch_series(
    client: CachedClient,
    ids: list[str],
    start_year: int,
    end_year: int,
    refresh: bool = True,
    progress: ProgressFile | None = None,
) -> pl.DataFrame:
    requests = plan_requests(ids, start_year, end_year, has_key=client.source.api_key() is not None)
    if progress:
        progress.start(total=len(requests))
    frames = []
    for req in requests:
        resp = client.post_json(API_URL, req.body(), refresh=refresh, validate=validate_api)
        payload = resp.json()
        for msg in payload.get("message", []):
            if not msg.startswith("No Data Available"):
                log.warning("BLS: %s", msg)
        df = parse_api(payload)
        client.record_rows(resp, df.height)
        frames.append(df)
        if progress:
            progress.advance(rows=df.height, cached=resp.from_cache)
    out = pl.concat(frames).unique(["series_id", "month"], keep="last")
    return out.sort("series_id", "month")


def run_survey(
    name: str,
    catalog: pl.DataFrame,
    start_year: int = START_YEAR,
    end_year: int | None = None,
    refresh: bool = True,
) -> pl.DataFrame:
    """Fetch every catalog series; write interim data and the reference catalog; summarise."""
    end_year = end_year or date.today().year
    catalog_path = config.REFERENCE_DIR / f"bls_{name}_series.csv"
    catalog.write_csv(catalog_path)

    progress = ProgressFile(progress_path("bls"), label=f"bls {name}")
    data = fetch_series(
        CachedClient("bls"), catalog["series_id"].to_list(), start_year, end_year, refresh,
        progress,
    )  # fmt: skip
    progress.finish()
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    data.write_parquet(INTERIM_DIR / f"{name}.parquet")

    got = data.filter(pl.col("value").is_not_null())
    missing = catalog.filter(~pl.col("series_id").is_in(got["series_id"].unique().to_list()))
    gaps = (
        data.filter(pl.col("value").is_null())
        .group_by("month")
        .agg(pl.len().alias("series"), pl.col("footnotes").first())
        .sort("month")
    )
    print(f"\nBLS {name}: {catalog.height:,} series in catalog -> {catalog_path.name}; "
          f"{got['series_id'].n_unique():,} with data, {got.height:,} observations, "
          f"{got['month'].min()} to {got['month'].max()}")  # fmt: skip
    if missing.height:
        print(f"  {missing.height} catalog series returned no data in {start_year}-{end_year}")
    if gaps.height:
        print("  months with unavailable values ('-'):")
        for row in gaps.iter_rows(named=True):
            print(f"    {row['month']}: {row['series']} series - {row['footnotes']}")
    return data

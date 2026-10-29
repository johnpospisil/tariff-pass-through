"""Census International Trade API: HS10 x country x month imports (P03).

Endpoint: api.census.gov/data/timeseries/intltrade/imports/hs

Chunking: one request per individual country x calendar year (`time=from YYYY-01 to
YYYY-MM`, COMM_LVL=HS10). Probing showed per-country queries are fast (China, one month,
13k rows: ~9 s; Vietnam, one year, 74k rows: ~26 s) while commodity wildcards
(`I_COMMODITY=85*`) are slow or fail. A year chunk that fails is split into months.

Country codes: `SUMMARY_LVL` is `DET` for individual countries and `CGP` for groupings
(EU, OECD, ...). The all-countries total (code `-`) is also tagged `DET`, so individual
countries are `DET` and not `-`.

Outputs:
- data/interim/census_imports/year=YYYY/data.parquet   HS10 x country x month
- data/interim/census_totals.parquet                     country (and group) x month totals
- data/reference/census_countries.csv                    code, name, level, first/last month

Run:  make ingest-census          (full window, resumable: cached chunks are skipped)
      uv run python -m tpt.ingest.census_trade --years 2025   (pilot one year)
Watch: make ingest-status
"""

import argparse
import json
import logging
import random
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import polars as pl

from tpt import config
from tpt.ingest._http import CachedClient, CachedResponse, HttpError, compact_manifest
from tpt.ingest.progress import ProgressFile, progress_path

log = logging.getLogger("tpt.census")

URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"

HS10_VARS = [
    "I_COMMODITY",
    "CTY_CODE",
    "SUMMARY_LVL",
    "GEN_VAL_MO",  # general imports, customs value
    "CON_VAL_MO",  # imports for consumption, customs value (duties are assessed on these)
    "DUT_VAL_MO",  # dutiable value
    "CAL_DUT_MO",  # calculated duty
    "CON_CHA_MO",  # import charges (freight, insurance)
    "GEN_QY1_MO",
    "CON_QY1_MO",
    "UNIT_QY1",
    "CON_QY2_MO",
    "UNIT_QY2",
]
TOTAL_VARS = ["CTY_CODE", "CTY_NAME", "SUMMARY_LVL", "GEN_VAL_MO", "CON_VAL_MO",
              "DUT_VAL_MO", "CAL_DUT_MO"]  # fmt: skip

TOTAL_CODE = "-"
SAMPLE_START = config.SAMPLE_START.strftime("%Y-%m")

INTERIM_IMPORTS = config.INTERIM_DIR / "census_imports"
INTERIM_TOTALS = config.INTERIM_DIR / "census_totals.parquet"
COUNTRIES_CSV = config.REFERENCE_DIR / "census_countries.csv"
FAILURES_JSON = config.RAW_DIR / "census" / "_failures.json"


class MissingChunkError(Exception):
    pass


# --- parsing -----------------------------------------------------------------


def validate_response(content: bytes) -> None:
    """Reject bodies that are not a Census JSON table, so they are never cached."""
    if not content:
        return
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Census response is not JSON: {content[:80]!r}") from exc
    if not (isinstance(data, list) and data and isinstance(data[0], list)):
        raise ValueError("Census response is not a header + rows table")


def parse_response(content: bytes) -> pl.DataFrame:
    """Census JSON table -> typed frame. Repeated predicate columns are dropped."""
    if not content:
        return pl.DataFrame()
    header, *rows = json.loads(content)
    keep = [i for i, h in enumerate(header) if h not in header[:i] and h != "COMM_LVL"]
    names = [header[i].lower() for i in keep]
    columns = {n: [r[i] for r in rows] for n, i in zip(names, keep, strict=True)}
    df = pl.DataFrame(columns, schema={n: pl.String for n in names})
    df = df.rename({"i_commodity": "hs10"}) if "i_commodity" in df.columns else df
    numeric = [c for c in df.columns if c.endswith("_mo")]
    return df.with_columns(
        pl.col(numeric).str.strip_chars().cast(pl.Int64, strict=False),
        pl.col("time").str.to_date("%Y-%m").alias("month"),
    ).drop("time")


# --- planning ----------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Chunk:
    cty_code: str
    start: str  # YYYY-MM
    end: str  # YYYY-MM

    @property
    def year(self) -> int:
        return int(self.start[:4])

    @property
    def time_param(self) -> str:
        return self.start if self.start == self.end else f"from {self.start} to {self.end}"

    def params(self) -> dict[str, str]:
        return {
            "get": ",".join(HS10_VARS),
            "time": self.time_param,
            "COMM_LVL": "HS10",
            "CTY_CODE": self.cty_code,
        }

    def split_months(self) -> list["Chunk"]:
        first, last = int(self.start[5:]), int(self.end[5:])
        return [
            Chunk(self.cty_code, m, m)
            for m in (f"{self.year}-{i:02d}" for i in range(first, last + 1))
        ]


def year_spans(start: str, end: str) -> list[tuple[str, str]]:
    spans = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        lo = start if year == int(start[:4]) else f"{year}-01"
        hi = end if year == int(end[:4]) else f"{year}-12"
        spans.append((lo, hi))
    return spans


def window_start(latest: str, months: int) -> str:
    """First month of a trailing window of `months` months ending at `latest` (YYYY-MM)."""
    n = int(latest[:4]) * 12 + int(latest[5:]) - months
    return f"{n // 12}-{n % 12 + 1:02d}"


def window_chunks(chunks: list[Chunk], since: str) -> list[Chunk]:
    """Chunks whose span reaches into [since, ...]: whole years, so rewritten partitions stay
    complete."""
    return [c for c in chunks if c.end >= since]


def _month(ym: str) -> date:
    return date(int(ym[:4]), int(ym[5:]), 1)


def country_reference(totals: pl.DataFrame) -> pl.DataFrame:
    return (
        totals.group_by("cty_code")
        .agg(
            pl.col("cty_name").last(),
            pl.col("summary_lvl").first(),
            pl.col("month").min().alias("first_month"),
            pl.col("month").max().alias("last_month"),
        )
        .with_columns(
            ((pl.col("summary_lvl") == "DET") & (pl.col("cty_code") != TOTAL_CODE)).alias(
                "is_individual"
            )
        )
        .sort("cty_code")
    )


def plan_chunks(totals: pl.DataFrame, start: str, end: str) -> list[Chunk]:
    """One chunk per individual country x year with any recorded imports in that span."""
    individual = totals.filter(
        (pl.col("summary_lvl") == "DET") & (pl.col("cty_code") != TOTAL_CODE)
    )
    chunks = []
    for lo, hi in year_spans(start, end):
        active = (
            individual.filter(pl.col("month").is_between(_month(lo), _month(hi)))
            .group_by("cty_code")
            .agg(pl.col("gen_val_mo").sum())
            .filter(pl.col("gen_val_mo") > 0)
        )
        chunks += [Chunk(code, lo, hi) for code in sorted(active["cty_code"])]
    return chunks


# --- totals ------------------------------------------------------------------


def fetch_totals(
    client: CachedClient,
    start: str,
    end: str | None,
    workers: int = 4,
    progress: ProgressFile | None = None,
    refresh_from: int | None = None,
) -> pl.DataFrame:
    """Country x month totals (all commodities). The latest year (and every year from
    `refresh_from`) is re-fetched."""
    last_year = int(end[:4]) if end else date.today().year
    refresh_from = min(refresh_from or last_year, last_year)
    years = range(int(start[:4]), last_year + 1)
    if progress:
        progress.start(total=len(years), label="census totals")

    def one_year(year: int) -> pl.DataFrame:
        params = {"get": ",".join(TOTAL_VARS), "time": f"from {year}-01 to {year}-12"}
        resp = client.get(URL, params, refresh=year >= refresh_from, validate=validate_response)
        df = parse_response(resp.content)
        client.record_rows(resp, df.height)
        if progress:
            progress.advance(rows=df.height, cached=resp.from_cache)
        return df

    with ThreadPoolExecutor(workers) as pool:
        frames = list(pool.map(one_year, years))
    totals = pl.concat([df for df in frames if df.height])
    lo = _month(start)
    hi = _month(end) if end else totals["month"].max()
    return totals.filter(pl.col("month").is_between(lo, hi))


# --- fetching ----------------------------------------------------------------


@dataclass
class FetchResult:
    chunk: Chunk
    responses: list[CachedResponse] = field(default_factory=list)
    failed: list[Chunk] = field(default_factory=list)
    split: bool = False

    @property
    def from_cache(self) -> bool:
        return bool(self.responses) and all(r.from_cache for r in self.responses)

    def rows(self) -> int:
        return sum(max(len(json.loads(r.content)) - 1, 0) for r in self.responses if r.content)


def _get(client: CachedClient, chunk: Chunk, refresh: bool) -> CachedResponse:
    return client.get(URL, chunk.params(), refresh=refresh, validate=validate_response)


def fetch_chunk(client: CachedClient, chunk: Chunk, refresh: bool = False) -> FetchResult:
    result = FetchResult(chunk)
    try:
        result.responses.append(_get(client, chunk, refresh))
        return result
    except (HttpError, ValueError) as exc:
        if chunk.start == chunk.end:
            log.warning("chunk %s failed: %s", chunk, exc)
            result.failed.append(chunk)
            return result
        log.warning("chunk %s failed (%s); splitting into months", chunk, exc)
    result.split = True
    for month in chunk.split_months():
        try:
            result.responses.append(_get(client, month, refresh))
        except (HttpError, ValueError) as exc:
            log.warning("chunk %s failed: %s", month, exc)
            result.failed.append(month)
    return result


def load_chunk(client: CachedClient, chunk: Chunk) -> pl.DataFrame:
    """Parse a chunk from the cache: the whole-span response, else its month responses."""
    responses = [client.cached(URL, chunk.params())]
    if responses[0] is None:
        responses = [client.cached(URL, m.params()) for m in chunk.split_months()]
        missing = [m for m, r in zip(chunk.split_months(), responses, strict=True) if r is None]
        if missing:
            raise MissingChunkError(f"{chunk}: not cached: {[m.start for m in missing]}")
    frames = []
    for resp in responses:
        df = parse_response(resp.content)
        client.record_rows(resp, df.height)
        if df.height:
            frames.append(df)
    return pl.concat(frames) if frames else pl.DataFrame()


def build_interim(client: CachedClient, chunks: list[Chunk], out_dir: Path) -> dict[int, int]:
    """Write one parquet per year from cached chunks. Returns rows written per year."""
    by_year: dict[int, list[Chunk]] = defaultdict(list)
    for chunk in chunks:
        by_year[chunk.year].append(chunk)
    stats = {}
    for year in sorted(by_year):
        frames = [df for c in sorted(by_year[year]) if (df := load_chunk(client, c)).height]
        if not frames:
            continue
        df = pl.concat(frames, how="diagonal").sort("month", "cty_code", "hs10")
        path = out_dir / f"year={year}" / "data.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
        stats[year] = df.height
    return stats


# --- run ---------------------------------------------------------------------


def run(
    start: str = SAMPLE_START,
    end: str | None = None,
    years: list[int] | None = None,
    workers: int = 4,
    refresh: bool = False,
    refresh_months: int | None = None,
) -> None:
    """refresh_months: re-download the years covering the trailing window of that many months
    (Census revisions) and rebuild only those year partitions; older years are left as they are,
    so their raw cache is not needed (CI)."""
    client = CachedClient("census")
    t0 = time.time()

    progress = ProgressFile(progress_path("census"), label="census totals")
    refresh_from = None
    if refresh_months:  # the latest month is not known yet: refresh from the window's year
        today = date.today().strftime("%Y-%m")
        refresh_from = int(window_start(today, refresh_months + 2)[:4])
    totals = fetch_totals(client, start, end, workers, progress, refresh_from)
    INTERIM_TOTALS.parent.mkdir(parents=True, exist_ok=True)
    totals.write_parquet(INTERIM_TOTALS)
    country_reference(totals).write_csv(COUNTRIES_CSV)
    latest = totals["month"].max().strftime("%Y-%m")
    log.warning("totals: %s rows, latest month %s", f"{totals.height:,}", latest)

    chunks = plan_chunks(totals, start, end or latest)
    if years:
        chunks = [c for c in chunks if c.year in years]
    if refresh_months:
        since = window_start(latest, refresh_months)
        chunks = window_chunks(chunks, since)
        refresh = True
        log.warning("refreshing %s chunks touching %s..%s", len(chunks), since, latest)
    random.Random(0).shuffle(chunks)  # mix big and small countries so the ETA is stable

    progress.start(total=len(chunks), label="census HS10")
    failed: list[Chunk] = []
    with ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(fetch_chunk, client, c, refresh) for c in chunks]
        for fut in as_completed(futures):
            res = fut.result()
            failed += res.failed
            progress.advance(rows=res.rows(), cached=res.from_cache, failed=bool(res.failed))
    progress.finish()

    FAILURES_JSON.write_text(json.dumps([c.__dict__ for c in sorted(failed)], indent=1))
    complete = [c for c in chunks if not any(f.cty_code == c.cty_code and f.year == c.year
                                             for f in failed)]  # fmt: skip
    stats = build_interim(client, complete, INTERIM_IMPORTS)
    compact_manifest()

    print(f"chunks: {len(chunks):,} planned, {len(failed):,} failed months "
          f"(see {FAILURES_JSON.relative_to(config.PROJECT_ROOT)})")  # fmt: skip
    for year, rows in stats.items():
        print(f"  {year}: {rows:,} rows")
    print(f"total rows {sum(stats.values()):,}; latest month {latest}; "
          f"elapsed {(time.time() - t0) / 60:.1f} min")  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", default=SAMPLE_START, help="first month, YYYY-MM")
    parser.add_argument("--end", default=None, help="last month, YYYY-MM (default: latest)")
    parser.add_argument("--years", type=int, nargs="*", help="only these years (pilot)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--refresh", action="store_true", help="re-download cached chunks")
    parser.add_argument(
        "--refresh-months",
        type=int,
        default=None,
        help="re-pull only the years covering this trailing window (revisions)",
    )
    args = parser.parse_args()

    log_path = config.RAW_DIR / "census" / "ingest.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )
    run(args.start, args.end, args.years, args.workers, args.refresh, args.refresh_months)


if __name__ == "__main__":
    main()

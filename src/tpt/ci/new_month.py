"""Is a Census month newer than the published data available? (P24 monthly refresh gate)

Census moved its 2026 FT-900 release dates after the funding lapse, so the workflow runs
weekly early in the month and rebuilds only when the API has a month the site does not.
Writes new/available/published to $GITHUB_OUTPUT when set.
"""

import os
import sys
from datetime import date
from pathlib import Path

import polars as pl

from tpt import config
from tpt.ingest._http import CachedClient
from tpt.ingest.census_trade import TOTAL_CODE, URL, parse_response, validate_response

PUBLISHED = config.PUBLISHED_DIR / "effective_rates.csv"


def latest_published(path: Path = PUBLISHED) -> str:
    return pl.read_csv(path).get_column("month").max()[:7]


def latest_available() -> str | None:
    """Latest month in the Census imports API (total, all countries), or None on failure."""
    year = date.today().year
    params = {"get": "CTY_CODE,GEN_VAL_MO", "CTY_CODE": TOTAL_CODE,
              "time": f"from {year - 1}-01 to {year}-12"}  # fmt: skip
    try:
        resp = CachedClient("census").get(URL, params, refresh=True, validate=validate_response)
    except Exception as e:  # network or API error: report, do not rebuild
        print(f"Census API check failed: {type(e).__name__}", file=sys.stderr)
        return None
    return parse_response(resp.content).get_column("month").max().strftime("%Y-%m")


def decide(available: str | None, published: str) -> bool:
    return available is not None and available > published


def write_output(path: Path, new: bool, available: str | None, published: str) -> None:
    with open(path, "a") as f:
        f.write(f"new={'true' if new else 'false'}\navailable={available}\n"
                f"published={published}\n")  # fmt: skip


def main() -> None:
    published, available = latest_published(), latest_available()
    new = decide(available, published)
    print(f"published {published}; Census API latest {available}; rebuild: {new}")
    if out := os.environ.get("GITHUB_OUTPUT"):
        write_output(Path(out), new, available, published)


if __name__ == "__main__":
    main()

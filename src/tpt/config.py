"""Project paths, sample window and API key loading.

Keys are read from the environment (and a git-ignored `.env` at the project root).
Code must run without keys, at lower API rate limits. Never log key values.
"""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"  # untouched API responses, never edited
INTERIM_DIR = DATA_DIR / "interim"  # parsed, typed parquet
PROCESSED_DIR = DATA_DIR / "processed"  # analysis-ready panels
REFERENCE_DIR = DATA_DIR / "reference"  # small hand-built, cited tables (committed)
PUBLISHED_DIR = DATA_DIR / "published"  # aggregates for the report and explorer

REPORT_DIR = PROJECT_ROOT / "report"
FIGURES_DIR = REPORT_DIR / "figures"
GITHUB_REPO = "johnpospisil/tariff-pass-through"  # data links in the report

# Sample window: 2017 onward so the 2018-19 trade war can be replicated as a check.
# SAMPLE_END = None means "latest month available".
SAMPLE_START = date(2017, 1, 1)
SAMPLE_END: date | None = None

load_dotenv(PROJECT_ROOT / ".env", override=False)


def _key(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def census_api_key() -> str | None:
    return _key("CENSUS_API_KEY")


def bls_api_key() -> str | None:
    return _key("BLS_API_KEY")

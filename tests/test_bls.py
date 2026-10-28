"""Tests for the BLS ingest: flat-file catalogs and API v2 data (P05)."""

import json
from datetime import date
from pathlib import Path

import httpx
import polars as pl
import pytest

from tpt.ingest import _bls, bls_cpi, bls_mxp, bls_ppi
from tpt.ingest._http import CachedClient, Source

FIXTURES = Path(__file__).parent / "fixtures"
API_FIXTURE = FIXTURES / "bls_api_sample.json"

# Real catalog lines (padded series ids, tab separated), trimmed.
EI_SERIES = (
    "series_id                     \tseasonal\tindex_code\tseries_name\tbase_period\tseries_title"
    "\tfootnote_codes\tbegin_year\tbegin_period\tend_year\tend_period\n"
    "EIUCDCANTOT                   \tU\tCD\tCanada-All Industries\tDecember 2017=100\tMonthly "
    "export price index by destination\t\t2017\tM12\t2026\tM09\n"
    "EIUCOCHNTOT                   \tU\tCO\tChina-All Industries\tDecember 2003=100\tMonthly "
    "import price index by origin for NAICS, All industries, China\t\t2003\tM12\t2026\tM09\n"
    "EIUIR                         \tU\tIR\tAll commodities\t2000=100\tMonthly import price index "
    "for BEA End Use, All commodities\t\t1988\tM09\t2026\tM09\n"
    "EIUIQ                         \tU\tIQ\tAll commodities\t2000=100\tMonthly export price index "
    "for BEA End Use, All commodities\t\t1983\tM09\t2026\tM09\n"
    "EIUIP0102                     \tU\tIP\tBovine animals\tJanuary 2025=100\tMonthly import price "
    "index for Harmonized 0102\t\t2025\tM01\t2026\tM09\n"
    "EIUIZ11                       \tU\tIZ\tAgriculture\tDecember 2005=100\tMonthly import price "
    "index for NAICS 11\t\t2005\tM12\t2014\tM12\n"
)
EI_INDEX = (
    "index_code\tindex_name\nCD\tLocality of Destination Price Indexes\nCO\tLocality of Origin "
    "Price Indexes\nIP\tHarmonized System Import Price Indexes\nIQ\tBEA End Use Export Price "
    "Indexes\nIR\tBEA End Use Import Price Indexes\nIZ\tNAICS Import Price Indexes\n"
)


def _flat(text: str) -> pl.DataFrame:
    return _bls.parse_flat(text.encode())


# --- flat files and catalogs -------------------------------------------------


def test_parse_flat_strips_padding():
    df = _flat(EI_SERIES)
    assert df.columns[0] == "series_id"
    assert df["series_id"][1] == "EIUCOCHNTOT"
    assert df["end_year"][1] == "2026"


def test_mxp_catalog_keeps_active_import_families():
    cat = bls_mxp.catalog(_flat(EI_SERIES), _flat(EI_INDEX), start_year=2015)
    assert sorted(cat["series_id"]) == ["EIUCOCHNTOT", "EIUIP0102", "EIUIR"]
    china = cat.filter(pl.col("series_id") == "EIUCOCHNTOT").row(0, named=True)
    assert china["index_name"] == "Locality of Origin Price Indexes"
    assert china["base_period"] == "December 2003=100"


def test_cpi_catalog_us_average_monthly_with_item_levels():
    series = _flat(
        "series_id\tarea_code\titem_code\tseasonal\tperiodicity_code\tbase_code\tbase_period"
        "\tseries_title\tfootnote_codes\tbegin_year\tbegin_period\tend_year\tend_period\n"
        "CUUR0000SA0\t0000\tSA0\tU\tR\tS\t1982-84=100\tAll items\t\t1913\tM01\t2026\tM09\n"
        "CUSR0000SA0\t0000\tSA0\tS\tR\tS\t1982-84=100\tAll items SA\t\t1947\tM01\t2026\tM09\n"
        "CUUS0000SA0\t0000\tSA0\tU\tS\tS\t1982-84=100\tSemiannual\t\t1984\tS01\t2026\tS01\n"
        "CUUR0100SA0\t0100\tSA0\tU\tR\tS\t1982-84=100\tNortheast\t\t1966\tM07\t2026\tM09\n"
        "CUUR0000SEHA\t0000\tSEHA\tU\tR\tS\t1982-84=100\tRent\t\t1914\tM12\t2014\tM12\n"
    )
    items = _flat(
        "item_code\titem_name\tdisplay_level\tselectable\tsort_sequence\n"
        "SA0\tAll items\t0\tT\t1\nSEHA\tRent of primary residence\t3\tT\t50\n"
    )
    cat = bls_cpi.catalog(series, items, start_year=2015)
    assert sorted(cat["series_id"]) == ["CUSR0000SA0", "CUUR0000SA0"]
    assert set(cat["item_name"]) == {"All items"}
    assert cat.schema["display_level"] == pl.Int32


def test_ppi_catalog_goods_groups_shallow_plus_final_demand():
    series = _flat(
        "series_id\tgroup_code\titem_code\tseasonal\tbase_date\tseries_title\tfootnote_codes"
        "\tbegin_year\tbegin_period\tend_year\tend_period\n"
        "WPU01\t01\t-\tU\t198200\tFarm products\t\t1913\tM01\t2026\tM09\n"
        "WPU011\t01\t1\tU\t198200\tFruits\t\t1913\tM01\t2026\tM09\n"
        "WPU01110101\t01\t110101\tU\t198200\tApples\t\t1913\tM01\t2026\tM09\n"
        "WPS011\t01\t1\tS\t198200\tFruits SA\t\t1967\tM01\t2026\tM09\n"
        "WPU3011\t30\t11\tU\t200906\tServices\t\t2009\tM06\t2026\tM09\n"
        "WPUFD41\tFD41\t-\tU\t200911\tFinal demand goods\t\t2009\tM11\t2026\tM09\n"
    )
    groups = _flat(
        "group_code\tgroup_name\n01\tFarm products\n30\tServices\nFD41\tFinal demand goods\n"
    )
    cat = bls_ppi.catalog(series, groups, start_year=2015)
    assert sorted(cat["series_id"]) == ["WPU01", "WPU011", "WPUFD41"]


# --- API ---------------------------------------------------------------------


def test_parse_api_long_monthly_with_missing_and_footnotes():
    df = _bls.parse_api(json.loads(API_FIXTURE.read_text()))
    assert set(df.columns) >= {"series_id", "month", "value", "footnotes"}
    assert df.filter(pl.col("month").is_null()).height == 0  # M13 annual averages dropped
    cpi_oct = df.filter(
        (pl.col("series_id") == "CUUR0000SA0") & (pl.col("month") == date(2025, 10, 1))
    )
    assert cpi_oct["value"].item() is None
    assert "lapse in appropriations" in cpi_oct["footnotes"].item()
    revised = df.filter(
        (pl.col("series_id") == "EIUCOCHNTOT") & (pl.col("month") == date(2026, 9, 1))
    )
    assert revised["value"].item() == pytest.approx(100.1)


def test_validate_rejects_unprocessed_requests():
    with pytest.raises(ValueError, match="daily threshold"):
        _bls.validate_api(
            json.dumps(
                {"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold reached"]}
            ).encode()
        )
    _bls.validate_api(API_FIXTURE.read_bytes())


def test_batches_with_and_without_key():
    ids = [f"S{i}" for i in range(120)]
    with_key = _bls.plan_requests(ids, 2015, 2026, has_key=True)
    assert len(with_key) == 3  # 50 + 50 + 20 series, one 12-year window
    assert {(r.start_year, r.end_year) for r in with_key} == {(2015, 2026)}
    no_key = _bls.plan_requests(ids, 2015, 2026, has_key=False)
    assert len(no_key) == 5 * 2  # 25 series per request, 10-year windows
    assert max(len(r.series_ids) for r in no_key) == 25


def test_fetch_posts_batches_and_combines(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_BLS_KEY", "k")
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        series = [
            {
                "seriesID": s,
                "data": [{"year": "2025", "period": "M01", "value": "1.5", "footnotes": [{}]}],
            }  # fmt: skip
            for s in body["seriesid"]
        ]
        return httpx.Response(200, json={"status": "REQUEST_SUCCEEDED", "message": [],
                                         "Results": {"series": series}})  # fmt: skip

    src = Source("bls", 0.0, key_param="registrationkey", key_env="TEST_BLS_KEY",
                 key_location="json")  # fmt: skip
    client = CachedClient(src, raw_dir=tmp_path, transport=httpx.MockTransport(handler),
                          sleep=lambda s: None)  # fmt: skip
    ids = [f"S{i}" for i in range(60)]
    df = _bls.fetch_series(client, ids, 2025, 2025)
    assert len(bodies) == 2
    assert bodies[0]["registrationkey"] == "k"
    assert bodies[0]["startyear"] == "2025"
    assert df.height == 60
    assert df["series_id"].n_unique() == 60

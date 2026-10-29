"""Tests for the Census International Trade ingest (P03)."""

import json
from datetime import date
from pathlib import Path

import httpx
import polars as pl
import pytest

from tpt.ingest import census_trade as ct
from tpt.ingest._http import CachedClient, Source

FIXTURES = Path(__file__).parent / "fixtures"
HS10_FIXTURE = FIXTURES / "census_hs10_vietnam_2024.json"


# --- parsing -----------------------------------------------------------------


def test_parse_drops_repeated_predicate_columns_and_types_values():
    df = ct.parse_response(HS10_FIXTURE.read_bytes())
    assert df.columns.count("cty_code") == 1
    assert "comm_lvl" not in df.columns
    assert df.schema["month"] == pl.Date
    assert df.schema["hs10"] == pl.String
    assert df.schema["con_val_mo"] == pl.Int64
    assert df.schema["cal_dut_mo"] == pl.Int64
    first = df.row(0, named=True)
    assert first["hs10"] == "0106110000"
    assert first["month"] == date(2024, 1, 1)
    assert first["con_val_mo"] == 6_120_000
    assert first["con_qy1_mo"] == 680
    assert first["unit_qy1"] == "NO"


def test_parse_null_and_blank_values_become_null():
    df = ct.parse_response(HS10_FIXTURE.read_bytes())
    row = df.filter(pl.col("hs10") == "9999999999").row(0, named=True)
    assert row["con_val_mo"] is None
    assert row["cal_dut_mo"] is None
    assert row["con_qy1_mo"] == 12


def test_parse_keeps_true_zero_rows():
    df = ct.parse_response(HS10_FIXTURE.read_bytes())
    assert df.filter(pl.col("con_val_mo") == 0).height == 1


def test_parse_empty_response():
    df = ct.parse_response(b"")
    assert df.height == 0


def test_validate_rejects_non_json():
    with pytest.raises(ValueError):
        ct.validate_response(b"<html>error</html>")
    ct.validate_response(b"")  # 204 no content is fine
    ct.validate_response(HS10_FIXTURE.read_bytes())


# --- planning ----------------------------------------------------------------


def test_year_chunks_cover_window_and_stop_at_latest_month():
    spans = ct.year_spans("2017-01", "2026-08")
    assert spans[0] == ("2017-01", "2017-12")
    assert spans[-1] == ("2026-01", "2026-08")
    assert len(spans) == 10


def test_year_spans_partial_start():
    assert ct.year_spans("2025-06", "2026-02") == [("2025-06", "2025-12"), ("2026-01", "2026-02")]


def test_chunk_time_param_and_split():
    year = ct.Chunk("5520", "2024-01", "2024-12")
    assert year.time_param == "from 2024-01 to 2024-12"
    months = year.split_months()
    assert len(months) == 12
    assert months[0] == ct.Chunk("5520", "2024-01", "2024-01")
    assert months[0].time_param == "2024-01"


def test_individual_countries_exclude_total_and_groupings():
    totals = pl.DataFrame(
        {
            "cty_code": ["-", "0003", "1XXX", "5700", "5520", "5700"],
            "cty_name": [
                "TOTAL FOR ALL COUNTRIES",
                "EUROPEAN UNION",
                "NORTH AMERICA",
                "CHINA",
                "VIETNAM",
                "CHINA",
            ],
            "summary_lvl": ["DET", "CGP", "CGP", "DET", "DET", "DET"],
            "gen_val_mo": [100, 50, 20, 10, 5, 7],
            "month": [date(2024, 1, 1)] * 5 + [date(2025, 1, 1)],
        }
    )
    ref = ct.country_reference(totals)
    individual = ref.filter(pl.col("is_individual"))["cty_code"].to_list()
    assert sorted(individual) == ["5520", "5700"]
    china = ref.filter(pl.col("cty_code") == "5700").row(0, named=True)
    assert china["first_month"] == date(2024, 1, 1)
    assert china["last_month"] == date(2025, 1, 1)


def test_plan_chunks_only_countries_trading_that_year():
    totals = pl.DataFrame(
        {
            "cty_code": ["5700", "5520", "5520"],
            "cty_name": ["CHINA", "VIETNAM", "VIETNAM"],
            "summary_lvl": ["DET"] * 3,
            "gen_val_mo": [10, 0, 3],
            "month": [date(2024, 1, 1), date(2024, 1, 1), date(2025, 1, 1)],
        }
    )
    chunks = ct.plan_chunks(totals, "2024-01", "2025-03")
    assert set(chunks) == {
        ct.Chunk("5700", "2024-01", "2024-12"),
        ct.Chunk("5520", "2025-01", "2025-03"),
    }


# --- fetching ----------------------------------------------------------------


def _month_payload(request: httpx.Request) -> list:
    month = request.url.params["time"]
    cty = request.url.params["CTY_CODE"]
    header = [
        "I_COMMODITY",
        "CTY_CODE",
        "SUMMARY_LVL",
        "CON_VAL_MO",
        "time",
        "COMM_LVL",
        "CTY_CODE",
    ]
    return [header, ["0101210010", cty, "DET", "5", month, "HS10", cty]]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "k")
    source = Source("census", 0.0, key_param="key", key_env="TEST_API_KEY")

    def make(handler):
        return CachedClient(
            source,
            raw_dir=tmp_path,
            transport=httpx.MockTransport(handler),
            sleep=lambda s: None,
            max_attempts=1,
        )

    return make


def test_fetch_chunk_splits_year_into_months_on_failure(client):
    def handler(request):
        if request.url.params["time"].startswith("from"):
            return httpx.Response(500)
        return httpx.Response(200, json=_month_payload(request))

    c = client(handler)
    result = ct.fetch_chunk(c, ct.Chunk("5700", "2024-01", "2024-12"))
    assert result.failed == []
    assert len(result.responses) == 12
    assert result.split


def test_fetch_chunk_reports_months_that_still_fail(client):
    def handler(request):
        t = request.url.params["time"]
        if t.startswith("from") or t == "2024-05":
            return httpx.Response(500)
        return httpx.Response(200, json=_month_payload(request))

    c = client(handler)
    result = ct.fetch_chunk(c, ct.Chunk("5700", "2024-01", "2024-12"))
    assert result.failed == [ct.Chunk("5700", "2024-05", "2024-05")]
    assert len(result.responses) == 11


def test_load_chunk_prefers_year_then_month_cache(client):
    def handler(request):
        if request.url.params["time"].startswith("from"):
            return httpx.Response(500)
        return httpx.Response(200, json=_month_payload(request))

    c = client(handler)
    chunk = ct.Chunk("5700", "2024-01", "2024-03")
    ct.fetch_chunk(c, chunk)
    df = ct.load_chunk(c, chunk)
    assert df.height == 3
    assert sorted(df["month"].dt.month().to_list()) == [1, 2, 3]


def test_load_chunk_raises_when_months_missing(client):
    c = client(lambda r: httpx.Response(500))
    with pytest.raises(ct.MissingChunkError):
        ct.load_chunk(c, ct.Chunk("5700", "2024-01", "2024-02"))


def test_build_interim_writes_one_parquet_per_year(client, tmp_path):
    def handler(request):
        return httpx.Response(200, json=_month_payload(request))

    c = client(handler)
    chunks = [ct.Chunk("5700", "2024-12", "2024-12"), ct.Chunk("5700", "2025-01", "2025-01")]
    for ch in chunks:
        ct.fetch_chunk(c, ch)
    out = tmp_path / "interim"
    stats = ct.build_interim(c, chunks, out)
    assert (out / "year=2024" / "data.parquet").exists()
    assert (out / "year=2025" / "data.parquet").exists()
    assert stats == {2024: 1, 2025: 1}
    df = pl.read_parquet(out / "year=2025" / "data.parquet")
    assert df["hs10"].to_list() == ["0101210010"]


def test_fixture_is_real_census_shape():
    header = json.loads(HS10_FIXTURE.read_text())[0]
    assert header[-1] == "CTY_CODE" and header.count("CTY_CODE") == 2


# --- trailing-window refresh (P24) ---------------------------------------------


def test_window_start_counts_back_from_latest_month():
    assert ct.window_start("2026-08", 24) == "2024-09"
    assert ct.window_start("2026-01", 1) == "2026-01"


def test_window_chunks_are_whole_years_touching_the_window():
    """Year chunks overlapping the window are refreshed whole, so each rewritten year
    partition stays complete; earlier years keep their existing partitions."""
    chunks = [ct.Chunk("5700", lo, hi) for lo, hi in ct.year_spans("2017-01", "2026-08")]
    got = ct.window_chunks(chunks, "2024-09")
    assert [c.start for c in got] == ["2024-01", "2025-01", "2026-01"]
    assert got[-1].end == "2026-08"

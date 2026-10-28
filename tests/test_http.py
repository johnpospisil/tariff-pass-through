"""Tests for the shared HTTP, cache and manifest layer (P02)."""

import json
import logging

import httpx
import polars as pl
import pytest

from tpt.ingest import _http
from tpt.ingest._http import CachedClient, HttpError, RateLimiter, Source

SECRET = "SECRET-KEY-123"
URL = "https://api.example.test/data"


class Recorder:
    """Mock transport handler that replays a list of responses and records requests."""

    def __init__(self, *responses):
        self.responses = list(responses) or [httpx.Response(200, json=[["a"], ["1"]])]
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        resp = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return resp


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", SECRET)
    return Source(
        name="test",
        min_interval=0.0,
        key_param="key",
        key_env="TEST_API_KEY",
    )


@pytest.fixture
def json_source(monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", SECRET)
    return Source(
        name="testjson",
        min_interval=0.0,
        key_param="registrationkey",
        key_env="TEST_API_KEY",
        key_location="json",
    )


def make_client(source, tmp_path, handler, **kw):
    sleeps: list[float] = []
    client = CachedClient(
        source,
        raw_dir=tmp_path,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **kw,
    )
    return client, sleeps


# --- cache -------------------------------------------------------------------


def test_cache_hit_skips_network(source, tmp_path):
    rec = Recorder()
    client, _ = make_client(source, tmp_path, rec)
    first = client.get(URL, params={"time": "2025-01"})
    second = client.get(URL, params={"time": "2025-01"})
    assert len(rec.requests) == 1
    assert not first.from_cache
    assert second.from_cache
    assert second.content == first.content
    assert second.json() == [["a"], ["1"]]


def test_cache_key_ignores_api_key_and_param_order(source, tmp_path, monkeypatch):
    rec = Recorder()
    client, _ = make_client(source, tmp_path, rec)
    client.get(URL, params={"a": "1", "b": "2"})
    monkeypatch.setenv("TEST_API_KEY", "a-different-key")
    again = client.get(URL, params={"b": "2", "a": "1"})
    assert again.from_cache
    assert len(rec.requests) == 1


def test_different_params_are_different_cache_entries(source, tmp_path):
    rec = Recorder()
    client, _ = make_client(source, tmp_path, rec)
    client.get(URL, params={"time": "2025-01"})
    client.get(URL, params={"time": "2025-02"})
    assert len(rec.requests) == 2


def test_refresh_bypasses_cache(source, tmp_path):
    rec = Recorder()
    client, _ = make_client(source, tmp_path, rec)
    client.get(URL, params={"t": "1"})
    resp = client.get(URL, params={"t": "1"}, refresh=True)
    assert not resp.from_cache
    assert len(rec.requests) == 2


def test_cache_files_live_under_source_dir(source, tmp_path):
    client, _ = make_client(source, tmp_path, Recorder())
    resp = client.get(URL, params={"t": "1"})
    assert resp.path.is_relative_to(tmp_path / "test")
    assert resp.path.read_bytes() == resp.content


def test_204_no_content_is_cached_as_empty(source, tmp_path):
    rec = Recorder(httpx.Response(204))
    client, _ = make_client(source, tmp_path, rec)
    first = client.get(URL, params={"t": "1"})
    second = client.get(URL, params={"t": "1"})
    assert first.status_code == 204
    assert first.content == b""
    assert second.from_cache
    assert len(rec.requests) == 1


def test_validate_rejection_is_not_cached(source, tmp_path):
    rec = Recorder(httpx.Response(200, json={"status": "REQUEST_NOT_PROCESSED"}))
    client, _ = make_client(source, tmp_path, rec)

    def validate(content: bytes) -> None:
        if b"NOT_PROCESSED" in content:
            raise ValueError("rejected")

    with pytest.raises(ValueError):
        client.get(URL, params={"t": "1"}, validate=validate)
    with pytest.raises(ValueError):
        client.get(URL, params={"t": "1"}, validate=validate)
    assert len(rec.requests) == 2


def test_post_json_is_cached_by_body(json_source, tmp_path):
    rec = Recorder(httpx.Response(200, json={"status": "REQUEST_SUCCEEDED"}))
    client, _ = make_client(json_source, tmp_path, rec)
    client.post_json(URL, {"seriesid": ["A", "B"]})
    again = client.post_json(URL, {"seriesid": ["A", "B"]})
    client.post_json(URL, {"seriesid": ["C"]})
    assert again.from_cache
    assert len(rec.requests) == 2


# --- retries -----------------------------------------------------------------


def test_retries_on_429_then_succeeds(source, tmp_path):
    rec = Recorder(
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(429),
        httpx.Response(200, json={"ok": True}),
    )
    client, sleeps = make_client(source, tmp_path, rec)
    resp = client.get(URL, params={"t": "1"})
    assert resp.json() == {"ok": True}
    assert len(rec.requests) == 3
    assert len(sleeps) >= 2
    assert max(sleeps) >= 7  # Retry-After honoured


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_retries_on_5xx(source, tmp_path, status):
    rec = Recorder(httpx.Response(status), httpx.Response(200, json={}))
    client, _ = make_client(source, tmp_path, rec)
    client.get(URL, params={"t": "1"})
    assert len(rec.requests) == 2


def test_retries_on_transport_error(source, tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={})

    client, _ = make_client(source, tmp_path, handler)
    client.get(URL, params={"t": "1"})
    assert calls["n"] == 2


def test_gives_up_after_max_attempts(source, tmp_path):
    rec = Recorder(httpx.Response(503))
    client, _ = make_client(source, tmp_path, rec, max_attempts=3)
    with pytest.raises(HttpError) as exc:
        client.get(URL, params={"t": "1"})
    assert exc.value.status_code == 503
    assert len(rec.requests) == 3


def test_client_error_not_retried(source, tmp_path):
    rec = Recorder(httpx.Response(404))
    client, _ = make_client(source, tmp_path, rec)
    with pytest.raises(HttpError) as exc:
        client.get(URL, params={"t": "1"})
    assert exc.value.status_code == 404
    assert len(rec.requests) == 1


# --- keys --------------------------------------------------------------------


def test_key_is_sent_in_query(source, tmp_path):
    rec = Recorder()
    client, _ = make_client(source, tmp_path, rec)
    client.get(URL, params={"t": "1"})
    assert rec.requests[0].url.params["key"] == SECRET


def test_key_is_sent_in_json_body(json_source, tmp_path):
    rec = Recorder(httpx.Response(200, json={}))
    client, _ = make_client(json_source, tmp_path, rec)
    client.post_json(URL, {"seriesid": ["A"]})
    assert json.loads(rec.requests[0].content)["registrationkey"] == SECRET


def test_no_key_configured_sends_no_key(source, tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_API_KEY")
    rec = Recorder()
    client, _ = make_client(source, tmp_path, rec)
    client.get(URL, params={"t": "1"})
    assert "key" not in rec.requests[0].url.params


def test_key_never_in_manifest_meta_or_logs(source, json_source, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    client, _ = make_client(source, tmp_path, Recorder())
    client.get(URL, params={"t": "1"})
    jclient, _ = make_client(json_source, tmp_path, Recorder(httpx.Response(200, json={})))
    jclient.post_json(URL, {"seriesid": ["A"]})
    _http.compact_manifest(tmp_path)

    assert "HTTP Request" in caplog.text  # httpx did log the request...
    assert SECRET not in caplog.text  # ...but with the key redacted
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.suffix != ".bin":
            assert SECRET.encode() not in path.read_bytes(), path


def test_key_never_in_error_message(source, tmp_path):
    client, _ = make_client(source, tmp_path, Recorder(httpx.Response(403)))
    with pytest.raises(HttpError) as exc:
        client.get(URL, params={"t": "1"})
    assert SECRET not in str(exc.value)
    assert SECRET not in repr(exc.value)


# --- manifest ----------------------------------------------------------------


def test_manifest_row_per_network_fetch_only(source, tmp_path):
    client, _ = make_client(source, tmp_path, Recorder())
    resp = client.get(URL, params={"t": "1"})
    client.get(URL, params={"t": "1"})  # cache hit, no new row
    client.record_rows(resp, 42)
    manifest = _http.compact_manifest(tmp_path)

    assert (tmp_path / "manifest.parquet").exists()
    assert manifest.height == 1
    row = manifest.row(0, named=True)
    assert row["source"] == "test"
    assert row["url"] == URL
    assert json.loads(row["params"]) == {"t": "1"}
    assert row["sha256"] == resp.sha256
    assert row["rows"] == 42
    assert row["retrieved_at"] is not None
    assert pl.read_parquet(tmp_path / "manifest.parquet").equals(manifest)


def test_compact_manifest_when_empty(tmp_path):
    manifest = _http.compact_manifest(tmp_path)
    assert manifest.height == 0
    assert "sha256" in manifest.columns


# --- rate limiting -----------------------------------------------------------


def test_rate_limiter_spaces_requests():
    now = {"t": 100.0}
    sleeps: list[float] = []

    def sleep(s):
        sleeps.append(s)
        now["t"] += s

    limiter = RateLimiter(0.5, clock=lambda: now["t"], sleep=sleep)
    limiter.wait()
    limiter.wait()
    now["t"] += 0.2
    limiter.wait()
    assert sleeps == [pytest.approx(0.5), pytest.approx(0.3)]


def test_cache_hits_do_not_wait_for_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", SECRET)
    slow = Source(name="slow", min_interval=10.0, key_param="key", key_env="TEST_API_KEY")
    now = {"t": 0.0}
    sleeps: list[float] = []

    def sleep(s):
        sleeps.append(s)
        now["t"] += s

    client = CachedClient(
        slow,
        raw_dir=tmp_path,
        transport=httpx.MockTransport(Recorder()),
        sleep=sleep,
        clock=lambda: now["t"],
    )
    for _ in range(5):
        client.get(URL, params={"t": "1"})
    assert sum(sleeps) == 0


def test_known_sources_registered():
    assert _http.SOURCES["census"].key_param == "key"
    assert _http.SOURCES["bls"].key_location == "json"
    assert _http.SOURCES["bls"].key_param == "registrationkey"

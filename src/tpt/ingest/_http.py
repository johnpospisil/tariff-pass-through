"""Shared HTTP client: retries, per-source rate limiting, raw cache and fetch manifest.

Every ingest module fetches through `CachedClient`, so all raw responses land under
`data/raw/<source>/` and every network fetch is logged in the manifest.

- API keys are injected here (query param or JSON body, per `Source`), never by callers.
  They are excluded from cache keys, cache metadata, the manifest, error messages and the
  httpx request log, so cached data is identical with or without a key.
- Retries: 429, 5xx and transport errors, exponential backoff with jitter, honouring
  Retry-After. Other non-2xx statuses raise `HttpError` immediately.
- Cache: one `<hash>.bin` body plus `<hash>.meta.json` per request. 200 and 204 are
  cached; an optional `validate` callback can reject a 200 body (e.g. a BLS
  "REQUEST_NOT_PROCESSED") so it is not cached.
- Manifest: each network fetch appends a line to `manifest.jsonl` (cheap and crash-safe
  over thousands of calls). `compact_manifest()` resolves it into `manifest.parquet`
  with one row per fetch: source, url, params, retrieved_at, sha256, bytes, rows.
"""

import hashlib
import json
import logging
import os
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
import polars as pl
from tenacity import RetryCallState, Retrying, retry_if_exception, stop_after_attempt

from tpt import config

log = logging.getLogger("tpt.http")

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
CACHE_STATUSES = frozenset({200, 204})
MAX_WAIT = 120.0

MANIFEST_SCHEMA = {
    "source": pl.String,
    "cache_key": pl.String,
    "method": pl.String,
    "url": pl.String,
    "params": pl.String,
    "status": pl.Int64,
    "retrieved_at": pl.String,
    "sha256": pl.String,
    "bytes": pl.Int64,
    "rows": pl.Int64,
}


@dataclass(frozen=True)
class Source:
    name: str
    min_interval: float  # seconds between network requests
    key_param: str | None = None
    key_env: str | None = None
    key_location: Literal["query", "json"] = "query"
    user_agent_env: str | None = None  # env var with a contact email, for hosts that require one

    def api_key(self) -> str | None:
        if self.key_env is None:
            return None
        return os.environ.get(self.key_env, "").strip() or None

    def headers(self) -> dict[str, str]:
        if self.user_agent_env is None:
            return {}
        contact = os.environ.get(self.user_agent_env, "").strip()
        if not contact:
            raise RuntimeError(
                f"{self.name} requires a contact email: set {self.user_agent_env} in .env"
            )
        return {"User-Agent": f"tariff-pass-through research ({contact})"}


SOURCES = {
    "census": Source("census", 0.2, key_param="key", key_env="CENSUS_API_KEY"),
    "bls": Source(
        "bls", 0.5, key_param="registrationkey", key_env="BLS_API_KEY", key_location="json"
    ),
    "fiscaldata": Source("fiscaldata", 0.2),
    "download": Source("download", 0.5),
    # download.bls.gov returns 403 unless the User-Agent carries a contact email.
    "blsdownload": Source("blsdownload", 1.0, user_agent_env="BLS_CONTACT_EMAIL"),
}


class HttpError(Exception):
    """Non-retryable or exhausted HTTP failure. Message carries the redacted URL only."""

    def __init__(self, status_code: int | None, url: str, detail: str = ""):
        self.status_code = status_code
        self.url = url
        super().__init__(f"HTTP {status_code} for {url}" + (f": {detail}" if detail else ""))


class _Retryable(Exception):
    def __init__(self, status_code: int | None, url: str, retry_after: float | None = None):
        self.status_code = status_code
        self.url = url
        self.retry_after = retry_after
        super().__init__(f"HTTP {status_code} for {url}")


# --- redaction ---------------------------------------------------------------

_secrets: set[str] = set()
_secrets_lock = threading.Lock()


def _redact(text: str) -> str:
    for secret in _secrets:
        text = text.replace(secret, "REDACTED")
    return text


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if _secrets:
            record.msg = _redact(record.getMessage())
            record.args = ()
        return True


# httpx logs full request URLs (keys included) at INFO.
logging.getLogger("httpx").addFilter(_RedactFilter())


def _register_secret(secret: str) -> None:
    with _secrets_lock:
        _secrets.add(secret)


# --- rate limiting -----------------------------------------------------------


class RateLimiter:
    """Enforce a minimum interval between calls to `wait()`. Thread-safe."""

    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last is not None:
                remaining = self.min_interval - (now - self._last)
                if remaining > 0:
                    self._sleep(remaining)
                    now = self._clock()
            self._last = now


# --- cache + manifest --------------------------------------------------------


@dataclass
class CachedResponse:
    content: bytes
    status_code: int
    from_cache: bool
    path: Path
    cache_key: str
    sha256: str
    source: str
    raw_dir: Path

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def json(self) -> Any:
        return json.loads(self.content)


_manifest_lock = threading.Lock()


def _append_manifest(raw_dir: Path, record: dict) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    with _manifest_lock, open(raw_dir / "manifest.jsonl", "a") as f:
        f.write(line)


def compact_manifest(raw_dir: Path = config.RAW_DIR) -> pl.DataFrame:
    """Resolve `manifest.jsonl` into `manifest.parquet` (one row per network fetch)."""
    path = raw_dir / "manifest.jsonl"
    events = []
    if path.exists():
        events = [json.loads(line) for line in path.read_text().splitlines() if line]
    fetches = [e for e in events if e["event"] == "fetch"]
    rows = {(e["cache_key"], e["sha256"]): e["rows"] for e in events if e["event"] == "rows"}
    records = [
        {k: f.get(k) for k in MANIFEST_SCHEMA} | {"rows": rows.get((f["cache_key"], f["sha256"]))}
        for f in fetches
    ]
    manifest = pl.DataFrame(records, schema=MANIFEST_SCHEMA)
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest.write_parquet(raw_dir / "manifest.parquet")
    return manifest


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


# --- client ------------------------------------------------------------------


def _wait_for(state: RetryCallState) -> float:
    exc = state.outcome.exception() if state.outcome else None
    backoff = min(MAX_WAIT, 2.0 ** (state.attempt_number - 1)) + random.uniform(0, 1)
    if isinstance(exc, _Retryable) and exc.retry_after is not None:
        return min(MAX_WAIT, max(backoff, exc.retry_after))
    return backoff


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None


class CachedClient:
    def __init__(
        self,
        source: str | Source,
        raw_dir: Path = config.RAW_DIR,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 120.0,
        max_attempts: int = 6,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.source = SOURCES[source] if isinstance(source, str) else source
        self.raw_dir = Path(raw_dir)
        self.max_attempts = max_attempts
        self._sleep = sleep
        self._limiter = RateLimiter(self.source.min_interval, clock=clock, sleep=sleep)
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
            headers=self.source.headers(),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CachedClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        refresh: bool = False,
        validate: Callable[[bytes], None] | None = None,
    ) -> CachedResponse:
        return self._fetch("GET", url, dict(params or {}), None, refresh, validate)

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        refresh: bool = False,
        validate: Callable[[bytes], None] | None = None,
    ) -> CachedResponse:
        return self._fetch("POST", url, {}, dict(payload), refresh, validate)

    def cached(self, url: str, params: dict[str, Any] | None = None) -> CachedResponse | None:
        """Return the cached GET response, or None, without touching the network."""
        key = self._cache_key("GET", url, dict(params or {}), None)
        return self._read_cache(key)

    def record_rows(self, response: CachedResponse, rows: int) -> None:
        """Attach a parsed row count to a fetch's manifest entry."""
        _append_manifest(
            self.raw_dir,
            {
                "event": "rows",
                "cache_key": response.cache_key,
                "sha256": response.sha256,
                "rows": rows,
            },
        )

    # internals

    def _cache_key(self, method: str, url: str, params: dict, body: dict | None) -> str:
        ident = json.dumps(
            {"method": method, "url": url, "params": params, "json": body},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(ident.encode()).hexdigest()

    def _paths(self, key: str) -> tuple[Path, Path]:
        base = self.raw_dir / self.source.name / key[:2]
        return base / f"{key}.bin", base / f"{key}.meta.json"

    def _read_cache(self, key: str) -> CachedResponse | None:
        body_path, meta_path = self._paths(key)
        if not (body_path.exists() and meta_path.exists()):
            return None
        meta = json.loads(meta_path.read_text())
        log.debug("cache hit %s %s", self.source.name, key[:12])
        return self._response(body_path.read_bytes(), meta["status"], True, body_path, key)

    def _fetch(
        self,
        method: str,
        url: str,
        params: dict,
        body: dict | None,
        refresh: bool,
        validate: Callable[[bytes], None] | None,
    ) -> CachedResponse:
        key = self._cache_key(method, url, params, body)
        body_path, meta_path = self._paths(key)

        if not refresh and (hit := self._read_cache(key)) is not None:
            return hit

        response = self._send(method, url, params, body)
        content = response.content
        if validate is not None:
            validate(content)

        sha = hashlib.sha256(content).hexdigest()
        retrieved_at = datetime.now(UTC).isoformat()
        logged_params = json.dumps(params if body is None else body, sort_keys=True, default=str)
        meta = {
            "source": self.source.name,
            "cache_key": key,
            "method": method,
            "url": url,
            "params": logged_params,
            "status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "retrieved_at": retrieved_at,
            "sha256": sha,
            "bytes": len(content),
        }
        _atomic_write(body_path, content)
        _atomic_write(meta_path, json.dumps(meta, indent=2).encode())
        _append_manifest(self.raw_dir, {"event": "fetch"} | meta)
        return self._response(content, response.status_code, False, body_path, key)

    def _response(
        self, content: bytes, status: int, from_cache: bool, path: Path, key: str
    ) -> CachedResponse:
        return CachedResponse(
            content=content,
            status_code=status,
            from_cache=from_cache,
            path=path,
            cache_key=key,
            sha256=hashlib.sha256(content).hexdigest(),
            source=self.source.name,
            raw_dir=self.raw_dir,
        )

    def _with_key(self, params: dict, body: dict | None) -> tuple[dict, dict | None]:
        key = self.source.api_key()
        if key is None or self.source.key_param is None:
            return params, body
        _register_secret(key)
        if self.source.key_location == "json":
            return params, (body or {}) | {self.source.key_param: key}
        return params | {self.source.key_param: key}, body

    def _send(self, method: str, url: str, params: dict, body: dict | None) -> httpx.Response:
        send_params, send_body = self._with_key(params, body)

        def attempt() -> httpx.Response:
            self._limiter.wait()
            try:
                response = self._client.request(method, url, params=send_params, json=send_body)
            except httpx.TransportError as exc:
                log.warning(
                    "%s transport error for %s: %s", self.source.name, url, type(exc).__name__
                )
                raise _Retryable(None, url) from None
            if response.status_code in RETRY_STATUSES:
                log.warning(
                    "%s HTTP %s for %s, retrying", self.source.name, response.status_code, url
                )
                raise _Retryable(response.status_code, url, _retry_after(response))
            if response.status_code not in CACHE_STATUSES:
                raise HttpError(response.status_code, url, _redact(response.text[:200]))
            return response

        retrying = Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=_wait_for,
            retry=retry_if_exception(lambda e: isinstance(e, _Retryable)),
            sleep=self._sleep,
            reraise=True,
        )
        try:
            return retrying(attempt)
        except _Retryable as exc:
            raise HttpError(exc.status_code, url, "retries exhausted") from None

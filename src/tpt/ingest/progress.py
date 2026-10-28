"""Progress file for long ingest runs, and a live terminal monitor for it.

An ingest writes `data/raw/<source>/_progress.json` after every chunk (atomic replace, so a
reader never sees a half-written file). Watch it from any terminal:

    make ingest-status                       # default: census
    uv run python -m tpt.ingest.progress bls

The ETA uses only chunks fetched from the network; cache hits are near-instant and would
make a resumed run look faster than it is.
"""

import contextlib
import json
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from tpt import config


def progress_path(source: str) -> Path:
    return config.RAW_DIR / source / "_progress.json"


@dataclass
class Snapshot:
    label: str
    total: int
    done: int
    cached: int
    failed: int
    rows: int
    started_at: float
    updated_at: float
    status: str  # running | finished

    @property
    def network_done(self) -> int:
        return self.done - self.cached

    def eta_seconds(self) -> float | None:
        if self.network_done <= 0:
            return None
        per_chunk = (self.updated_at - self.started_at) / self.network_done
        return per_chunk * (self.total - self.done)


class ProgressFile:
    """Thread-safe progress counter persisted to a JSON file."""

    def __init__(self, path: Path, label: str, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self._clock = clock
        self._lock = threading.Lock()
        self._snap = Snapshot(label, 0, 0, 0, 0, 0, clock(), clock(), "running")

    def start(self, total: int, label: str | None = None) -> None:
        """Begin (or restart, for a new stage) counting; resets all counters."""
        with self._lock:
            now = self._clock()
            label = label or self._snap.label
            self._snap = Snapshot(label, total, 0, 0, 0, 0, now, now, "running")
            self._write()

    def advance(self, rows: int = 0, cached: bool = False, failed: bool = False,
                steps: int = 1) -> None:  # fmt: skip
        with self._lock:
            s = self._snap
            s.done += steps
            s.rows += rows
            s.cached += cached
            s.failed += failed
            s.updated_at = self._clock()
            self._write()

    def finish(self) -> None:
        with self._lock:
            self._snap.status = "finished"
            self._snap.updated_at = self._clock()
            self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self._snap)))
        tmp.replace(self.path)


def read_snapshot(path: Path) -> Snapshot | None:
    try:
        return Snapshot(**json.loads(Path(path).read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "estimating…"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


def watch(path: Path, interval: float = 2.0) -> None:
    """Render a live progress bar for a progress file until its run finishes."""
    from rich.console import Console
    from rich.live import Live
    from rich.progress_bar import ProgressBar
    from rich.table import Table

    console = Console()

    def render(snap: Snapshot | None):
        if snap is None:
            return f"Waiting for {path} …"
        table = Table.grid(padding=(0, 2))
        table.add_row(
            f"[bold]{snap.label}[/]",
            ProgressBar(total=max(snap.total, 1), completed=snap.done, width=40),
            f"{snap.done:,}/{snap.total:,} ({snap.done / max(snap.total, 1):.1%})",
        )
        elapsed = snap.updated_at - snap.started_at
        rate = snap.network_done / elapsed * 60 if elapsed > 0 else 0
        failed = f"[red]{snap.failed:,} failed[/]" if snap.failed else "0 failed"
        table.add_row(
            "",
            f"rows {snap.rows:,} · cached {snap.cached:,} · {failed}",
            f"{rate:.1f} chunks/min",
        )
        status = "[green]finished[/]" if snap.status == "finished" else "running"
        table.add_row(
            "",
            f"elapsed {_fmt_duration(elapsed)} · ETA {_fmt_duration(snap.eta_seconds())}",
            status,
        )
        return table

    with Live(render(read_snapshot(path)), console=console, refresh_per_second=4) as live:
        while True:
            snap = read_snapshot(path)
            live.update(render(snap))
            if snap is not None and snap.status == "finished":
                break
            time.sleep(interval)


if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else "census"
    with contextlib.suppress(KeyboardInterrupt):
        watch(progress_path(source))

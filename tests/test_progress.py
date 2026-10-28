"""Tests for the ingest progress file and ETA maths."""

import json
import threading

import pytest

from tpt.ingest.progress import ProgressFile, Snapshot, read_snapshot


def test_start_advance_finish(tmp_path):
    path = tmp_path / "progress.json"
    prog = ProgressFile(path, label="census", clock=lambda: 100.0)
    prog.start(total=10)
    prog.advance(rows=50)
    prog.advance(rows=25, cached=True)
    prog.advance(failed=True)
    snap = read_snapshot(path)
    assert snap.total == 10
    assert snap.done == 3
    assert snap.cached == 1
    assert snap.failed == 1
    assert snap.rows == 75
    assert snap.status == "running"
    prog.finish()
    assert read_snapshot(path).status == "finished"


def test_file_is_valid_json_after_each_write(tmp_path):
    path = tmp_path / "progress.json"
    prog = ProgressFile(path, label="x")
    prog.start(total=3)
    for _ in range(3):
        prog.advance()
        json.loads(path.read_text())


def test_thread_safe_counts(tmp_path):
    path = tmp_path / "progress.json"
    prog = ProgressFile(path, label="x")
    prog.start(total=400)

    def work():
        for _ in range(100):
            prog.advance(rows=1)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    snap = read_snapshot(path)
    assert snap.done == 400
    assert snap.rows == 400


def test_eta_excludes_cache_hits():
    # 10 network chunks in 100 s -> 10 s each; 80 left -> 800 s.
    snap = Snapshot(
        label="x",
        total=100,
        done=20,
        cached=10,
        failed=0,
        rows=0,
        started_at=0.0,
        updated_at=100.0,
        status="running",
    )
    assert snap.network_done == 10
    assert snap.eta_seconds() == pytest.approx(800.0)


def test_eta_unknown_before_any_network_chunk():
    snap = Snapshot(
        label="x",
        total=10,
        done=3,
        cached=3,
        failed=0,
        rows=0,
        started_at=0.0,
        updated_at=5.0,
        status="running",
    )
    assert snap.eta_seconds() is None


def test_read_snapshot_missing_file(tmp_path):
    assert read_snapshot(tmp_path / "nope.json") is None


def test_restart_for_new_stage_resets_counts_and_label(tmp_path):
    path = tmp_path / "progress.json"
    prog = ProgressFile(path, label="totals")
    prog.start(total=2)
    prog.advance(rows=5)
    prog.start(total=10, label="hs10")
    snap = read_snapshot(path)
    assert (snap.label, snap.total, snap.done, snap.rows) == ("hs10", 10, 0, 0)

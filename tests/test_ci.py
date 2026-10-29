"""Monthly refresh helpers (P24): is there a Census month newer than the published data?"""

import polars as pl

from tpt.ci import new_month as nm


def test_latest_published_reads_effective_rates(tmp_path):
    p = tmp_path / "effective_rates.csv"
    pl.DataFrame({"month": ["2026-07-01", "2026-08-01"], "group": ["All", "All"]}).write_csv(p)
    assert nm.latest_published(p) == "2026-08"


def test_decide():
    assert nm.decide("2026-09", "2026-08") is True
    assert nm.decide("2026-08", "2026-08") is False
    assert nm.decide(None, "2026-08") is False  # API down: do not rebuild on a guess


def test_github_output(tmp_path):
    out = tmp_path / "gh_out"
    nm.write_output(out, new=True, available="2026-09", published="2026-08")
    assert out.read_text().splitlines() == ["new=true", "available=2026-09", "published=2026-08"]


def test_watch_bar_and_elapsed():
    from datetime import UTC, datetime

    from tpt.ci import watch

    assert watch.bar(8, 16, width=10) == "[#####-----] 8/16"
    now = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
    assert watch.minutes("2026-10-29T08:35:37Z", now) == "1h24m"

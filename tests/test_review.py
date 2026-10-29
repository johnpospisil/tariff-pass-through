"""Review packet tables (P25): built from data/published and the cited timeline."""

import polars as pl
import pytest

from tpt import config
from tpt.report import review as rv

ACTIONS = config.REFERENCE_DIR / "tariff_actions.csv"
BORDER = config.PUBLISHED_DIR / "border_pt.csv"


def test_timeline_table_lists_every_action_group_with_citations():
    t = pl.read_csv(ACTIONS, infer_schema_length=0)
    md = rv.timeline_md(t)
    for g in t["action_group"].unique():
        assert f"| {g} |" in md, g
    # every official URL in the timeline is linked from the packet
    for url in t["source_url"].unique():
        assert url in md, url


def test_estimates_table_matches_published_border_estimates():
    if not BORDER.exists():
        pytest.skip("border estimates not built")
    b = pl.read_csv(BORDER, infer_schema_length=0)
    rows = rv.border_rows(b)
    main = next(r for r in rows if r["period"] == "2025_26" and r["spec"] == "main"
                and r["outcome"] == "uv")  # fmt: skip
    want = b.filter(period="2025_26", spec="main", outcome="uv", group="all").row(0, named=True)
    assert main["coef"] == pytest.approx(float(want["coef"]))
    assert main["se"] == pytest.approx(float(want["se"]))
    assert {r["period"] for r in rows} == {"2018_19", "2025_26"}


def test_fmt_signs_and_rounding():
    assert rv.fmt(0.04123) == "+0.041" and rv.fmt(-0.7061) == "−0.706" and rv.fmt(None) == "–"

"""Report (P22): formatting, numbers from data/published only, no hard-coded figures in prose."""

import re

import polars as pl
import pytest

from tpt import config
from tpt.report import numbers as nm

QMD = config.REPORT_DIR / "index.qmd"


def test_formatting_uses_true_minus_and_no_signed_zero():
    assert nm.signed(-0.0412) == "−0.04"
    assert nm.signed(0.041) == "+0.04"
    assert nm.signed(-0.0009) == "0.00"
    assert nm.pct(-0.123, 1, sign=True) == "−12.3%"
    assert nm.bn(71.04) == "$71.0bn"


def test_md_table():
    t = nm.md_table(pl.DataFrame({"a": ["x"], "b": [1]}), ["A", "B"], "lr")
    assert t.splitlines() == ["| A | B |", "| :--- | ---: |", "| x | 1 |"]


def _prose(text: str) -> str:
    """index.qmd without YAML, code chunks, inline code, links, citations and table captions."""
    text = re.sub(r"\A---.*?\n---\n", "", text, flags=re.S)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    return text


def test_no_hard_coded_figures_in_prose():
    """Every result in the text comes from numbers(): no decimals, percentages or dollar
    amounts typed into the prose."""
    bad = re.findall(r"\d+\.\d+|\d+\s?%|\$\s?\d", _prose(QMD.read_text()))
    assert bad == []


@pytest.fixture(scope="module")
def numbers() -> dict:
    if not (config.PUBLISHED_DIR / "diversion.csv").exists():
        pytest.skip("published data not built")
    return nm.numbers()


def test_every_number_used_in_the_report_exists(numbers):
    used = set(re.findall(r'N\["([^"]+)"\]', QMD.read_text()))
    assert used, "no numbers referenced"
    assert used <= set(numbers), sorted(used - set(numbers))
    assert all(isinstance(v, str) and v for v in numbers.values())


def test_headline_numbers(numbers):
    assert numbers["data_month"] == "August 2026"
    assert numbers["b25"] == "+0.04" and numbers["b18"] == "+0.17"
    assert int(numbers["buyer_lo"]) >= 90 and numbers["buyer_hi"] == "100"


def test_figures_have_light_dark_and_alt_text():
    md = nm.fig("hero_border_pt", "Hero")
    assert "hero_border_pt.png" in md and "hero_border_pt_dark.png" in md
    assert ".light-content" in md and ".dark-content" in md and 'fig-alt="' in md


def test_tables_render(numbers):
    tables = (nm.table_timeline, nm.table_border, nm.table_retail, nm.table_exposure,
              nm.table_diversion, nm.table_flags, nm.table_front_running,
              nm.table_legal)  # fmt: skip
    for fn in tables:
        t = fn()
        assert t.count("\n") >= 2 and t.startswith("| "), fn.__name__

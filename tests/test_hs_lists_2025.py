"""Tests for the 2025-26 HTSUS Chapter 99 list extractor (P09)."""

import pytest

from tpt.build import hs_lists_2025 as h25

VALID = h25.prefix_index(
    {"7606120000", "7605110000", "7604101000", "7601100000", "7616995160", "7609000000",
     "7608100000", "7607110000", "7216210000", "7215100000", "7214100000", "9403200082",
     "9403200075", "8708103010", "0805900100"}
)  # fmt: skip


@pytest.mark.parametrize(
    ("text", "codes"),
    [
        ("7606760576047601", ["7606", "7605", "7604", "7601"]),
        ("7616.99.5160760976087607", ["7616995160", "7609", "7608", "7607"]),
        # an 8-digit code followed by a heading: the 10-digit reading is not a real code
        ("7216.21.0072157214", ["72162100", "7215", "7214"]),
        ("9403.20.00829403.20.0075", ["9403200082", "9403200075"]),
        ("8708.10.30; 9403.20.00.", ["87081030", "94032000"]),
        ("(classifiable in subheading 0805.90.01)", ["08059001"]),
    ],
)
def test_codes_split_run_together_numbers(text, codes):
    found, unmatched = h25.note_codes(text, VALID)
    assert found == codes
    assert unmatched == []


def test_prose_numbers_and_chapter_99_are_ignored():
    text = "12:01 a.m. on April 6, 2026, 90 Fed. Reg. 44638, heading 9903.82.02 and 19 CFR 146.41"
    assert h25.note_codes(text, VALID) == ([], [])


def test_unresolvable_codes_reported_separately():
    found, unmatched = h25.note_codes("7606; 7699.99.99", VALID)
    assert found == ["7606"]
    assert unmatched == ["76999999"]


def test_block_between_markers():
    text = "x (a) start 7606 (b) end 7605"
    assert h25.block(text, "(a) start", "(b) end") == "(a) start 7606 "
    with pytest.raises(ValueError, match="marker"):
        h25.block(text, "(c) missing", "(b) end")


def test_country_rate_rows():
    text = (
        "Heading/\nSubheading\n"
        "Except ..., articles the product of Algeria, as provided for in subdivision (v) of\n"
        "U.S. note 2 to this subchapter......\n1/9903.02.03\n"
        "No change.The duty provided in the applicable subheading + 30%\n"
        "Except ..., articles the product of the Philippines, as provided for in note 2....\n"
        "9903.02.53\nNo changeThe duty provided in the applicable subheading + 19%\n"
    )
    rows = h25.country_rate_rows(text, r"9903\.02\.")
    assert rows == [("9903.02.03", "Algeria", 0.30), ("9903.02.53", "Philippines", 0.19)]

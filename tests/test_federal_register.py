"""Tests for the Federal Register helper (P08)."""

from tpt.ingest import federal_register as fr


def test_hts_codes_extracts_hts8_and_hts10_in_order_without_ch99():
    text = (
        "heading 9903.88.03 applies to 8471.30.01 and 8471.30.01; also 7208.10.15.00 "
        "(see 84 FR 43304) and 0101.21.00, but not 1234.56 or 2018.07.06.1"
    )
    assert fr.hts_codes(text) == ["84713001", "7208101500", "01012100"]
    assert fr.hts_codes(text, include_ch99=True)[0] == "99038803"

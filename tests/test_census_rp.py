"""Tests for the USMCA share from Census rate provisions (P10)."""

import json
from datetime import date

import pytest

from tpt.ingest import census_rp


def test_usmca_share_from_rate_provisions():
    content = json.dumps(
        [
            ["I_COMMODITY", "RP", "CON_VAL_MO", "CTY_CODE", "COMM_LVL", "time"],
            ["8703230190", "-", "1000", "1220", "HS10", "2025-06"],
            ["8703230190", "19", "600", "1220", "HS10", "2025-06"],
            ["8703230190", "18", "100", "1220", "HS10", "2025-06"],
            ["8703230190", "69", "300", "1220", "HS10", "2025-06"],
            ["7208100000", "-", "50", "1220", "HS10", "2025-06"],
            ["7208100000", "69", "50", "1220", "HS10", "2025-06"],
            ["0101210010", "-", "0", "1220", "HS10", "2025-06"],
        ]
    ).encode()
    df = census_rp.usmca_share(census_rp.parse(content)).sort("hs10")
    assert df["hs10"].to_list() == ["7208100000", "8703230190"]  # zero-value rows dropped
    assert df["usmca_share"].to_list() == pytest.approx([0.0, 0.7])
    assert df["month"][0] == date(2025, 6, 1)

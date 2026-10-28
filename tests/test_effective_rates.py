"""Monthly effective vs statutory tariff rates by partner (P13)."""

from datetime import date

import polars as pl
import pytest

from tpt.build import effective_rates as er

M = date(2025, 9, 1)


def test_series_by_group():
    df = pl.DataFrame({
        "cty_code": ["5700", "5700", "4280", "1220"],
        "month": [M] * 4,
        "con_val": [100.0, 300.0, 200.0, 400.0],
        "cal_dut": [40.0, 90.0, 20.0, 8.0],
        "mfn_dut": [2.0, 6.0, 4.0, 0.0],
        "rate_total": [0.40, 0.30, 0.15, 0.02],
    })  # fmt: skip
    groups = {"All countries": None, "China": {"5700"}, "EU": {"4280", "4279"}}
    out = er.series(df, groups).sort("group")
    china = out.filter(pl.col("group") == "China").row(0, named=True)
    assert china["imports_bn"] == pytest.approx(400e-9)
    assert china["effective_rate"] == pytest.approx(130 / 400)
    assert china["statutory_additional"] == pytest.approx((40 + 90) / 400)
    assert china["statutory_rate"] == pytest.approx((130 + 8) / 400)
    assert china["effective_additional"] == pytest.approx((130 - 8) / 400)
    total = out.filter(pl.col("group") == "All countries").row(0, named=True)
    assert total["effective_rate"] == pytest.approx(158 / 1000)
    assert out["group"].to_list() == ["All countries", "China", "EU"]  # Canada not a group here


def test_groups_cover_named_partners():
    groups = er.groups()
    assert list(groups) == ["All countries", *er.PARTNERS]
    assert len(groups["EU"]) == 27 and "4280" in groups["EU"]  # Germany
    assert groups["China"] == {"5700"} and groups["Vietnam"] == {"5520"}

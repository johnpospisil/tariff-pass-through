"""Low-value import estimates (HTS 9999.95) by origin group (P14)."""

from datetime import date

import polars as pl
import pytest

from tpt.build import low_value as lv


def test_series_splits_china_hk_from_rest():
    df = pl.DataFrame({
        "hs10": ["9999950000", "9999950000", "9999950000", "6110200010"],
        "cty_code": ["5700", "5820", "4280", "5700"],
        "month": [date(2025, 6, 1)] * 4,
        "con_val": [600.0, 50.0, 350.0, 9_000.0],
    })  # fmt: skip
    r = lv.series(df).row(0, named=True)
    assert r["china_hk_bn"] == pytest.approx(650e-9)
    assert r["rest_bn"] == pytest.approx(350e-9)
    assert r["total_bn"] == pytest.approx(1000e-9)
    assert r["share_of_imports"] == pytest.approx(1000 / 10_000)

"""Tests for MFN (column 1 general) rates (P10)."""

import polars as pl
import pytest

from tpt.build import mfn


@pytest.mark.parametrize(
    ("text", "rate"),
    [("Free", 0.0), ("2.5%", 0.025), ("25%", 0.25), ("4.4¢/kg", None), ("1.2¢/kg + 5%", None),
     ("", None), ("Free1/", 0.0), ("6.5%1/", 0.065)],
)  # fmt: skip
def test_parse_general(text, rate):
    assert mfn.parse_general(text) == (pytest.approx(rate) if rate is not None else None)


def test_hts8_rates_from_export_rows():
    rows = [
        {"htsno": "0101", "general": ""},
        {"htsno": "0101.21.00", "general": "Free"},
        {"htsno": "0101.21.00.10", "general": ""},
        {"htsno": "0201.10.05", "general": "4.4¢/kg"},
        {"htsno": "8703.23.01", "general": "2.5%"},
        {"htsno": "8471.30.01.00", "general": "Free"},  # rate on the 10-digit line
    ]
    df = mfn.hts8_rates(rows).sort("hs8")
    assert df.rows() == [("01012100", 0.0), ("02011005", None), ("84713001", 0.0),
                         ("87032301", 0.025)]  # fmt: skip


def test_assign_to_hs10_with_ave_and_fallbacks():
    hts8 = pl.DataFrame({"hs8": ["01012100", "02011005"], "general": [0.0, None]},
                        schema={"hs8": pl.String, "general": pl.Float64})  # fmt: skip
    ave = pl.DataFrame({"hs10": ["0201100500"], "ave": [0.03]})
    codes = ["0101210010", "0201100500", "0201100599", "0101290000"]
    fam = pl.DataFrame({"hs10": codes, "family": ["A", "B", "B", "A"]})
    out = dict(mfn.assign(codes, hts8, ave, fam).select("hs10", "mfn_rate").iter_rows())
    assert out["0101210010"] == 0.0
    assert out["0201100500"] == pytest.approx(0.03)  # specific rate: AVE from duties paid
    assert out["0201100599"] == pytest.approx(0.03)  # HS8 AVE
    assert out["0101290000"] == 0.0  # not in current HTS: family member's rate

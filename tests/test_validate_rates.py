"""Statutory vs implied (collected) additional duty rates (P11)."""

from datetime import date

import polars as pl
import pytest

from tpt.build import validate_rates as vr

M = date(2025, 9, 1)


def frame(**cols) -> pl.DataFrame:
    base = {"hs10": ["6110200010"], "cty_code": ["5700"], "month": [M], "con_val": [100.0],
            "dut_val": [100.0], "cal_dut": [0.0], "mfn_rate": [0.0], "rate_total": [0.0],
            "rate_s232": [0.0], "rate_metal_content": [0.0], "rate_s301": [0.0],
            "rate_s201": [0.0], "rate_total_prev": [0.0], "rate_total_prev2": [0.0]}  # fmt: skip
    base.update({k: v if isinstance(v, list) else [v] for k, v in cols.items()})
    n = max(len(v) for v in base.values())
    return pl.DataFrame({k: v * n if len(v) == 1 else v for k, v in base.items()})


NO_REF = pl.DataFrame(schema={"hs10": pl.String, "cty_code": pl.String, "ref_year": pl.Int32,
                              "ref_share": pl.Float64})  # fmt: skip


def test_implied_subtracts_mfn_on_dutiable_value():
    # $100, MFN 16.5% on all of it, plus a 20% additional duty: $36.5 assessed
    out = vr.implied(frame(cal_dut=36.5, mfn_rate=0.165, rate_total=0.20), NO_REF)
    assert out["impl_add"][0] == pytest.approx(0.20)
    assert out["gap_dut"][0] == pytest.approx(0.0)


def test_mfn_base_capped_by_reference_share():
    # USMCA pickup: MFN 25% but MFN-free under USMCA (2024 dutiable share 0); the 2025 Section 232
    # duty (25% on the 55% non-US content) makes it dutiable. Without the cap implied would be < 0.
    ref = pl.DataFrame({"hs10": ["8704310140"], "cty_code": ["2010"], "ref_year": [2024],
                        "ref_share": [0.0]}, schema_overrides={"ref_year": pl.Int32})  # fmt: skip
    df = frame(hs10="8704310140", cty_code="2010", dut_val=55.0, cal_dut=13.75, mfn_rate=0.25,
               rate_total=0.1375)  # fmt: skip
    out = vr.implied(df, ref)
    assert out["impl_add"][0] == pytest.approx(0.1375)
    assert vr.implied(df, NO_REF)["impl_add"][0] == pytest.approx((13.75 - 0.25 * 55) / 100)


def test_ref_shares_by_reference_year():
    df = frame(month=[date(2017, 3, 1), date(2017, 4, 1), date(2024, 5, 1)],
               con_val=[100.0, 100.0, 50.0], dut_val=[100.0, 0.0, 10.0])  # fmt: skip
    ref = vr.ref_shares(df).sort("ref_year")
    assert ref["ref_share"].to_list() == pytest.approx([0.5, 0.2])
    assert ref["ref_year"].to_list() == [2017, 2024]


@pytest.mark.parametrize(
    ("cols", "category"),
    [
        ({"hs10": "9999950000", "rate_total": 0.2}, "not_comparable"),
        ({"hs10": "9801001066", "cty_code": "1220"}, "not_comparable"),
        ({"hs10": "2711210000", "cty_code": "1220"}, "not_comparable"),
        ({"hs10": "2711210000", "cty_code": "5700"}, "other"),
        ({"rate_metal_content": 0.3, "rate_total": 0.5}, "metal_content"),
        ({"rate_total": 0.3, "rate_total_prev": 0.1}, "in_transit"),
        ({"rate_total": 0.3, "rate_total_prev": 0.3, "rate_total_prev2": 0.1}, "in_transit"),
        # no in-transit exemption in force after 2025-10-05
        ({"rate_total": 0.3, "rate_total_prev": 0.1, "month": date(2025, 11, 1)}, "other"),
        ({"cty_code": "2010", "rate_total": 0.1, "rate_total_prev": 0.1, "rate_total_prev2": 0.1},
         "usmca"),
        ({"rate_s201": 0.14, "cty_code": "5520"}, "s201"),
        ({"hs10": "9021390000", "cty_code": "4190"}, "medical"),
        ({"hs10": "8411124000", "cty_code": "4279"}, "aircraft"),
        ({"hs10": "7108135500", "cty_code": "4419"}, "precious_metals"),
        ({"hs10": "7108135500", "cty_code": "4419", "month": date(2024, 5, 1)}, "other"),
        ({"rate_s301": 0.25, "rate_total": 0.25, "rate_total_prev": 0.25,
          "rate_total_prev2": 0.25}, "s301_china"),
    ],
)  # fmt: skip
def test_categories(cols, category):
    assert vr.categorize(frame(**cols))["category"][0] == category


def test_metrics_and_bridge():
    df = frame(hs10=["a", "b", "9999950000"], con_val=[100.0, 300.0, 50.0],
               rate_total=[0.10, 0.20, 0.20], cal_dut=[10.0, 30.0, 0.0])  # fmt: skip
    df = vr.categorize(vr.implied(df, NO_REF))
    m = vr.metrics(df).filter(pl.col("period") == "2025-26")
    # comparable pairs only: a matches; b has 20% statutory vs 10% implied (> 5 pp) on 300 of 400
    assert m["share_value_gt_5pp"][0] == pytest.approx(0.75)
    assert m["statutory"][0] == pytest.approx((10 + 60) / 400)
    assert m["implied"][0] == pytest.approx(40 / 400)
    b = vr.bridge(df)
    assert b["gap"][0] == pytest.approx((70 + 10 - 40) / 450)
    # category gaps add up to the total gap
    cats = sum(b[f"gap_{c}"][0] for c in vr.CATEGORIES)
    assert cats == pytest.approx(b["gap"][0])
    assert b["gap_not_comparable"][0] == pytest.approx(10 / 450)


def test_top_pairs_ranks_by_absolute_gap():
    df = frame(hs10=["a", "b", "c"], con_val=[100.0, 100.0, 100.0],
               rate_total=[0.10, 0.0, 0.30], cal_dut=[10.0, 25.0, 0.0])  # fmt: skip
    top = vr.top_pairs(vr.categorize(vr.implied(df, NO_REF)), date(2025, 1, 1), n=2)
    assert top["hs10"].to_list() == ["c", "b"]  # $30 over, then $25 under (a missing action)
    assert top["gap_bn"].to_list() == pytest.approx([30e-9, -25e-9])

"""HS10-family x country x month import panel (P12): hand-worked cases."""

from datetime import date

import polars as pl
import pytest

from tpt.build import import_panel as ip


def months(*ym: str) -> list[date]:
    return [date.fromisoformat(m + "-01") for m in ym]


def rows(**cols) -> pl.DataFrame:
    """HS10 x country x month inputs, as ip.build expects them."""
    base = {"hs10": ["6110200010"], "cty_code": ["5700"], "month": months("2024-03"),
            "con_val": [100.0], "cal_dut": [0.0], "dut_val": [0.0], "qty": [10.0],
            "unit": ["DOZ"], "rate_total": [0.0], "mfn_rate": [0.0]}  # fmt: skip
    base.update(cols)
    n = max(len(v) for v in base.values())
    return pl.DataFrame({k: v * n if len(v) == 1 else v for k, v in base.items()})


FAM = pl.DataFrame({"hs10": ["6110200010", "6110200020", "6110209999", "8471300100"],
                    "family": ["F1", "F1", "F1", "8471300100"]})  # fmt: skip
CODES = pl.DataFrame({
    "year": [2023, 2023, 2024, 2024, 2023, 2024],
    "hs10": ["6110200010", "6110200020", "6110200010", "6110200020", "8471300100", "8471300100"],
})  # fmt: skip


def test_twelve_month_changes_at_hs10_when_family_unchanged():
    df = rows(month=months("2023-03", "2024-03"), con_val=[100.0, 132.0], qty=[10.0, 12.0],
              cal_dut=[0.0, 33.0], rate_total=[0.0, 0.25])  # fmt: skip
    out = ip.build(df, FAM, CODES).filter(pl.col("month") == date(2024, 3, 1))
    r = out.row(0, named=True)
    assert (r["prod_id"], r["level"]) == ("6110200010", "hs10")
    assert r["unit_value"] == pytest.approx(11.0)
    assert r["dln_uv"] == pytest.approx(0.0953101798)  # ln(11/10)
    assert r["eff_rate"] == pytest.approx(0.25)
    assert r["uv_duty_incl"] == pytest.approx(11.0 * 1.25)
    assert r["dln_1p_tau_stat"] == pytest.approx(0.2231435513)  # ln(1.25) - ln(1)
    assert r["dln_1p_tau_eff"] == pytest.approx(0.2231435513)
    assert r["dln_qty"] == pytest.approx(0.1823215568)  # ln(12/10)
    assert r["drop_reason"] is None


def test_family_level_when_codes_change():
    # 2025: 6110200010 and ...20 replaced by 6110209999; compare the family aggregates
    codes = pl.concat([CODES, pl.DataFrame({"year": [2025], "hs10": ["6110209999"]})])
    df = rows(hs10=["6110200010", "6110200020", "6110209999"],
              month=months("2024-03", "2024-03", "2025-03"),
              con_val=[60.0, 40.0, 150.0], qty=[6.0, 4.0, 10.0],
              rate_total=[0.0, 0.10, 0.20])  # fmt: skip
    out = ip.build(df, FAM, codes)
    r = out.filter(pl.col("month") == date(2025, 3, 1)).row(0, named=True)
    assert (r["prod_id"], r["level"]) == ("F1", "family")
    assert r["dln_uv"] == pytest.approx(0.4054651081)  # ln(15/10)
    # statutory rate of the 2024 family aggregate is value-weighted: 0.4 x 10% = 4%
    assert r["dln_1p_tau_stat"] == pytest.approx(0.1823215568 - 0.0392207132)
    assert out.filter(pl.col("month") == date(2024, 3, 1)).height == 2  # 2024 stays HS10


def test_unit_change_and_missing_quantity_are_dropped_with_reasons():
    df = rows(hs10=["6110200010"] * 2 + ["8471300100"] * 2,
              month=months("2023-03", "2024-03", "2023-03", "2024-03"),
              unit=["DOZ", "NO", "NO", "NO"], qty=[10.0, 10.0, 5.0, 0.0])  # fmt: skip
    out = ip.build(df, FAM, CODES).filter(pl.col("month") == date(2024, 3, 1)).sort("prod_id")
    assert out["drop_reason"].to_list() == ["unit_change", "no_quantity"]
    assert out["dln_uv"].is_null().all()
    assert out["dln_val"].to_list() == pytest.approx([0.0, 0.0])  # value changes still usable


def test_special_provisions_and_mixed_units():
    codes = pl.concat([CODES, pl.DataFrame({"year": [2025], "hs10": ["6110209999"]})])
    df = rows(hs10=["9801001066", "6110200010", "6110200020", "6110209999"],
              month=months("2024-03", "2024-03", "2024-03", "2025-03"),
              unit=["X", "DOZ", "NO", "DOZ"])  # fmt: skip
    out = ip.build(df, FAM, codes)
    reasons = dict(
        zip(out["prod_id"] + "/" + out["month"].cast(str), out["drop_reason"], strict=True)
    )
    assert reasons["9801001066/2024-03-01"] == "special_provision"
    assert reasons["F1/2025-03-01"] == "mixed_units"  # 2024 family aggregate mixes DOZ and NO


def test_no_change_without_a_trade_twelve_months_earlier():
    df = rows(month=months("2023-02", "2024-03"))
    out = ip.build(df, FAM, CODES).filter(pl.col("month") == date(2024, 3, 1))
    assert out["dln_uv"][0] is None
    assert out["drop_reason"][0] == "no_base"


def test_winsorise_and_trim():
    x = pl.DataFrame({"dln_uv": [float(i) for i in range(101)], "drop_reason": [None] * 101},
                     schema_overrides={"drop_reason": pl.String})  # fmt: skip
    w = ip.winsorise(x, ip.Cleaning(winsor=(0.05, 0.95)), cols=["dln_uv"])
    assert (w["dln_uv"].min(), w["dln_uv"].max()) == (5.0, 95.0)
    t = ip.winsorise(x, ip.Cleaning(winsor=(0.05, 0.95), mode="trim"), cols=["dln_uv"])
    assert t.filter(pl.col("drop_reason") == "trimmed").height == 10


def test_drop_report_shares():
    out = pl.DataFrame({"month": months("2024-03", "2024-03", "2024-03"),
                        "con_val": [50.0, 30.0, 20.0],
                        "drop_reason": [None, "unit_change", "no_base"]})  # fmt: skip
    rep = ip.drop_report(out).sort("drop_reason", nulls_last=True)
    assert rep["value_share"].to_list() == pytest.approx([0.2, 0.3, 0.5])
    assert rep["drop_reason"].to_list() == ["no_base", "unit_change", None]


def test_duty_outliers_flagged():
    # over-quota tobacco: $2,519 of value, $25,000 of duty (specific rate on a tiny shipment)
    df = rows(hs10=["2403999070"], month=months("2023-03", "2024-03"), cal_dut=[0.0, 25_000.0],
              con_val=[2519.0, 2519.0])  # fmt: skip
    r = ip.build(df, FAM, CODES).filter(pl.col("month") == date(2024, 3, 1)).row(0, named=True)
    assert r["drop_reason"] == "duty_outlier"
    assert r["eff_rate"] is None and r["dln_uv"] is None and r["dln_1p_tau_eff"] is None

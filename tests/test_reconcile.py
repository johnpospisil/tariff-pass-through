"""Reconciliation gates (P04).

Unit tests run on small constructed frames. The gate tests run against the real data and are
skipped until `make ingest` and `make reconcile` have produced it.
"""

from datetime import date

import polars as pl
import pytest

from tpt import config
from tpt.build import reconcile as rc
from tpt.ingest import ft900, treasury_mts

# --- FT-900 country file -----------------------------------------------------


def _wide(year: str, code: str, name: str, imports: list[float]) -> dict:
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    row = {"year": year, "CTY_CODE": code, "CTYNAME": name}
    row |= {f"I{m}": v for m, v in zip(months, imports, strict=True)}
    row |= {f"E{m}": 1.0 for m in months}
    row["IYR"] = sum(imports)
    row["EYR"] = 12.0
    return row


def test_tidy_country_table_long_and_in_dollars():
    wide = pl.DataFrame([_wide("2025", "5700", "China", [float(i) for i in range(1, 13)])])
    long = ft900.tidy_country_table(wide)
    assert long.height == 12
    first = long.sort("month").row(0, named=True)
    assert first["month"] == date(2025, 1, 1)
    assert first["cty_code"] == "5700"
    assert first["imports_usd"] == pytest.approx(1e6)


def test_tidy_country_table_drops_unreleased_months():
    vals = [5.0] * 8 + [0.0] * 4  # Sep-Dec not yet released
    wide = pl.DataFrame([_wide("2026", ft900.WORLD_NSA, "World, NSA", vals)])
    long = ft900.tidy_country_table(wide)
    assert long["month"].max() == date(2026, 8, 1)


# --- Treasury MTS ------------------------------------------------------------


def test_parse_mts_customs_rows():
    payload = {
        "data": [
            {
                "record_date": "2025-06-30",
                "classification_desc": "Customs Duties",
                "current_month_gross_rcpt_amt": "27154576587.18",
                "current_month_refund_amt": "522912355.41",
                "current_month_net_rcpt_amt": "26631664231.77",
            },
            {
                "record_date": "2025-06-30",
                "classification_desc": "Estate and Gift Taxes",
                "current_month_gross_rcpt_amt": "1",
                "current_month_refund_amt": "0",
                "current_month_net_rcpt_amt": "1",
            },
        ]
    }
    df = treasury_mts.parse_customs(payload)
    assert df.height == 1
    row = df.row(0, named=True)
    assert row["month"] == date(2025, 6, 1)
    assert row["mts_gross_usd"] == pytest.approx(27_154_576_587.18)
    assert row["mts_refund_usd"] == pytest.approx(522_912_355.41)
    assert row["mts_net_usd"] == pytest.approx(26_631_664_231.77)


# --- gate maths --------------------------------------------------------------


def _months(n: int) -> list[date]:
    return [date(2025, m, 1) for m in range(1, n + 1)]


def test_ft900_gate_flags_months_outside_tolerance():
    census = pl.DataFrame({"month": _months(3), "gen_val_mo": [100.0, 100.0, 100.0]})
    ft = pl.DataFrame({"month": _months(3), "ft900_imports_usd": [100.0, 100.4, 101.0]})
    out = rc.ft900_gate(census, ft, tolerance=0.005)
    assert out["pass"].to_list() == [True, True, False]
    assert out["gap_pct"][2] == pytest.approx(-0.990, abs=1e-3)


def test_ft900_gate_flags_missing_months():
    census = pl.DataFrame({"month": _months(2), "gen_val_mo": [100.0, 100.0]})
    ft = pl.DataFrame({"month": _months(1), "ft900_imports_usd": [100.0]})
    out = rc.ft900_gate(census, ft)
    assert out.filter(pl.col("month") == date(2025, 2, 1))["pass"].item() is False


def test_treasury_comparison_lags_receipts_one_month(monkeypatch):
    monkeypatch.setattr(rc, "TREASURY_BASELINE", (date(2025, 1, 1), date(2025, 12, 1)))
    census = pl.DataFrame({"month": _months(5), "cal_dut_mo": [10.0, 10.0, 10.0, 10.0, 20.0]})
    # Receipts arrive a month after assessment and are 25% higher than assessed duties.
    mts = pl.DataFrame(
        {
            "month": _months(6),
            "mts_gross_usd": [99.0, 12.5, 12.5, 12.5, 12.5, 25.0],
            "mts_refund_usd": [0.0] * 6,
            "mts_net_usd": [99.0, 12.5, 12.5, 12.5, 12.5, 25.0],
        }
    )
    out = rc.treasury_comparison(census, mts).sort("month")
    assert out["mts_gross_usd"].to_list() == [12.5, 12.5, 12.5, 12.5, 25.0]
    assert out["gap_gross_pct"][0] == pytest.approx(-20.0)
    assert out["ratio_3m"][1] is None  # needs 3 months
    assert out["ratio_3m"][2] == pytest.approx(0.8)
    assert out["ratio_dev_pct"].drop_nulls().to_list() == pytest.approx([0.0, 0.0, 0.0])


# --- gates on real data ------------------------------------------------------

needs_data = pytest.mark.skipif(
    not (rc.FT900_REPORT.exists() and rc.TREASURY_REPORT.exists()),
    reason="run `make ingest` and `make reconcile` first",
)


@needs_data
def test_gate1_census_totals_match_ft900_every_month():
    report = pl.read_csv(rc.FT900_REPORT, try_parse_dates=True)
    failing = report.filter(~pl.col("pass"))
    assert failing.height == 0, f"FT-900 gate failed:\n{failing}"
    assert report["month"].min() <= config.SAMPLE_START


@needs_data
def test_gate2_duties_track_treasury_customs_receipts():
    report = pl.read_csv(rc.TREASURY_REPORT, try_parse_dates=True)
    bad = report.filter(pl.col("ratio_dev_pct").abs() > rc.TREASURY_TOLERANCE * 100)
    explained = bad.filter(pl.col("month").is_in(rc.TREASURY_EXPLAINED_MONTHS))
    unexplained = bad.filter(~pl.col("month").is_in(rc.TREASURY_EXPLAINED_MONTHS))
    assert unexplained.height == 0, f"Unexplained Treasury gaps:\n{unexplained}"
    assert explained.height == bad.height
    assert report["ratio_dev_pct"].drop_nulls().len() >= report.height - 3

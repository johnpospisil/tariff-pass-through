"""Hand-worked cases for the HS10 x country x month rate expansion (P10)."""

import csv
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from tpt.build import tariff_rates as tr
from tpt.build import tariff_timeline as tt

CN, CA, DE, MX = "5700", "1220", "4280", "2010"
LIST3_GOOD, STEEL, CAR = "8471500150", "7208100000", "8703230190"
CHIP, OTHER = "8473301180", "6110200010"
NO_MFN = pl.DataFrame(
    {"hs10": [], "mfn_rate": []}, schema={"hs10": pl.String, "mfn_rate": pl.Float64}
)


def act(action_id, authority, cty, scope, rate, start, end="", **kw) -> dict:
    base = {
        "action_id": action_id, "action_group": kw.pop("group", action_id), "authority": authority,
        "country_iso": kw.pop("iso", "XX" if cty != "ALL" else "ALL"), "cty_code": cty,
        "hs_scope": scope, "rate_type": "ad_valorem", "rate": str(rate), "effective_date": start,
        "end_date": end, "stacking": "cumulative", "legal_status": "in_effect",
        "source_type": "federal_register", "source_citation": "test",
        "source_url": "https://www.federalregister.gov/d/x", "verified_on": "2026-10-28",
    }  # fmt: skip
    base.update(kw)
    return {c: base.get(c, "") for c in tt.COLUMNS}


def load(tmp_path: Path, rows: list[dict]) -> list[tt.TariffAction]:
    path = tmp_path / "actions.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=tt.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return tt.load_actions(path)


def keys(*items: tuple[str, str, str]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "hs10": [i[0] for i in items],
            "cty_code": [i[1] for i in items],
            "month": [date.fromisoformat(i[2] + "-01") for i in items],
        }  # fmt: skip
    )


def rates(tmp_path, rows, k, mfn=None, usmca=None, groups=None) -> pl.DataFrame:
    out = tr.expand(
        load(tmp_path, rows), k, base_dir=tmp_path, groups=groups or {},
        mfn=mfn if mfn is not None else NO_MFN,
        usmca_share=usmca,
    )  # fmt: skip
    return out.sort("hs10", "cty_code", "month")


def value(df, hs10, cty, month, col="rate_total") -> float:
    m = date.fromisoformat(month + "-01")
    sel = df.filter((pl.col("hs10") == hs10) & (pl.col("cty_code") == cty) & (pl.col("month") == m))
    assert sel.height == 1, sel
    return sel[col][0]


def test_china_list3_plus_fentanyl_and_reciprocal(tmp_path):
    rows = [
        act("L3", "S301", CN, "84715001", 0.25, "2019-05-10", iso="CN"),
        act("F10", "IEEPA_FENTANYL", CN, "ALL", 0.10, "2025-02-04", "2025-03-04", iso="CN"),
        act("F20", "IEEPA_FENTANYL", CN, "ALL", 0.20, "2025-03-04", iso="CN"),
        act("RB", "IEEPA_RECIPROCAL", "ALL", "ALL", 0.10, "2025-04-05", stacking="not_with:S232"),
        act("R84", "IEEPA_RECIPROCAL", CN, "ALL", 0.84, "2025-04-09", "2025-04-10", iso="CN",
            supersedes="RB"),
        act("R125", "IEEPA_RECIPROCAL", CN, "ALL", 1.25, "2025-04-10", "2025-05-14", iso="CN",
            supersedes="RB"),
    ]  # fmt: skip
    months = ("2025-01", "2025-02", "2025-03", "2025-04", "2025-05")
    k = keys(*[(LIST3_GOOD, CN, m) for m in months])
    df = rates(tmp_path, rows, k)
    assert value(df, LIST3_GOOD, CN, "2025-01") == pytest.approx(0.25)
    # Feb: fentanyl 10% from the 4th: 25 of 28 days
    fent = "rate_ieepa_fentanyl"
    assert value(df, LIST3_GOOD, CN, "2025-02", fent) == pytest.approx(0.10 * 25 / 28)
    # Mar: 3 days at 10%, 28 at 20%
    assert value(df, LIST3_GOOD, CN, "2025-03", "rate_ieepa_fentanyl") == pytest.approx(
        (3 * 0.10 + 28 * 0.20) / 31
    )
    # Apr: baseline 10% on the 5th-8th, 84% on the 9th, 125% from the 10th
    assert value(df, LIST3_GOOD, CN, "2025-04", "rate_ieepa_reciprocal") == pytest.approx(
        (4 * 0.10 + 1 * 0.84 + 21 * 1.25) / 30
    )
    # May: 125% to the 13th, then the 10% baseline
    assert value(df, LIST3_GOOD, CN, "2025-05", "rate_ieepa_reciprocal") == pytest.approx(
        (13 * 1.25 + 18 * 0.10) / 31
    )
    assert value(df, LIST3_GOOD, CN, "2025-05") == pytest.approx(
        0.25 + 0.20 + (13 * 1.25 + 18 * 0.10) / 31)  # fmt: skip


def test_usmca_qualifying_share_is_exempt(tmp_path):
    rows = [act("FCA", "IEEPA_FENTANYL", CA, "ALL", 0.25, "2025-03-07", iso="CA", usmca="exempt")]
    k = keys((OTHER, CA, "2025-04"), (STEEL, CA, "2025-04"))
    share = pl.DataFrame({"hs10": [OTHER, STEEL], "cty_code": [CA, CA],
                          "month": [date(2025, 4, 1)] * 2, "usmca_share": [0.8, 0.0]})  # fmt: skip
    df = rates(tmp_path, rows, k, usmca=share)
    assert value(df, OTHER, CA, "2025-04") == pytest.approx(0.25 * 0.2)
    assert value(df, STEEL, CA, "2025-04") == pytest.approx(0.25)  # no USMCA claims


def test_usmca_vehicles_pay_on_non_us_content(tmp_path):
    rows = [act("AUT", "S232", "ALL", "8703", 0.25, "2025-04-03", usmca="non_us_content")]
    k = keys((CAR, MX, "2025-05"), (CAR, DE, "2025-05"))
    share = pl.DataFrame({"hs10": [CAR], "cty_code": [MX], "month": [date(2025, 5, 1)],
                          "usmca_share": [0.6]})  # fmt: skip
    df = rates(tmp_path, rows, k, usmca=share)
    # the US-content line is entered duty-free (rate provision 19), so it is in the share
    assert value(df, CAR, MX, "2025-05") == pytest.approx(0.25 * (1 - 0.6))
    assert value(df, CAR, DE, "2025-05") == pytest.approx(0.25)  # USMCA rule only for CA, MX


def test_section_232_replaces_reciprocal(tmp_path):
    rows = [
        act("ST", "S232", "ALL", "7208", 0.50, "2025-06-04"),
        act("EU", "IEEPA_RECIPROCAL", DE, "ALL", 0.15, "2025-08-07", rate_type="all_in_floor",
            stacking="not_with:S232", iso="DE"),
    ]  # fmt: skip
    k = keys((STEEL, DE, "2025-09"), (OTHER, DE, "2025-09"), (CAR, DE, "2025-09"))
    mfn = pl.DataFrame({"hs10": [STEEL, OTHER, CAR], "mfn_rate": [0.0, 0.04, 0.20]})
    df = rates(tmp_path, rows, k, mfn=mfn)
    assert value(df, STEEL, DE, "2025-09", "rate_s232") == pytest.approx(0.50)
    assert value(df, STEEL, DE, "2025-09", "rate_ieepa_reciprocal") == 0
    assert value(df, OTHER, DE, "2025-09") == pytest.approx(0.11)  # 15% all-in less 4% MFN
    assert value(df, CAR, DE, "2025-09") == 0  # MFN above the floor


def test_mid_month_effective_date_with_supersedes(tmp_path):
    rows = [
        act("S25", "S232", "ALL", "7208", 0.25, "2025-03-12", "2025-06-04"),
        act("S50", "S232", "ALL", "7208", 0.50, "2025-06-04", supersedes="S25"),
    ]
    k = keys((STEEL, DE, "2025-03"), (STEEL, DE, "2025-06"))
    df = rates(tmp_path, rows, k)
    assert value(df, STEEL, DE, "2025-03") == pytest.approx(0.25 * 20 / 31)
    assert value(df, STEEL, DE, "2025-06") == pytest.approx((3 * 0.25 + 27 * 0.50) / 30)


def test_supersedes_wins_while_both_active(tmp_path):
    rows = [
        act("BASE", "IEEPA_RECIPROCAL", "ALL", "ALL", 0.10, "2025-04-05"),
        act("AG", "IEEPA_RECIPROCAL", "ALL", "6110", 0.0, "2025-11-13", supersedes="BASE"),
    ]
    k = keys((OTHER, DE, "2025-12"))
    assert value(rates(tmp_path, rows, k), OTHER, DE, "2025-12") == 0


def test_action_group_stacking_and_unidentified_subset(tmp_path):
    rows = [
        act("AUTOS", "S232", "ALL", "8473", 0.25, "2025-05-03", group="S232-AUTOS"),
        act("STD", "S232", "ALL", "8473", 0.50, "2025-06-04", group="S232-STEELDER",
            stacking="not_with:S232-AUTOS", value_basis="metal_content"),
        act("SEMI", "S232", "ALL", "847330", 0.25, "2026-01-15", group="S232-SEMI",
            value_basis="unidentified_subset"),
        act("RB", "IEEPA_RECIPROCAL", "ALL", "ALL", 0.10, "2025-04-05", "2026-02-24",
            stacking="not_with:S232"),
    ]  # fmt: skip
    k = keys((CHIP, DE, "2026-02"))
    df = rates(tmp_path, rows, k)
    assert value(df, CHIP, DE, "2026-02", "rate_s232") == pytest.approx(0.25)  # autos only
    assert value(df, CHIP, DE, "2026-02", "rate_metal_content") == 0
    assert value(df, CHIP, DE, "2026-02", "rate_unidentified") == pytest.approx(0.25)
    assert value(df, CHIP, DE, "2026-02", "rate_ieepa_reciprocal") == 0  # S232 goods
    assert value(df, CHIP, DE, "2026-02") == pytest.approx(0.25)  # subset duty not in total


def test_country_groups_and_exclusions(tmp_path):
    rows = [act("ST", "S232", "ALL", "7208", 0.25, "2018-03-23", exclude_cty_codes="EU", iso="ALL")]
    k = keys((STEEL, DE, "2018-03"), (STEEL, CN, "2018-03"))
    df = rates(tmp_path, rows, k, groups={"EU": {DE}})
    assert value(df, STEEL, DE, "2018-03") == 0
    assert value(df, STEEL, CN, "2018-03") == pytest.approx(0.25 * 9 / 31)  # from the 23rd


def test_family_fill_extends_lists_to_renamed_codes(tmp_path):
    lists = tmp_path / "hs_lists"
    lists.mkdir()
    (lists / "l.csv").write_text("hs\n61102000\n")
    rows = [act("L", "S301", CN, "file:hs_lists/l.csv", 0.25, "2018-09-24", iso="CN")]
    # 6110200010 exists in 2018; in 2019 it is replaced by 6110209999 (same family, new HTS8)
    k = keys((OTHER, CN, "2018-10"), ("6110209999", CN, "2019-01"))
    # 6110209998 is in the family table but never traded: not in the panel, must be ignored
    fam = pl.DataFrame({"hs10": [OTHER, "6110209999", "6110209998"], "family": ["F1"] * 3})
    out = tr.expand(load(tmp_path, rows), k, base_dir=tmp_path, groups={}, families=fam,
                    mfn=pl.DataFrame({"hs10": ["x"], "mfn_rate": [0.0]}))  # fmt: skip
    assert out.filter(pl.col("hs10") == "6110209999")["rate_total"][0] == pytest.approx(0.25)

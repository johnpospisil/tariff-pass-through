"""Tests for reference concordances (P06)."""

from pathlib import Path

import polars as pl
import pytest

from tpt.build import concordance as cc
from tpt.ingest import bea_io, hs_codes, rauch

FIXTURES = Path(__file__).parent / "fixtures"


# --- Census HS10 code lists --------------------------------------------------


def test_parse_fixed_width_concordance():
    df = hs_codes.parse_fixed_width((FIXTURES / "iconcord_2026_sample.txt").read_bytes())
    assert df.columns == hs_codes.COLUMNS
    laptop = df.filter(pl.col("hs10") == "8471300100").row(0, named=True)
    assert laptop["desc_short"].startswith("PORT DGTL ADP MACH")
    assert laptop["unit_qy1"] == "NO"
    assert laptop["sitc"] == "75220"
    assert laptop["end_use"] == "21300"
    assert laptop["naics"] == "334111"
    assert laptop["hitech"] == "04"


# --- HS10 families (Pierce-Schott style) -------------------------------------


def _families(codes_by_year):
    fam = cc.hs10_families(codes_by_year)
    return {r["hs10"]: r["family"] for r in fam.iter_rows(named=True)}


def test_unchanged_codes_are_their_own_family():
    fam = _families({2017: {"0101210010", "0101210020"}, 2018: {"0101210010", "0101210020"}})
    assert fam == {"0101210010": "0101210010", "0101210020": "0101210020"}


def test_replaced_code_joins_its_replacement_within_hs8():
    fam = _families(
        {
            2017: {"8471300100", "8471300200", "9999000000"},
            2018: {"8471300100", "8471300300", "9999000000"},  # ...200 replaced by ...300
        }
    )
    assert fam["8471300200"] == fam["8471300300"]
    assert fam["8471300100"] == "8471300100"  # persisting sibling untouched
    assert fam["9999000000"] == "9999000000"


def test_replacement_falls_back_to_hs6_then_hs4():
    fam = _families({2017: {"8471300100"}, 2018: {"8471410000"}})  # same HS4 only
    assert fam["8471300100"] == fam["8471410000"]


def test_carve_out_links_new_code_to_hs8_siblings():
    fam = _families({2017: {"6110200010"}, 2018: {"6110200010", "6110200099"}})
    assert fam["6110200010"] == fam["6110200099"]


def test_every_code_maps_to_exactly_one_family():
    fam = cc.hs10_families(
        {
            2017: {"0101210010", "0101210020"},
            2018: {"0101210010", "0101210030"},
            2019: {"0101210030", "0201100000"},
        }  # fmt: skip
    )
    assert fam["hs10"].is_unique().all()
    assert fam["family"].null_count() == 0


def test_family_ids_are_deterministic():
    years = {2017: {"8471300200"}, 2018: {"8471300300"}}
    assert cc.hs10_families(years).equals(cc.hs10_families(years))
    assert _families(years)["8471300300"] == "F8471300200"


# --- NAICS to BEA ------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("11111-2", ["11111", "11112"]),
        ("11113-6, 11119", ["11113", "11114", "11115", "11116", "11119"]),
        ("23*", ["23"]),
        ("332111-2, 332117", ["332111", "332112", "332117"]),
        ("32192-9", [f"3219{d}" for d in range(2, 10)]),
        (None, []),
    ],
)
def test_expand_naics_spec(spec, expected):
    assert bea_io.expand_naics_spec(spec) == expected


def test_naics_to_bea_longest_prefix():
    bea = pl.DataFrame({"bea_code": ["334111", "33411A", "230000"],
                        "naics_prefix": ["334111", "3341", "23"]})  # fmt: skip
    out = cc.naics_to_bea(pl.Series("naics", ["334111", "334112", "236118", "999999"]), bea)
    assert dict(zip(out["naics"], out["bea_code"], strict=True)) == {
        "334111": "334111", "334112": "33411A", "236118": "230000", "999999": None,
    }  # fmt: skip


def test_naics_to_bea_translates_2022_codes_to_2017():
    bea = pl.DataFrame({"bea_code": ["336111", "336112"], "naics_prefix": ["336111", "336112"]})
    out = cc.naics_to_bea(pl.Series("naics", ["336110"]), bea, {"336110": ["336111", "336112"]})
    assert out["bea_code"].to_list() == ["336111"]


def test_naics_to_bea_special_codes_and_truncated_codes():
    bea = pl.DataFrame({"bea_code": ["1121A0", "1121A0", "S00401"],
                        "naics_prefix": ["11211", "11213", "n.a."]})  # fmt: skip
    out = cc.naics_to_bea(pl.Series("naics", ["910000", "1121XX", "990000"]), bea,
                          special={"910000": "S00401"})  # fmt: skip
    assert dict(zip(out["naics"], out["bea_code"], strict=True)) == {
        "910000": "S00401", "1121XX": "1121A0", "990000": None,
    }  # fmt: skip


# --- Rauch -------------------------------------------------------------------


def test_rauch_fallbacks_other_revision_then_hs4():
    rauch_hs6 = pl.DataFrame(
        {
            "hs_revision": ["HS2017", "HS2022", "HS2017"],
            "hs6": ["847330", "880730", "847130"],
            "rauch_con": ["n", "n", "r"],
            "rauch_lib": ["n", "n", "r"],
            "rauch_mixed": [False, False, False],
        }  # fmt: skip
    )
    attrs = pl.DataFrame(
        {
            "hs_revision": ["HS2017", "HS2017", "HS2017", "HS2017"],
            "hs6": ["847330", "880730", "847350", "990000"],
        }  # fmt: skip
    )
    out = cc.rauch_with_fallback(attrs, rauch_hs6)
    assert out["rauch_source"].to_list() == ["hs6", "hs6_other_revision", "hs4_mode", None]
    assert out["rauch_con"].to_list() == ["n", "n", "n", None]


def test_hs6_rauch_takes_modal_class_and_flags_mixed():
    hs_sitc = pl.DataFrame(
        {
            "hs6": ["010121", "847130", "847130", "847130"],
            "sitc2_4d": ["0015", "7522", "7522", "7599"],
        }  # fmt: skip
    )
    classes = pl.DataFrame({"sitc2_4d": ["0015", "7522", "7599"], "con": ["w", "n", "r"],
                            "lib": ["w", "n", "r"]})  # fmt: skip
    out = rauch.hs6_classification(hs_sitc, classes).sort("hs6")
    row = out.filter(pl.col("hs6") == "847130").row(0, named=True)
    assert row["rauch_con"] == "n"
    assert row["rauch_mixed"] is True
    assert out.filter(pl.col("hs6") == "010121")["rauch_mixed"].item() is False


# --- PCE <-> CPI -------------------------------------------------------------


def test_normalise_description_collapses_whitespace_and_case():
    assert cc.normalise("Men's and boys'   clothing ") == "men's and boys' clothing"


def test_cpi_strata_from_eli():
    eli = pl.DataFrame({"eli": ["AA011", "SEAA01"]})
    strata = eli.select(cc.eli_to_strata(pl.col("eli")).alias("strata"))["strata"]
    assert strata.to_list() == ["SEAA01", None]


def test_crosswalk_falls_back_to_expenditure_class_and_hand_lines():
    mapping = pl.DataFrame(
        {
            "eli": ["AA011", "AB011", "RC011"],
            "eli_desc": ["men's suits", "boys' outerwear", "pcs"],
            "pce_code": ["DMBCRC", "DMBCRC", "DCPPRC"],
            "pce_desc": [
                "Men's and boys'  clothing",
                "Men's and boys' clothing",
                "Personal computers and peripheral equipment",
            ],
        }  # fmt: skip
    )
    bridge = pl.DataFrame(
        {
            "nipa_line": [24, 49],
            "pce_category": [
                "Men's and boys' clothing",
                "Personal computers/tablets and peripheral equipment",
            ],
        }
    )
    cpi = pl.DataFrame({"item_code": ["SEAA01", "SEAB", "SERC01"],
                        "item_name": ["Men's suits", "Boys' apparel", "Computers"],
                        "display_level": [3, 2, 3]})  # fmt: skip
    hand = pl.DataFrame(
        {
            "pce_code": ["DCPPRC"],
            "nipa_line": ["49"],
            "bridge_category": ["Personal computers/tablets and peripheral equipment"],
        }
    )
    out = cc.cpi_pce_crosswalk(mapping, bridge, cpi, hand).sort("eli")
    assert out["item_code"].to_list() == ["SEAA01", "SEAB", "SERC01"]
    assert out["cpi_match"].to_list() == ["strata", "expenditure_class", "strata"]
    assert out["nipa_line"].to_list() == [24, 24, 49]
    assert out["pce_match"].to_list() == ["description", "description", "hand"]


# --- coverage gates on real data ---------------------------------------------

needs_data = pytest.mark.skipif(
    not cc.FAMILIES_PATH.exists(), reason="run `make concordance` first"
)


@needs_data
def test_every_panel_hs10_has_a_family():
    fam = pl.read_parquet(cc.FAMILIES_PATH)
    panel = pl.scan_parquet(cc.CENSUS_GLOB).select("hs10").unique().collect()
    assert panel.join(fam, on="hs10", how="anti").height == 0


@needs_data
def test_naics_and_rauch_coverage_by_import_value():
    cov = pl.read_csv(cc.COVERAGE_REPORT)
    by = dict(zip(cov["mapping"], cov["share_of_value"], strict=True))
    assert by["family"] == pytest.approx(1.0)
    assert by["naics"] >= 0.99
    assert by["bea_commodity"] >= 0.99
    assert by["rauch_con"] >= 0.90

"""CPI item tariff exposure (P18): commodity groups, item weights, tariff changes, both routes."""

import math
from datetime import date

import polars as pl
import pytest

from tpt.build import exposure as ex

M0, M1, M2 = date(2024, 12, 1), date(2025, 1, 1), date(2025, 2, 1)


def test_naics_merges_pool_bea_commodities():
    """NAICS 2022 336110 covers BEA 336111 (autos) and 336112 (light trucks); Census lists put
    every car HS10 on 336110 -> 336111, so the two commodities are pooled into one group."""
    bea = pl.DataFrame({"bea_code": ["336111", "336112", "325411"],
                        "naics_prefix": ["336111", "336112", "325411"]})  # fmt: skip
    g = ex.commodity_groups({"336110": ["336111", "336112"], "325411": ["325411"]}, bea)
    m = dict(zip(g["bea_code"], g["group"], strict=True))
    assert m["336111"] == m["336112"] == "336111+336112"
    assert m["325411"] == "325411"


def test_import_shares_by_group():
    supply = pl.DataFrame({
        "commodity_code": ["a", "a", "b", "b", "c", "c"],
        "column_code": ["MCIF", "T013"] * 3,
        "value": [30.0, 100.0, 10.0, 100.0, 0.0, 50.0],
    })  # fmt: skip
    groups = pl.DataFrame({"bea_code": ["a", "b", "c"], "group": ["a+b", "a+b", "c"]})
    s = ex.import_shares(supply, groups)
    m = dict(zip(s["group"], s["import_share"], strict=True))
    assert m["a+b"] == pytest.approx(40 / 200) and m["c"] == 0.0


def _xwalk_bridge():
    # Item X has two ELIs: e1 -> line 1; e2 -> lines 1 and 2 (split by line purchasers' value).
    xwalk = pl.DataFrame(
        {"item_code": ["X", "X", "X", "Y"], "eli": ["e1", "e2", "e2", "e3"],
         "nipa_line": [1, 1, 2, None]},
        schema_overrides={"nipa_line": pl.Int32},
    )  # fmt: skip
    bridge = pl.DataFrame({
        "nipa_line": [1, 1, 2],
        "commodity_code": ["g1", "s1", "g2"],
        "producers_value": [60.0, 20.0, 50.0],
        "purchasers_value": [90.0, 30.0, 50.0],  # line 1: 120 purchasers, 80 producers
    }, schema_overrides={"nipa_line": pl.Int32})  # fmt: skip
    groups = pl.DataFrame({"bea_code": ["g1", "s1", "g2"], "group": ["g1", "s1", "g2"]})
    return xwalk, bridge, groups


def test_item_weights_sum_to_one_and_carry_margins():
    w = ex.item_weights(*_xwalk_bridge())
    x = w.filter(pl.col("item_code") == "X")
    assert x["w"].sum() == pytest.approx(1.0)
    # e1: all line 1. e2: line 1 120/(120+50), line 2 50/170. Item: 1/2 each ELI.
    l1 = 0.5 + 0.5 * 120 / 170
    m = dict(zip(x["group"], x["w"], strict=True))
    assert m["g1"] == pytest.approx(l1 * 60 / 80) and m["g2"] == pytest.approx(1 - l1)
    mp = dict(zip(x["group"], x["w_purch"], strict=True))
    assert mp["g1"] == pytest.approx(l1 * 60 / 120)  # trade margins are not imported goods
    assert "Y" not in w["item_code"].to_list()  # no bridge line: unmapped, reported separately


def _rates():
    base = pl.DataFrame({"hs10": ["h1", "h2", "h3"], "cty_code": ["c", "c", "c"],
                         "group": ["g1", "g1", "g2"], "value": [100.0, 300.0, 50.0]})  # fmt: skip
    rates = pl.DataFrame({
        "hs10": ["h1", "h1", "h1", "h2", "h2", "h2", "h3", "h4"],
        "cty_code": ["c"] * 8,
        "month": [M0, M1, M2, M0, M1, M2, M0, M1],
        "rate_total": [0.0, 0.10, 0.25, 0.0, 0.0, 0.10, 0.0, 0.20],
    })  # fmt: skip
    families = pl.DataFrame({"hs10": ["h1", "h2", "h3", "h4"], "family": ["h1", "h2", "F3", "F3"]})
    return base, rates, families


def test_pair_changes_fall_back_to_family_when_code_changes():
    pairs = ex.pair_dtau(*_rates(), base_month=M0)
    h3 = pairs.filter(pl.col("hs10") == "h3").sort("month")
    # h3 dropped after the base month; its family (with h4) carries the 20% rate in January.
    assert h3.filter(pl.col("month") == M1)["dtau"][0] == pytest.approx(math.log(1.2))
    assert M2 not in h3["month"].to_list()  # no rate for the family: dropped, not zero


def test_base_rate_falls_back_to_latest_base_year_month():
    """The rate panel has rows only for pairs traded that month: a pair not traded in December
    takes its latest earlier base-year rate."""
    base = pl.DataFrame({"hs10": ["h1"], "cty_code": ["c"], "group": ["g"], "value": [1.0]})
    rates = pl.DataFrame({"hs10": ["h1"] * 2, "cty_code": ["c"] * 2,
                          "month": [date(2024, 10, 1), M1],
                          "rate_total": [0.05, 0.30]})  # fmt: skip
    fam = pl.DataFrame({"hs10": ["h1"], "family": ["h1"]})
    p = ex.pair_dtau(base, rates, fam, base_month=M0).filter(pl.col("month") == M1)
    assert p["dtau"][0] == pytest.approx(math.log(1.3) - math.log(1.05))


def test_group_dtau_is_base_value_weighted():
    g = ex.group_dtau(ex.pair_dtau(*_rates(), base_month=M0))
    g1 = g.filter(pl.col("group") == "g1").sort("month")
    assert g1["dtau"].to_list() == pytest.approx(
        [0.0, 0.25 * math.log(1.1), 0.25 * math.log(1.25) + 0.75 * math.log(1.1)]
    )


def test_effective_dtau_against_base_year():
    flows = pl.DataFrame({
        "group": ["g"] * 3, "month": [date(2024, 6, 1), date(2024, 12, 1), date(2025, 3, 1)],
        "con_val": [100.0, 100.0, 200.0], "cal_dut": [2.0, 4.0, 30.0],
    })  # fmt: skip
    e = ex.effective_dtau(flows, base_year=2024).filter(pl.col("month") == date(2025, 3, 1))
    assert e["dtau_eff"][0] == pytest.approx(math.log(1.15) - math.log(1.03))


def test_item_series_exposure_and_coverage():
    w = pl.DataFrame({"item_code": ["X"] * 3, "group": ["g1", "g2", "s1"],
                      "w": [0.5, 0.3, 0.2], "w_purch": [0.4, 0.3, 0.1]})  # fmt: skip
    shares = pl.DataFrame({"group": ["g1", "g2", "s1"], "import_share": [0.5, 0.2, 0.1]})
    dtau = pl.DataFrame({"group": ["g1"], "month": [M1], "dtau": [0.10], "dtau_eff": [0.04]})
    goods = {"g1", "g2"}
    s = ex.item_series(w, shares, dtau, goods).row(0, named=True)
    assert s["import_share"] == pytest.approx(0.4 * 0.5 + 0.3 * 0.2 + 0.1 * 0.1)
    assert s["goods_import_share"] == pytest.approx(0.4 * 0.5 + 0.3 * 0.2)
    assert s["exposure"] == pytest.approx(0.4 * 0.5 * 0.10)  # g2 has no tariff data: not counted
    assert s["dtau"] == pytest.approx(0.10)  # mean over mapped goods imports
    assert s["coverage"] == pytest.approx(0.20 / 0.26)  # mapped share of goods import weight


def test_hand_route_weights_hs_codes_by_base_value():
    pairs = ex.pair_dtau(*_rates(), base_month=M0)
    hand = pl.DataFrame({"item_code": ["T", "T"], "hs_prefix": ["h1", "h2"]})
    h = ex.hand_dtau(hand, pairs).filter(pl.col("month") == M2)
    assert h["dtau"][0] == pytest.approx(0.25 * math.log(1.25) + 0.75 * math.log(1.1))


def test_window_mean():
    s = pl.DataFrame({"item_code": ["X"] * 3, "month": [M0, M1, M2], "dtau": [0.0, 0.1, 0.3]})
    out = ex.window_mean(s, ["item_code"], ["dtau"], M1, M2)
    assert out["dtau"][0] == pytest.approx(0.2)


# --- built outputs ---------------------------------------------------------------


@pytest.fixture(scope="module")
def built() -> pl.DataFrame:
    if not ex.OUT.exists():
        pytest.skip("run make exposure")
    return pl.read_parquet(ex.OUT)


def test_built_weights_sum_to_one_within_each_item():
    if not ex.WEIGHTS_OUT.exists():
        pytest.skip("run make exposure")
    w = pl.read_parquet(ex.WEIGHTS_OUT).group_by("item_code").agg(pl.col("w").sum())
    assert w["w"].to_numpy() == pytest.approx(1.0, abs=1e-9)


def test_built_exposure_is_sane(built):
    b = built.filter(pl.col("route") == "bea")
    assert b["import_share"].is_between(0, 1).all()
    assert b.filter(pl.col("item_code") == "SEHC01").is_empty()  # owners' rent: no bridge line
    p = b.filter(pl.col("period") == "2025_26")
    m = dict(zip(p["item_code"], p["exposure"], strict=True))
    assert m["SERE01"] > 0.01 > m["SEHA"]  # toys exposed; rent not
    assert m["SEHA"] == pytest.approx(0.0, abs=1e-3)

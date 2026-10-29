"""Robustness grid (P17): cleaning rules, sample masks, weighting, the moves-beta flag."""

import math
from datetime import date

import numpy as np
import polars as pl
import pytest

from tpt.models import border_pt as bp
from tpt.models import robustness as rb


def test_cleaning_rules():
    df = pl.DataFrame({
        "dln_uv": [0.2, 0.5, -0.5, 1.5],  # published (1/99 winsorised)
        "dln_uv_raw": [0.2, 0.9, -0.9, 3.0],
    })  # fmt: skip
    bounds = {(0.01, 0.99): {"dln_uv": (-2.0, 2.0)}, (0.05, 0.95): {"dln_uv": (-0.5, 0.5)}}
    w1, y = rb.clean(df, "w1", "dln_uv", bounds)
    assert y == "dln_uv" and w1["dln_uv"].to_list() == [0.2, 0.5, -0.5, 1.5]
    w5, y = rb.clean(df, "w5", "dln_uv", bounds)
    assert w5[y].to_list() == [0.2, 0.5, -0.5, 0.5]
    t1, y = rb.clean(df, "trim1", "dln_uv", bounds)
    assert t1[y].to_list() == [0.2, 0.9, -0.9]  # 3.0 outside the 1/99 bounds dropped
    t3, y = rb.clean(df, "trim3", "dln_uv", bounds)
    assert t3[y].to_list() == [0.2, 0.9, -0.9]  # |ln 3| = 1.10
    assert math.log(3) < 3.0


def test_trims_use_the_unit_value_change_for_quantity_too():
    df = pl.DataFrame({"dln_uv_raw": [0.1, 2.0], "dln_qty": [0.3, -1.8],
                       "dln_qty_raw": [0.3, -1.8]})  # fmt: skip
    out, y = rb.clean(df, "trim3", "dln_qty", {})
    assert y == "dln_qty_raw" and out[y].to_list() == [0.3]


def test_frontrun_masks():
    df = pl.DataFrame({"k": [None, -7, -6, -1, 0, 5, 6, 11, 12]})
    keep = df.filter(rb.keep_frontrun(base=False))["k"].to_list()
    assert keep == [None, -7, 0, 5, 6, 11, 12]
    keep = df.filter(rb.keep_frontrun(base=True))["k"].to_list()
    assert keep == [None, -7, 0, 5, 12]  # k 6..11: the base month was a front-run month


def test_s232_products_flagged_across_countries():
    df = pl.DataFrame({
        "prod_id": ["a", "a", "b", "c"], "cty_code": ["1", "2", "1", "1"],
        "rate_s232": [0.25, 0.0, 0.0, 0.0], "rate_s232_b": [0.0, 0.0, 0.0, 0.1],
    })  # fmt: skip
    assert sorted(rb.drop_s232(df)["prod_id"].to_list()) == ["b"]


def test_grid_has_every_variant_under_every_cleaning_rule():
    specs = rb.grid("2025_26")
    names = {(s.cleaning, s.variant.name) for s in specs}
    assert len(names) == len(specs) == len(rb.CLEANING) * len(rb.VARIANTS)
    assert {s.variant.name for s in rb.grid("2018_19")} == {v.name for v in rb.VARIANTS
                                                            if "2018_19" in v.periods}  # fmt: skip


def test_moves_beta_against_same_cleaning_baseline():
    est = pl.DataFrame({
        "period": ["p"] * 4, "outcome": ["uv"] * 4, "cleaning": ["w1", "w1", "trim3", "trim3"],
        "variant": ["baseline", "drop_china", "baseline", "drop_china"],
        "coef": [0.04, 0.10, -0.04, -0.045], "se": [0.03, 0.04, 0.01, 0.01],
    })  # fmt: skip
    out = rb.flag_moves(est).sort("cleaning", "variant")
    got = {(r["cleaning"], r["variant"]): r for r in out.iter_rows(named=True)}
    assert got[("w1", "drop_china")]["moves_beta"] is True  # 0.06 > 0.03
    assert got[("trim3", "drop_china")]["moves_beta"] is False  # 0.005 < 0.01
    assert got[("w1", "baseline")]["delta"] == 0.0
    # cleaning itself vs the main (w1 baseline)
    assert got[("trim3", "baseline")]["delta_vs_main"] == pytest.approx(-0.08)
    assert got[("trim3", "baseline")]["moves_vs_main"] is True


def test_weighted_fit_uses_weights():
    rng = np.random.default_rng(0)
    rows = []
    for h in range(40):
        for c in range(6):
            for m in range(1, 13):
                x = rng.choice([0.0, 0.1, 0.2])
                heavy = c == 0  # big-value varieties have beta -0.5, the rest 0
                y = (-0.5 if heavy else 0.0) * x + 0.01 * h + 0.02 * m + rng.normal(0, 0.01)
                rows.append((f"{h:06d}0000", "hs10", str(c), date(2025, m, 1), x, y,
                             1000.0 if heavy else 1.0))  # fmt: skip
    df = bp.add_keys(pl.DataFrame(rows, schema=["prod_id", "level", "cty_code", "month", bp.X,
                                                "dln_uv", "w"], orient="row"))  # fmt: skip
    fe = ("hs6^ym", "ym")
    plain = bp.fit_terms(df, "dln_uv", [bp.X], fe)[0]["coef"]
    weighted = bp.fit_terms(df, "dln_uv", [bp.X], fe, weights="w")[0]["coef"]
    assert weighted < plain - 0.1

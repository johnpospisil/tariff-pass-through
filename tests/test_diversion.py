"""Trade diversion (P20): HS6 rates, long differences, PPML, transshipment flags, share series."""

import math
from datetime import date

import numpy as np
import polars as pl
import pytest

from tpt.models import diversion as dv

M1, M2 = date(2025, 1, 1), date(2025, 2, 1)


def test_hs6_rates_weight_hs10_by_base_value_and_fill_gaps():
    rates = pl.DataFrame({
        "hs10": ["1111110010", "1111110020", "1111110010"],
        "cty_code": ["c"] * 3, "month": [M1, M1, M2], "rate_total": [0.10, 0.30, 0.20],
    })  # fmt: skip
    base = pl.DataFrame({"hs10": ["1111110010", "1111110020"], "cty_code": ["c", "c"],
                         "w": [300.0, 100.0]})  # fmt: skip
    r = dv.hs6_rates(rates, base).sort("month")
    assert r["rate"].to_list() == pytest.approx([0.15, 0.20])
    # a month with no traded HS10 is filled from the pair's previous month
    filled = dv.fill_rates(r, months=[M1, M2, date(2025, 3, 1)])
    assert filled.sort("month")["rate"].to_list() == pytest.approx([0.15, 0.20, 0.20])


def test_hs6_rates_unweighted_when_no_base_value():
    rates = pl.DataFrame({"hs10": ["2222220010", "2222220020"], "cty_code": ["c", "c"],
                          "month": [M1, M1], "rate_total": [0.1, 0.3]})  # fmt: skip
    base = pl.DataFrame(
        {"hs10": [], "cty_code": [], "w": []},
        schema={"hs10": pl.String, "cty_code": pl.String, "w": pl.Float64},
    )
    assert dv.hs6_rates(rates, base)["rate"][0] == pytest.approx(0.2)


def _sim_flows(beta: float = -2.0, seed: int = 1) -> pl.DataFrame:
    """200 HS6 x 6 countries x 8 months in each window; product, country and product x country
    effects; country 'a' gets a tariff in the post window on half the products."""
    rng = np.random.default_rng(seed)
    rows = []
    for p in range(200):
        fp = rng.normal(0, 1)
        for c in "abcdef":
            fpc = rng.normal(0, 0.5)
            tau = 0.25 if (c == "a" and p % 2) else 0.0
            for w, months in (
                ("base", dv.months_between(date(2023, 6, 1), date(2024, 1, 1))),
                ("post", dv.months_between(date(2025, 6, 1), date(2026, 1, 1))),
            ):
                for m in months:
                    t = tau if w == "post" else 0.0
                    mu = math.exp(10 + fp + fpc + beta * math.log1p(t) + rng.normal(0, 0.05))
                    rows.append({"hs6": f"{p:06d}", "cty_code": c, "month": m, "value": mu,
                                 "rate": t})  # fmt: skip
    return pl.DataFrame(rows)


def test_long_difference_recovers_elasticity():
    flows = _sim_flows()
    ld = dv.long_diff(flows, dv.PERIODS["2025_26"])
    assert ld.filter(pl.col("cty_code") == "a", pl.col("hs6") == "000001")["dtau"][0] == (
        pytest.approx(math.log(1.25)))  # fmt: skip
    r = dv.fit_ld(ld, "dln_v", ("hs6",))
    assert r["coef"] == pytest.approx(-2.0, abs=0.05)
    # shares sum to 1 within HS6 in each window
    sh = ld.group_by("hs6").agg(pl.col("share_b").sum(), pl.col("share_p").sum())
    assert sh["share_b"].to_numpy() == pytest.approx(1.0) and sh["share_p"].to_numpy() == (
        pytest.approx(1.0))  # fmt: skip


def test_ppml_recovers_elasticity_with_zeros():
    flows = _sim_flows(beta=-3.0).with_columns(
        value=pl.when((pl.col("rate") > 0) & (pl.col("hs6").str.ends_with("1")))
        .then(0.0)
        .otherwise(pl.col("value"))
    )  # a tariff that stops trade in some products: PPML keeps the zeros
    q = dv.quarterly(flows)
    r = dv.fit_ppml(q, ("hs6^quarter", "hs6^cty_code"))
    assert r["coef"] < -3.0  # zeros make the response larger than the interior -3
    assert r["n"] == q.height


def test_transshipment_flags():
    base = {("p1", "5700"): 90.0, ("p1", "x"): 2.0, ("p1", "y"): 8.0,
            ("p2", "5700"): 50.0, ("p2", "x"): 50.0}  # fmt: skip
    post = {("p1", "5700"): 40.0, ("p1", "x"): 50.0, ("p1", "y"): 10.0,
            ("p2", "5700"): 50.0, ("p2", "x"): 60.0}  # fmt: skip
    rows = [{"hs6": p, "cty_code": c, "v_b": base.get((p, c), 0.0), "v_p": post.get((p, c), 0.0)}
            for p, c in set(base) | set(post)]  # fmt: skip
    f = dv.flag_pairs(pl.DataFrame(rows), min_gain=1.0)
    assert f.select("hs6", "cty_code").rows() == [("p1", "x")]  # y had 8% before; p2: China flat
    r = f.row(0, named=True)
    assert r["china_share_b"] == pytest.approx(0.9) and r["share_p"] == pytest.approx(0.5)


def test_unit_value_gap():
    uv = pl.DataFrame({
        "hs10": ["a", "a", "b", "b"], "cty_code": ["5700", "x", "5700", "x"],
        "value": [100.0, 50.0, 100.0, 150.0], "qty": [10.0, 10.0, 10.0, 15.0],
    })  # fmt: skip
    g = dv.uv_gap(uv.with_columns(hs6=pl.lit("p")))
    # a: |ln(5/10)| = 0.693 weight 50; b: |ln(10/10)| = 0 weight 150
    assert g["uv_gap"][0] == pytest.approx(0.693147 * 50 / 200)


def test_group_shares_sum_to_one():
    df = pl.DataFrame({"month": [M1] * 3, "group": ["China", "Vietnam", "Rest of world"],
                       "value": [5.0, 3.0, 2.0], "panel": ["s301"] * 3})  # fmt: skip
    s = dv.group_shares(df, window=1)
    assert s["share"].sum() == pytest.approx(1.0)

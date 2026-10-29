"""Border pass-through regressions (P15): keys, trimming, event dates, FE estimates."""

import math
from datetime import date

import numpy as np
import polars as pl
import pytest

from tpt.models import border_pt as bp


def test_keys_from_hs10_and_family_ids():
    df = pl.DataFrame({
        "prod_id": ["0101210020", "F4407100101"], "level": ["hs10", "family"],
        "cty_code": ["5700", "1220"], "month": [date(2018, 3, 1), date(2019, 11, 1)],
    })  # fmt: skip
    k = bp.add_keys(df)
    assert k["hs6"].to_list() == ["010121", "440710"]
    assert k["hs8"].to_list() == ["01012100", "44071001"]
    assert k["hs2"].to_list() == ["01", "44"]
    assert k["ym"].to_list() == ["2018-03", "2019-11"]
    assert k["year"].to_list() == [2018, 2019]


def test_arw_ratio_trim_drops_unit_value_ratios_beyond_three():
    df = pl.DataFrame({"dln_uv_raw": [0.0, math.log(2.9), math.log(3.1), -math.log(3.1), None]})
    out = bp.trim_ratio(df, 3.0)
    assert out.height == 2  # null base and both tails dropped


def test_event_month_uses_half_rate_rule():
    # mid-month action (35% of the month at 10%): event is the next month, as with a 15th cutoff
    months = [date(2018, m, 1) for m in range(1, 7)]
    df = pl.DataFrame({
        "prod_id": ["a"] * 6 + ["b"] * 6 + ["c"] * 6 + ["d"] * 6,
        "cty_code": ["5700"] * 24, "month": months * 4,
        "stat_rate": [0.0, 0, 0.035, 0.10, 0.10, 0.10]  # a: event 2018-04
        + [0.0, 0.25, 0.25, 0.25, 0.25, 0.25]  # b: from the 1st -> 2018-02
        + [0.0] * 6  # c: never
        + [0.0, 0.01, 0.02, 0.02, 0.02, 0.02],  # d: below the minimum step
    })  # fmt: skip
    ev = bp.event_months(df).sort("prod_id")
    got = dict(zip(ev["prod_id"], ev["event"], strict=True))
    assert got == {"a": date(2018, 4, 1), "b": date(2018, 2, 1)}


def test_event_dummies_bin_trim_and_omit_minus_one():
    df = pl.DataFrame({
        "prod_id": ["a"] * 4 + ["c"], "cty_code": ["1"] * 5,
        "month": [date(2017, 1, 1), date(2018, 2, 1), date(2018, 3, 1), date(2019, 6, 1),
                  date(2018, 3, 1)],
    })  # fmt: skip
    ev = pl.DataFrame({"prod_id": ["a"], "cty_code": ["1"], "event": [date(2018, 3, 1)]})
    out = bp.event_dummies(df, ev).sort("prod_id", "month")
    assert out.height == 4  # a at k = -14 dropped (<= -7)
    a = out.filter(pl.col("prod_id") == "a")
    assert a["k"].to_list() == [-1, 0, 6]  # 2019-06 is k = 15, binned at 6
    assert "ev_m1" not in out.columns
    assert a["ev_0"].to_list() == [0, 1, 0] and a["ev_6"].to_list() == [0, 0, 1]
    c = out.filter(pl.col("prod_id") == "c")
    assert c["k"][0] is None and sum(c[col][0] for col in bp.EVENT_COLS) == 0


def _panel(beta: float, n_hs6: int = 60, n_cty: int = 8, seed: int = 0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for h in range(n_hs6):
        for c in range(n_cty):
            for m in range(1, 13):
                tau = rng.choice([0, 0.1, 0.25]) if c < 3 else 0.0
                x = math.log(1 + tau)
                y = beta * x + 0.01 * h + 0.02 * c + 0.03 * m + rng.normal(0, 0.02)
                rows.append((f"{h:06d}0000", "hs10", str(c), date(2018, m, 1), x, y))
    return pl.DataFrame(rows, schema=["prod_id", "level", "cty_code", "month",
                                      "dln_1p_tau_stat", "dln_uv"], orient="row")  # fmt: skip


def test_fit_recovers_beta_with_fixed_effects():
    df = bp.add_keys(_panel(-0.3))
    spec = bp.Spec("t", "dln_uv", fe=("hs6^ym", "cty_code^ym"), cluster="hs8")
    r = bp.fit(df, spec)
    assert r["coef"] == pytest.approx(-0.3, abs=0.02)
    assert 0 < r["se"] < 0.05
    assert r["n"] == df.height
    assert r["ci_low"] < r["coef"] < r["ci_high"]


def test_event_study_recovers_a_step_in_levels():
    rng = np.random.default_rng(1)
    months = [date(2017, m, 1) for m in range(1, 13)] + [date(2018, m, 1) for m in range(1, 13)]
    rows = []
    for v in range(300):
        treated = v < 150
        for mo in months:
            post = treated and mo >= date(2018, 3, 1)
            y = 0.2 * post + 0.001 * v + rng.normal(0, 0.01)
            rows.append((f"{v % 30:06d}{v:04d}", "hs10", str(v % 4), mo, y,
                         0.25 if post else 0.0))  # fmt: skip
    df = pl.DataFrame(rows, schema=["prod_id", "level", "cty_code", "month", "ln_uv",
                                    "stat_rate"], orient="row")  # fmt: skip
    es = bp.event_study(bp.add_keys(df), "ln_uv", fe=("variety", "hs6^ym", "cty_code^ym"))
    get = dict(zip(es["k"], es["coef"], strict=True))
    assert get[-1] == 0.0  # reference
    assert all(abs(get[k]) < 0.01 for k in range(-6, -1))
    assert all(get[k] == pytest.approx(0.2, abs=0.01) for k in range(0, 7))

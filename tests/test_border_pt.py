"""Border pass-through regressions (P15, P16): keys, trimming, event dates, FE estimates."""

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


# --- P16 -----------------------------------------------------------------------


def test_event_month_relative_to_base_rate_without_half_rule():
    # 2025: steps over a December 2024 base; rates rise in successive monthly steps, so the
    # half-rate rule would push China's event from February to April
    months = [date(2024, 11, 1), date(2024, 12, 1)] + [date(2025, m, 1) for m in range(1, 6)]
    df = pl.DataFrame({
        "prod_id": ["a"] * 7 + ["b"] * 7 + ["c"] * 7, "cty_code": ["5700"] * 21,
        "month": months * 3,
        "stat_rate": [0.25, 0.25, 0.25, 0.339, 0.437, 1.30, 0.55]  # a: China, S301 base
        + [0.075, 0.075, 0.075, 0.075, 0.075, 0.075, 0.075]  # b: unchanged -> control
        + [0.0, 0.0, 0.02, 0.02, 0.02, 0.12, 0.12],  # c: +2pp (below the step), then April
    })  # fmt: skip
    base = pl.DataFrame({"prod_id": ["a", "b", "c"], "cty_code": ["5700"] * 3,
                         "base_rate": [0.25, 0.075, 0.0]})  # fmt: skip
    ev = bp.event_months(df, base=base, start=date(2025, 1, 1), half_rule=False)
    got = dict(zip(ev["prod_id"], ev["event"], strict=True))
    assert got == {"a": date(2025, 2, 1), "c": date(2025, 4, 1)}


def test_authority_terms_sum_to_change_in_log_one_plus_tau():
    # China: S301 25% + fentanyl 20% + reciprocal 10% on a 25% base; steel: S232 50% replaces
    # a 10% reciprocal rate
    df = pl.DataFrame({
        "stat_rate": [0.80, 0.50], "stat_rate_b": [0.25, 0.10],
        "rate_s232": [0.0, 0.50], "rate_s232_b": [0.0, 0.0],
        "rate_s301": [0.25, 0.0], "rate_s301_b": [0.25, 0.0],
        "rate_ieepa_fentanyl": [0.20, 0.0], "rate_ieepa_fentanyl_b": [0.0, 0.0],
        "rate_ieepa_reciprocal": [0.35, 0.0], "rate_ieepa_reciprocal_b": [0.0, 0.10],
        "rate_ieepa_other": [0.0, 0.0], "rate_ieepa_other_b": [0.0, 0.0],
        "rate_s201": [0.0, 0.0], "rate_s201_b": [0.0, 0.0],
        "rate_s122": [0.0, 0.0], "rate_s122_b": [0.0, 0.0],
        "rate_s338": [0.0, 0.0], "rate_s338_b": [0.0, 0.0],
    })  # fmt: skip
    out = bp.authority_terms(df)
    terms = [f"{bp.X}__{a}" for a in bp.AUTHORITY]
    total = out.select(pl.sum_horizontal(terms).alias("s"))["s"].to_list()
    exact = [math.log(1.80 / 1.25), math.log(1.50 / 1.10)]
    assert total == pytest.approx(exact, abs=0.005)
    steel = out.row(1, named=True)
    assert steel[f"{bp.X}__s232"] > 0 > steel[f"{bp.X}__ieepa"]
    assert out[f"{bp.X}__s301"].to_list() == [0.0, 0.0]


def test_split_x_puts_each_row_in_its_group_term():
    df = pl.DataFrame({bp.X: [0.1, 0.2, 0.3], "g": ["china", "other", "china"]})
    out, terms = bp.split_x(df, "g")
    assert terms == [f"{bp.X}__china", f"{bp.X}__other"]
    assert out[terms[0]].to_list() == [0.1, 0.0, 0.3]
    assert out[terms[1]].to_list() == [0.0, 0.2, 0.0]


def test_group_labels():
    df = pl.DataFrame({"cty_code": ["5700", "1220", "2010", "5880"],
                       "rauch_con": ["n", "r", "w", None], "k": [None, 0, 5, 14]})  # fmt: skip
    out = df.with_columns(c=bp.country_group(), r=bp.rauch_class(), t=bp.time_bin())
    assert out["c"].to_list() == ["china", "canada", "mexico", "other"]
    assert out["r"].to_list() == ["differentiated", "homogeneous", "homogeneous", "unclassified"]
    assert out["t"].to_list() == ["none", "m0_2", "m3_5", "m12p"]


def _two_group_panel(seed: int = 0) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for h in range(60):
        for c in range(8):
            for m in range(1, 13):
                tau = rng.choice([0, 0.1, 0.25])
                x = math.log(1 + tau)
                beta = -0.5 if c == 0 else 0.0
                e = rng.normal(0, 0.02)
                y = beta * x + 0.01 * h + 0.02 * c + 0.03 * m + e
                x_eff = x - 5 * e + rng.normal(0, 0.01)  # implied rate: mechanical + noise
                rows.append((f"{h:06d}0000", "hs10", str(c), date(2025, m, 1), x, x_eff, y,
                             "a" if c == 0 else "b"))  # fmt: skip
    return pl.DataFrame(rows, schema=["prod_id", "level", "cty_code", "month", bp.X, bp.X_EFF,
                                      "dln_uv", "g"], orient="row")  # fmt: skip


def test_fit_terms_recovers_group_slopes():
    df, terms = bp.split_x(bp.add_keys(_two_group_panel()), "g")
    rows = {r["term"]: r for r in bp.fit_terms(df, "dln_uv", terms, ("hs6^ym", "cty_code^ym"))}
    assert rows[f"{bp.X}__a"]["coef"] == pytest.approx(-0.5, abs=0.03)
    assert rows[f"{bp.X}__b"]["coef"] == pytest.approx(0.0, abs=0.03)


def test_iv_on_implied_rate_removes_mechanical_bias():
    df = bp.add_keys(_two_group_panel()).filter(pl.col("g") == "b")
    fe = ("hs6^ym", "cty_code^ym")
    ols = bp.fit_terms(df, "dln_uv", [bp.X_EFF], fe)[0]
    iv = bp.fit_terms(df, "dln_uv", [bp.X_EFF], fe, iv=bp.X)[0]
    assert ols["coef"] < -0.05  # y error enters the implied rate with the opposite sign
    assert iv["coef"] == pytest.approx(0.0, abs=0.03)
    assert iv["term"] == bp.X_EFF


def test_locality_rates_value_weighted_and_twelve_month_change():
    months = [date(2024, 3, 1), date(2025, 3, 1)]
    df = pl.DataFrame({
        "cty_code": ["5700", "5700", "5520", "5520"] * 2,
        "month": [months[0]] * 4 + [months[1]] * 4,
        "con_val": [100.0, 300.0, 50.0, 50.0] * 2,
        "cal_dut": [25.0, 75.0, 0.0, 0.0, 45.0, 135.0, 5.0, 5.0],
        "stat_rate": [0.25, 0.25, 0.0, 0.0, 0.45, 0.45, 0.10, 0.10],
    })  # fmt: skip
    out = bp.locality_rates(df, {"China": ["5700"], "ASEAN": ["5520", "5490"]})
    c = out.filter(pl.col("locality") == "China", pl.col("month") == months[1]).row(0, named=True)
    assert c["stat_rate"] == pytest.approx(0.45)
    assert c["dln_1p_tau_stat"] == pytest.approx(math.log(1.45 / 1.25))
    assert c["dln_1p_tau_eff"] == pytest.approx(math.log(1.45 / 1.25))
    a = out.filter(pl.col("locality") == "ASEAN", pl.col("month") == months[1]).row(0, named=True)
    assert a["dln_1p_tau_stat"] == pytest.approx(math.log(1.10))

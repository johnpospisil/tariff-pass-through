"""Retail CPI difference-in-differences (P19): sample, seasonality, estimators on simulated data."""

import math
from datetime import date

import numpy as np
import polars as pl
import pytest

from tpt.models import retail_did as rd


def test_leaf_items_drop_parents():
    assert rd.leaf_items(["SEHK", "SEHK01", "SEHK02", "SEAG01", "SERA"]) == [
        "SEAG01", "SEHK01", "SEHK02", "SERA"]  # fmt: skip


def test_terciles():
    s = pl.DataFrame({"item_code": list("abcdef"), "exposure": [0.0, 0.01, 0.02, 0.03, 0.05, 0.08]})
    g = dict(rd.terciles(s).iter_rows())
    assert [g[c] for c in "abcdef"] == ["low", "low", "mid", "mid", "high", "high"]


def test_missing_months_reported_not_filled():
    df = pl.DataFrame({"item_code": ["a", "a", "b"],
                       "month": [date(2025, 9, 1), date(2025, 10, 1), date(2025, 10, 1)],
                       "value": [100.0, None, 101.0]})  # fmt: skip
    kept, missing = rd.drop_missing(df)
    assert kept.height == 2
    assert missing.row(0, named=True) == {"month": date(2025, 10, 1), "n_missing": 1}


def _sim(theta: float = 0.7, seed: int = 0, trend: float = 0.0) -> pl.DataFrame:
    """60 items x 48 months: item x month-of-year seasonality, common month shocks, an item
    trend (exposed items fall by `trend` a month faster), and exposure that switches on in month
    25 for the exposed half."""
    rng = np.random.default_rng(seed)
    months = [date(2023 + m // 12, m % 12 + 1, 1) for m in range(48)]
    rows = []
    for i in range(60):
        season = rng.normal(0, 0.02, 12)
        e = 0.05 * (i % 2) * rng.uniform(0.5, 1.5)
        for t, m in enumerate(months):
            e_t = e if t >= 25 else 0.0
            slope = 0.001 - trend * (i % 2)
            y = 4.6 + season[m.month - 1] + slope * t + theta * e_t + rng.normal(0, 0.002)
            rows.append({"item_code": f"S{i:03d}", "month": m, "ln_p": y, "E": e_t, "E_i": e})
    shocks = {m: rng.normal(0, 0.01) for m in months}
    df = pl.DataFrame(rows).with_columns(
        pl.col("ln_p") + pl.col("month").replace_strict(shocks, return_dtype=pl.Float64)
    )
    return rd.add_keys(df)


def test_levels_and_differences_recover_theta():
    df = _sim()
    lv = rd.fit(df, "ln_p", "E", rd.FE_LEVELS, cluster="item_code")
    assert lv["coef"] == pytest.approx(0.7, abs=0.03)
    d = rd.diff12(df, ["ln_p", "E"])
    df12 = rd.fit(d, "d12_ln_p", "d12_E", rd.FE_DIFF, cluster="item_code")
    assert df12["coef"] == pytest.approx(0.7, abs=0.03)


def test_detrending_removes_pre_trends_correlated_with_exposure():
    """Exposed items fall 0.3%/month faster: without item trends the levels estimate is biased
    down; against each item's pre-period trend it recovers theta."""
    df = rd.deseasonalise(_sim(trend=0.003), pre_end=date(2024, 12, 1))
    df = rd.detrend(df, date(2023, 1, 1), date(2024, 12, 1))
    biased = rd.fit(df, "ln_p", "E", rd.FE_LEVELS, cluster="item_code")
    assert biased["coef"] < 0.3
    main = rd.fit(df, "ln_dt", "E", rd.FE_SA, cluster="item_code")
    assert main["coef"] == pytest.approx(0.7, abs=0.05)


def test_detrend_needs_enough_pre_months():
    df = pl.DataFrame({"item_code": ["a"] * 3 + ["b"] * 13,
                       "month": [date(2024, m, 1) for m in (1, 2, 3)]
                       + [date(2024, m, 1) for m in range(1, 13)] + [date(2025, 1, 1)],
                       "ln_sa": [1.0, 1.1, 1.2] + [0.01 * m for m in range(12)]
                       + [0.5]})  # fmt: skip
    d = rd.detrend(df, date(2024, 1, 1), date(2024, 12, 1))
    assert d.filter(pl.col("item_code") == "a")["ln_dt"].is_null().all()
    b = d.filter(pl.col("item_code") == "b").sort("month")
    assert b["ln_dt"][0] == pytest.approx(0.0, abs=1e-12)
    assert b["ln_dt"][-1] == pytest.approx(0.5 - 0.12)


def test_diff12_needs_the_month_a_year_earlier():
    df = pl.DataFrame({"item_code": ["a"] * 3,
                       "month": [date(2024, 9, 1), date(2025, 9, 1), date(2025, 11, 1)],
                       "ln_p": [1.0, 1.1, 1.2]})  # fmt: skip
    d = rd.diff12(df, ["ln_p"])
    assert d["month"].to_list() == [date(2025, 9, 1)]
    assert d["d12_ln_p"][0] == pytest.approx(0.1)


def test_event_study_flat_before_and_theta_after():
    df = rd.deseasonalise(_sim(theta=1.0, trend=0.003), pre_end=date(2024, 12, 1))
    df = rd.detrend(df, date(2023, 1, 1), date(2024, 12, 1))
    ev = rd.event_study(df, "ln_dt", "E_i", ref=date(2024, 12, 1), cluster="item_code")
    pre = ev.filter(pl.col("k") < 0)
    post = ev.filter(pl.col("k") >= 1)  # exposure on from month 25 = 2025-02 (k = 2)
    assert pre["coef"].abs().max() < 0.002 * 10
    assert post.filter(pl.col("k") >= 2)["coef"].mean() == pytest.approx(1.0, abs=0.05)


def test_deseasonalise_removes_month_of_year_pattern():
    df = _sim(theta=0.0)
    sa = rd.deseasonalise(df, pre_end=date(2024, 12, 1))
    by = sa.with_columns(r=pl.col("ln_sa") - pl.col("ln_sa").mean().over("item_code"))
    # seasonal sd was 0.02; residual month-of-year means are close to the common shocks only
    moy = by.group_by("item_code", "moy").agg(pl.col("r").mean())["r"].std()
    raw = df.with_columns(r=pl.col("ln_p") - pl.col("ln_p").mean().over("item_code"))
    raw_moy = raw.group_by("item_code", "moy").agg(pl.col("r").mean())["r"].std()
    assert moy < raw_moy / 2


def test_high_low_series_indexed_to_base():
    df = pl.DataFrame({
        "item_code": ["a", "a", "b", "b"], "group": ["high", "high", "low", "low"],
        "month": [date(2025, 1, 1), date(2025, 6, 1)] * 2,
        "ln_sa": [1.0, 1.0 + math.log(1.05), 2.0, 2.0],
    })  # fmt: skip
    s = rd.high_low_series(df, base=date(2025, 1, 1))
    m = {(r["group"], r["month"]): r["index"] for r in s.iter_rows(named=True)}
    assert m[("high", date(2025, 1, 1))] == pytest.approx(100)
    assert m[("high", date(2025, 6, 1))] == pytest.approx(105)
    assert m[("low", date(2025, 6, 1))] == pytest.approx(100)

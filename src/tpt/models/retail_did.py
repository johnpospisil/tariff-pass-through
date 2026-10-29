"""Retail CPI difference-in-differences (P19).

CPI item indexes (U.S. city average, NSA) against the P18 tariff exposure of each item. E_it is
the item's monthly exposure (duty as a share of the consumer price under full pass-through; 0
before the base month), so theta = 1 means retail prices rose by the full duty cost of the
item's imports.

High-exposure goods (durables, apparel, electronics) were falling relative to low-exposure goods
(food, fuel) before both episodes, so the main specification measures each item against its own
pre-trend:

- main: ln_dt = theta * E_it + item FE + month FE, where ln_dt is the log index minus item
  month-of-year factors (estimated from 2015 to the December before the reference month) minus
  the item's linear trend fitted on the window's pre-period (2023-01..2024-12; 2016-01..2017-12)
  and extrapolated.
- trend_long: the trend fitted from 2015 instead. no_trend: ln P on E_it with item x
  month-of-year + month FE, no item trends (reported to show the pre-trend bias).
- diff12: 12-month log changes on 12-month exposure changes with item + month FE (item FE in
  differences absorb linear item trends).
- binary: top vs bottom tercile of window-mean exposure x post (from the first tariff month);
  `theta_equiv` divides by the terciles' exposure gap.
- event studies: window-mean exposure (continuous) or high tercile (binary) x month dummies,
  reference month Jan 2025 (Jan 2018), on the detrended index (trend "pre") and on the
  deseasonalised index without item trends ("none"), item + month FE.
- robustness: effective (collected-duty) exposure; BLS seasonally adjusted series; all items
  (services at zero exposure); the hand-mapped route; item clusters; 2025-26 to Jan 2026 (before
  the IEEPA ruling cut exposure: E_it assumes prices respond to tariff cuts as to increases).

Sample: leaf CPI goods items (at least half the item's P18 weight on goods; an item is dropped
when a more detailed item under it is in the sample). Windows: 2023-01 to the last exposure month
(2026-08) and 2016-01 to 2019-12. Unweighted. SEs clustered by expenditure class (first four
characters of the item code: items in a class share bridge lines, hence exposure).

October 2025: BLS collected no prices for most items (federal shutdown). Those months are
missing, not interpolated; regressions skip them and 12-month differences touching them drop
out. Counts in the run log and DATA.md.

Run: make retail-did  -> data/published/retail_did.csv, retail_event.csv, retail_high_low.csv
"""

import time
from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from tpt import config
from tpt.build import exposure as ex
from tpt.models import border_pt as bp

OUT = config.PUBLISHED_DIR / "retail_did.csv"
EVENT_OUT = config.PUBLISHED_DIR / "retail_event.csv"
HIGH_LOW_OUT = config.PUBLISHED_DIR / "retail_high_low.csv"
CPI = config.INTERIM_DIR / "bls" / "cpi.parquet"
SERIES = {"U": "CUUR0000", "S": "CUSR0000"}
FE_LEVELS = ("item_code^moy", "month_id")
FE_SA = ("item_code", "month_id")
FE_DIFF = ("item_code", "month_id")
CLUSTER = "exp_cls"
HISTORY_START = date(2015, 1, 1)  # seasonal factors: all CPI months before the reference year


@dataclass(frozen=True)
class Window:
    start: date
    end: date | None  # None: last exposure month
    ref: date  # event-study reference month
    post: date  # first tariff month (binary DiD)


PERIODS = {
    "2018_19": Window(date(2016, 1, 1), date(2019, 12, 1), date(2018, 1, 1), date(2018, 2, 1)),
    "2025_26": Window(date(2023, 1, 1), None, date(2025, 1, 1), date(2025, 2, 1)),
}


@dataclass(frozen=True)
class Spec:
    name: str
    design: str = "levels"  # levels, diff12, binary
    x: str = "exposure"  # exposure or exposure_eff
    route: str = "bea"
    seasonal: str = "U"
    items: str = "goods"  # goods or all
    cluster: str = CLUSTER
    trend: str = "pre"  # pre (window pre-period), long (from 2015), none
    end: date | None = None  # earlier window end (pre-ruling)
    periods: tuple[str, ...] = ("2018_19", "2025_26")

    @property
    def y(self) -> str:
        return {"pre": "ln_dt", "long": "ln_dt_long", "none": "ln_p"}[self.trend]

    @property
    def fe(self) -> tuple[str, ...]:
        return FE_LEVELS if self.trend == "none" and self.seasonal == "U" else FE_SA


SPECS = [
    Spec("main"),
    Spec("main_eff", x="exposure_eff"),
    Spec("trend_long", trend="long"),
    Spec("no_trend", trend="none"),
    Spec("diff12", design="diff12", trend="none"),
    Spec("diff12_eff", design="diff12", x="exposure_eff", trend="none"),
    Spec("binary", design="binary"),
    Spec("binary_no_trend", design="binary", trend="none"),
    Spec("sa", seasonal="S"),
    Spec("all_items", items="all"),
    Spec("hand", route="hand"),
    Spec("hand_eff", route="hand", x="exposure_eff"),
    Spec("cl_item", cluster="item_code"),
    Spec("pre_ruling", end=date(2026, 1, 1), periods=("2025_26",)),
    Spec("pre_ruling_eff", x="exposure_eff", end=date(2026, 1, 1), periods=("2025_26",)),
]


# --- sample ------------------------------------------------------------------------


def leaf_items(codes: list[str]) -> list[str]:
    """Drop items with a more detailed item of the list under them (SEHK when SEHK01 is in)."""
    s = sorted(set(codes))
    return [c for c in s if not any(o != c and o.startswith(c) for o in s)]


def terciles(summary: pl.DataFrame, col: str = "exposure") -> pl.DataFrame:
    """item_code -> low / mid / high tercile of window-mean exposure."""
    r = summary.select("item_code", q=pl.col(col).rank("ordinal") / pl.len())
    g = pl.when(pl.col("q") <= 1 / 3).then(pl.lit("low"))
    g = g.when(pl.col("q") <= 2 / 3).then(pl.lit("mid")).otherwise(pl.lit("high"))
    return r.select("item_code", group=g)


def drop_missing(df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Rows with an index value, and the count of missing ones by month (Oct 2025)."""
    miss = (
        df.filter(pl.col("value").is_null())
        .group_by("month")
        .agg(n_missing=pl.len().cast(pl.Int64))
        .sort("month")
    )
    return df.drop_nulls("value"), miss


def add_keys(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        moy=pl.col("month").dt.month(),
        month_id=pl.col("month").dt.strftime("%Y-%m"),
        exp_cls=pl.col("item_code").str.slice(0, 4),
    )


def diff12(df: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    """12-month differences d12_<col>, only where the month a year earlier exists."""
    lag = df.select("item_code", pl.col("month").dt.offset_by("12mo"), *cols)
    return df.join(lag, on=["item_code", "month"], suffix="_l").select(
        *[c for c in df.columns if c not in cols],
        *[(pl.col(c) - pl.col(f"{c}_l")).alias(f"d12_{c}") for c in cols],
    )


# --- estimators --------------------------------------------------------------------


def fit(df: pl.DataFrame, y: str, x: str, fe: tuple[str, ...], cluster: str = CLUSTER) -> dict:
    r = bp.fit_terms(df.drop_nulls([y, x]), y, [x], fe, cluster)[0]
    n_items = df.drop_nulls([y, x])["item_code"].n_unique()
    return {**r, "n_items": n_items,
            "n_clusters": df.drop_nulls([y, x])[cluster.split("+")[0]].n_unique()}  # fmt: skip


def _k_name(k: int) -> str:
    return f"ev_m{-k}" if k < 0 else f"ev_p{k}"


def event_study(df: pl.DataFrame, y: str, treat: str, ref: date, fe: tuple[str, ...] = FE_SA,
                cluster: str = CLUSTER) -> pl.DataFrame:  # fmt: skip
    """treat x month dummies (k = months from ref; ref omitted). Run on deseasonalised y with
    item + month FE: item x month-of-year FE would absorb any full year of the dummies."""
    k = (pl.col("month").dt.year() - ref.year) * 12 + pl.col("month").dt.month() - ref.month
    d = df.drop_nulls([y, treat]).with_columns(k=k)
    ks = sorted(set(d["k"].to_list()) - {0})
    d = d.with_columns(
        [(pl.col(treat) * (pl.col("k") == j)).cast(pl.Float64).alias(_k_name(j)) for j in ks]
    )
    rows = bp.fit_terms(d, y, [_k_name(j) for j in ks], fe, cluster)
    by = {r["term"]: r for r in rows}
    out = [{"k": j, **by[_k_name(j)]} for j in ks if _k_name(j) in by]
    out.append({"k": 0, "term": "ref", "coef": 0.0, "se": 0.0, "ci_low": 0.0, "ci_high": 0.0})
    return (
        pl.DataFrame(out, infer_schema_length=None)
        .sort("k")
        .with_columns(month=pl.lit(ref).dt.offset_by(pl.format("{}mo", pl.col("k"))))
    )


def seasonal_factors(hist: pl.DataFrame, pre_end: date, y: str = "ln_p") -> pl.DataFrame:
    """item x month-of-year effects from months <= pre_end: item OLS on a constant, a linear
    trend and month dummies; effects demeaned across the 12 months."""
    out = []
    pre = hist.filter(pl.col("month") <= pre_end).drop_nulls(y).sort("month")
    for (item,), g in pre.group_by("item_code", maintain_order=True):
        t = (g["month"].dt.year() * 12 + g["month"].dt.month()).to_numpy().astype(float)
        moy = g["month"].dt.month().to_numpy()
        dummies = np.stack([(moy == m).astype(float) for m in range(2, 13)], axis=1)
        X = np.column_stack([np.ones(len(t)), t - t.mean(), dummies])
        beta, *_ = np.linalg.lstsq(X, g[y].to_numpy(), rcond=None)
        eff = np.concatenate([[0.0], beta[2:]])
        out.append(pl.DataFrame({"item_code": item, "moy": np.arange(1, 13, dtype=np.int8),
                                 "seas": eff - eff.mean()}))  # fmt: skip
    return pl.concat(out)


def deseasonalise(df: pl.DataFrame, pre_end: date, y: str = "ln_p",
                  hist: pl.DataFrame | None = None) -> pl.DataFrame:  # fmt: skip
    """ln_sa = y minus item month-of-year effects estimated on hist (default df) to pre_end."""
    f = seasonal_factors(df if hist is None else hist, pre_end, y)
    return (
        df.join(f, on=["item_code", "moy"], how="left", coalesce=True)
        .with_columns(ln_sa=pl.col(y) - pl.col("seas").fill_null(0.0))
        .drop("seas")
    )


def detrend(df: pl.DataFrame, start: date, end: date, y: str = "ln_sa",
            out: str = "ln_dt", min_obs: int = 12) -> pl.DataFrame:  # fmt: skip
    """out = y minus the item's linear trend fitted on start..end and extrapolated (null for
    items with fewer than min_obs months there)."""
    t = pl.col("month").dt.year() * 12 + pl.col("month").dt.month()
    fit_on = df.filter(pl.col("month").is_between(start, end)).drop_nulls(y).with_columns(t=t)
    co = fit_on.group_by("item_code").agg(
        b=pl.cov("t", y) / pl.col("t").var(), tm=pl.col("t").mean(), ym=pl.col(y).mean(),
        n=pl.len(),
    ).filter(pl.col("n") >= min_obs)  # fmt: skip
    return (
        df.join(co, on="item_code", how="left")
        .with_columns(
            (pl.col(y) - pl.col("ym") - pl.col("b") * (t - pl.col("tm"))).alias(out)
        )  # fmt: skip
        .drop("b", "tm", "ym", "n")
    )


def high_low_series(df: pl.DataFrame, base: date, y: str = "ln_sa") -> pl.DataFrame:
    """Mean across items of the log index relative to base, by group; index = 100 at base."""
    b = df.filter(pl.col("month") == base).drop_nulls(y).select("item_code", b=y)
    return (
        df.drop_nulls(y)
        .join(b, on="item_code")
        .group_by("group", "month")
        .agg(rel=(pl.col(y) - pl.col("b")).mean(), n_items=pl.col("item_code").n_unique())
        .with_columns(index=100 * pl.col("rel").exp())
        .sort("group", "month")
    )


# --- data --------------------------------------------------------------------------


def cpi(seasonal: str, items: list[str], start: date, end: date) -> pl.DataFrame:
    prefix = SERIES[seasonal]
    return (
        pl.scan_parquet(CPI)
        .filter(
            pl.col("series_id").is_in([prefix + i for i in items]),
            pl.col("month").is_between(start, end),
        )  # fmt: skip
        .select(
            item_code=pl.col("series_id").str.strip_prefix(prefix), month="month", value="value"
        )  # fmt: skip
        .collect()
    )


def sample_items(period: str, route: str, items: str) -> pl.DataFrame:
    """Window-mean exposure of the period's leaf items (P18 summary)."""
    s = pl.read_parquet(ex.OUT).filter(pl.col("period") == period, pl.col("route") == route)
    if items == "goods":
        s = s.filter(pl.col("goods_weight") >= ex.GOODS_ITEM_MIN)
    return s.filter(pl.col("item_code").is_in(leaf_items(s["item_code"].to_list())))


def panel(period: str, spec: Spec) -> tuple[pl.DataFrame, pl.DataFrame, Window]:
    """item x month in the window: ln_p, ln_sa (deseasonalised; = ln_p for SA series), ln_dt and
    ln_dt_long (minus the item's pre-period / long trend), E_it (exposure, exposure_eff; 0 before
    the base month), window-mean exposure E_i and tercile group; and missing-value counts."""
    w = PERIODS[period]
    mon = pl.read_parquet(ex.MONTHLY_OUT).filter(
        pl.col("period") == period, pl.col("route") == spec.route
    )
    end = min(d for d in (w.end, mon["month"].max(), spec.end) if d is not None)
    w = Window(w.start, end, w.ref, w.post)
    pre_end = date(w.ref.year - 1, 12, 1)
    items = sample_items(period, spec.route, spec.items)
    raw = cpi(spec.seasonal, items["item_code"].to_list(), HISTORY_START, end)
    _, missing = drop_missing(raw.filter(pl.col("month") >= w.start))
    hist = add_keys(drop_missing(raw)[0].with_columns(ln_p=pl.col("value").log()))
    if spec.seasonal == "U":
        hist = deseasonalise(hist, pre_end=pre_end)
    else:
        hist = hist.with_columns(ln_sa=pl.col("ln_p"))
    hist = detrend(hist, w.start, pre_end).pipe(detrend, HISTORY_START, pre_end, out="ln_dt_long")
    e = mon.select("item_code", "month", "exposure", "exposure_eff")
    df = (
        hist.filter(pl.col("month") >= w.start)
        .join(e, on=["item_code", "month"], how="left")
        .with_columns(pl.col("exposure", "exposure_eff").fill_null(0.0))
        .join(items.select("item_code", E_i="exposure"), on="item_code")
        .join(terciles(items), on="item_code")
    )
    return df, missing, w


# --- run ---------------------------------------------------------------------------


def _border(period: str) -> dict:
    """Border duty-inclusive coefficients (P16): statutory main and, 2025-26, implied-rate IV."""
    if not bp.PT_OUT.exists():
        return {}
    b = pl.read_csv(bp.PT_OUT).filter(pl.col("period") == period, pl.col("outcome") == "uv_dut",
                                      pl.col("group") == "all")  # fmt: skip
    get = {r["spec"]: r["coef"] for r in b.iter_rows(named=True)}
    return {"border_dut_stat": get.get("main"), "border_dut_iv": get.get("implied_iv")}


def run_spec(period: str, spec: Spec) -> dict:
    df, _, w = panel(period, spec)
    x = spec.x
    if spec.design == "levels":
        r = fit(df, spec.y, x, spec.fe, spec.cluster)
    elif spec.design == "diff12":
        r = fit(diff12(df, ["ln_p", x]), "d12_ln_p", f"d12_{x}", FE_DIFF, spec.cluster)
    else:
        d = df.filter(pl.col("group") != "mid").with_columns(
            high_post=((pl.col("group") == "high") & (pl.col("month") >= w.post)).cast(pl.Float64)
        )
        r = fit(d, spec.y, "high_post", spec.fe, spec.cluster)
        gap = d.group_by("group").agg(pl.col("E_i").mean())
        g = dict(gap.iter_rows())
        r["exposure_gap"] = g["high"] - g["low"]
        r["theta_equiv"] = r["coef"] / r["exposure_gap"]
    return {"period": period, "spec": spec.name, "design": spec.design, "x": x,
            "route": spec.route, "seasonal": spec.seasonal, "items": spec.items,
            "trend": spec.trend, **r,
            "start": w.start, "end": w.end}  # fmt: skip


def run() -> pl.DataFrame:
    t0 = time.time()
    rows, events, series = [], [], []
    for period in PERIODS:
        main, missing, w = panel(period, SPECS[0])
        if missing.height:
            gaps = ", ".join(f"{r['month']} {r['n_missing']}"
                             for r in missing.iter_rows(named=True))  # fmt: skip
            print(f"{period}: missing index values (not filled): {gaps}", flush=True)
        print(f"{period}: {main['item_code'].n_unique()} leaf goods items, "
              f"{main[CLUSTER].n_unique()} classes, {main.height:,} item-months "
              f"{w.start}..{w.end}", flush=True)  # fmt: skip
        border = _border(period)
        for spec in (s for s in SPECS if period in s.periods):
            r = run_spec(period, spec) | border
            rows.append(r)
            print(f"  {period} {spec.name:<11} theta = {r['coef']:+.3f} ({r['se']:.3f})  "
                  f"items = {r['n_items']}  n = {r['n']:,}  {time.time() - t0:.0f}s",
                  flush=True)  # fmt: skip
        hi = main.filter(pl.col("group") != "mid").with_columns(
            high=(pl.col("group") == "high").cast(pl.Float64)
        )
        for trend, y in (("pre", "ln_dt"), ("none", "ln_sa")):
            for design, treat, d in (("continuous", "E_i", main), ("binary", "high", hi)):
                ev = event_study(d, y, treat, w.ref)
                events.append(ev.with_columns(period=pl.lit(period), design=pl.lit(design),
                                              trend=pl.lit(trend)))  # fmt: skip
        s_sa = high_low_series(main, base=w.ref)
        s_dt = high_low_series(main, base=w.ref, y="ln_dt").select(
            "group", "month", index_dt="index"
        )
        series.append(s_sa.join(s_dt, on=["group", "month"], how="left")
                      .with_columns(period=pl.lit(period)))  # fmt: skip

    # Retail theta over the border duty-inclusive response on the same duty measure: statutory
    # exposure vs the statutory border coefficient; effective exposure vs the implied-rate IV.
    theta = pl.coalesce("theta_equiv", "coef")
    border = (
        pl.when(pl.col("x") == "exposure_eff").then("border_dut_iv").otherwise("border_dut_stat")
    )
    est = pl.DataFrame(rows, infer_schema_length=None).with_columns(retail_vs_border=theta / border)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    est.write_csv(OUT, float_precision=5)
    pl.concat(events, how="diagonal").write_csv(EVENT_OUT, float_precision=5)
    pl.concat(series).write_csv(HIGH_LOW_OUT, float_precision=5)
    print(f"wrote {OUT.name}, {EVENT_OUT.name}, {HIGH_LOW_OUT.name} ({time.time() - t0:.0f}s)",
          flush=True)  # fmt: skip
    return est


if __name__ == "__main__":
    run()

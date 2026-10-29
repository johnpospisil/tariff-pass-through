"""Robustness grid for border pass-through (P17).

Every variant of the P16 main specification (12-month changes on dln(1 + tau), HS6 x month +
country x month FE, HS8 clusters) under every unit-value cleaning rule, for 2018-19 and 2025-26,
pre-duty unit value and quantity:

- cleaning: w1 (1/99 winsorised, the published panel), w5 (5/95 winsorised), trim1 (rows with a
  unit-value change outside the 1/99 bounds dropped, P12 "trim" mode), trim3 (unit-value ratio
  beyond 3 dropped, ARW). Bounds are pooled over the whole panel's price sample, as in P12;
  trims use the unit-value change for every outcome.
- variants: alternative FE (HS8 x month), clustering (HS6, HS8 + country, country), weights
  (import value 12 months earlier), dropping China, dropping Section 232 products (any S232 rate
  in the change or its base, any country), excluding front-running months (k = -6..-1 before a
  variety's first increase; and also k = 6..11, whose 12-month base was a front-run month), a
  single year (2018 / 2025) and, for 2025-26, the pre-ruling window (to 2026-01).

flag_moves marks variants that move beta by more than the same-cleaning baseline's SE, and
cleaning rules that move it by more than the main SE.

Run: make robustness (writes data/published/robustness.csv)
"""

import math
import time
from dataclasses import dataclass, field
from datetime import date

import polars as pl

from tpt import config
from tpt.build.import_panel import OUT as PANEL
from tpt.models import border_pt as bp

OUT = config.PUBLISHED_DIR / "robustness.csv"
OUTCOMES = {"uv": "dln_uv", "qty": "dln_qty"}
CLEANING = {
    "w1": "Winsorise 1/99 (main)",
    "w5": "Winsorise 5/95",
    "trim1": "Trim 1/99",
    "trim3": "Trim ratio > 3 (ARW)",
}
QUANTILES = {"w1": (0.01, 0.99), "w5": (0.05, 0.95), "trim1": (0.01, 0.99)}
FRONTRUN = (-6, -1)  # months before a variety's first increase
MAIN_FE = ("hs6^ym", "cty_code^ym")


@dataclass(frozen=True)
class Variant:
    name: str
    label: str
    fe: tuple[str, ...] = MAIN_FE
    cluster: str = "hs8"
    weights: str | None = None
    keep: str | None = None  # china, s232, frontrun, frontrun_base
    windows: dict = field(default_factory=dict, compare=False, hash=False)
    periods: tuple[str, ...] = ("2018_19", "2025_26")


VARIANTS = [
    Variant("baseline", "Main specification"),
    Variant("fe_hs8", "HS8 × month FE", fe=("hs8^ym", "cty_code^ym")),
    Variant("cl_hs6", "Cluster HS6", cluster="hs6"),
    Variant("cl_twoway", "Cluster HS8 + country", cluster="hs8+cty_code"),
    Variant("cl_country", "Cluster country", cluster="cty_code"),
    Variant("weighted", "Weighted by import value", weights="con_val_b"),
    Variant("drop_china", "Drop China", keep="china"),
    Variant("drop_s232", "Drop Section 232 products", keep="s232"),
    Variant("excl_frontrun", "Drop front-run months", keep="frontrun"),
    Variant("excl_frontrun_base", "Also drop front-run base months", keep="frontrun_base"),
    Variant(
        "window_year",
        "Single year (2018 / 2025)",
        windows={
            "2018_19": (date(2018, 1, 1), date(2018, 12, 1)),
            "2025_26": (date(2025, 1, 1), date(2025, 12, 1)),
        },
    ),  # fmt: skip
    Variant(
        "pre_ruling",
        "To Jan 2026 (before the IEEPA ruling)",
        windows={"2025_26": (date(2024, 1, 1), date(2026, 1, 1))},
        periods=("2025_26",),
    ),  # fmt: skip
]


@dataclass(frozen=True)
class GridSpec:
    cleaning: str
    variant: Variant


def grid(period: str) -> list[GridSpec]:
    return [GridSpec(c, v) for v in VARIANTS if period in v.periods for c in CLEANING]


def panel_bounds() -> dict[tuple[float, float], dict[str, tuple[float, float]]]:
    """Quantiles of the raw 12-month changes over the whole panel's price sample (as P12)."""
    qs = set(QUANTILES.values())
    cols = list(OUTCOMES.values())
    q = (
        pl.scan_parquet(PANEL)
        .filter(pl.col("drop_reason").is_null())
        .select(
            pl.col(f"{c}_raw").quantile(p).alias(f"{c}|{p}")
            for c in cols
            for lo_hi in qs
            for p in lo_hi
        )  # fmt: skip
        .collect()
    )
    return {(lo, hi): {c: (q[f"{c}|{lo}"][0], q[f"{c}|{hi}"][0]) for c in cols}
            for lo, hi in qs}  # fmt: skip


def clean(df: pl.DataFrame, rule: str, y: str, bounds: dict) -> tuple[pl.DataFrame, str]:
    """Apply a cleaning rule for outcome y; returns the sample and the column to regress."""
    raw = f"{y}_raw"
    if rule == "w1":
        return df.filter(pl.col(y).is_not_null()), y
    if rule == "w5":
        lo, hi = bounds[QUANTILES["w5"]][y]
        return df.filter(pl.col(raw).is_not_null()).with_columns(pl.col(raw).clip(lo, hi)), raw
    if rule == "trim1":
        lo, hi = bounds[QUANTILES["trim1"]]["dln_uv"]
        keep = pl.col("dln_uv_raw").is_between(lo, hi)
    elif rule == "trim3":
        keep = pl.col("dln_uv_raw").abs() <= math.log(3)
    else:
        raise ValueError(f"unknown cleaning rule {rule!r}")
    return df.filter(keep, pl.col(raw).is_not_null()), raw


def keep_frontrun(base: bool) -> pl.Expr:
    """True for rows outside the front-run months (k = -6..-1); with base, also outside k = 6..11
    (the 12-month base was a front-run month)."""
    k = pl.col("k")
    out = ~k.is_between(*FRONTRUN)
    if base:
        out = out & ~k.is_between(FRONTRUN[0] + 12, FRONTRUN[1] + 12)
    return out.fill_null(True)


def drop_s232(df: pl.DataFrame) -> pl.DataFrame:
    """Drop products with a Section 232 rate in any row (change month or its base, any country)."""
    hit = (pl.col("rate_s232").fill_null(0) > 0) | (pl.col("rate_s232_b").fill_null(0) > 0)
    products = df.filter(hit).select("prod_id").unique()
    return df.join(products, on="prod_id", how="anti")


def apply_variant(df: pl.DataFrame, v: Variant, period: str,
                  months: tuple[date, date]) -> tuple[pl.DataFrame, tuple[date, date]]:  # fmt: skip
    months = v.windows.get(period, months)
    s = df.filter(pl.col("month").is_between(*months))
    if v.keep == "china":
        s = s.filter(pl.col("cty_code") != "5700")
    elif v.keep == "s232":
        s = drop_s232(s)
    elif v.keep in ("frontrun", "frontrun_base"):
        s = s.filter(keep_frontrun(base=v.keep == "frontrun_base"))
    if v.weights:
        s = s.filter(pl.col(v.weights) > 0)
    return s, months


def flag_moves(est: pl.DataFrame) -> pl.DataFrame:
    """delta / moves_beta: vs the baseline under the same cleaning rule (|delta| > its SE);
    delta_vs_main / moves_vs_main: vs the main specification (w1 baseline)."""
    keys = ["period", "outcome"]
    base = est.filter(pl.col("variant") == "baseline").select(
        *keys, "cleaning", base_coef="coef", base_se="se"
    )
    main = est.filter(pl.col("variant") == "baseline", pl.col("cleaning") == "w1").select(
        *keys, main_coef="coef", main_se="se"
    )
    return (
        est.join(base, on=[*keys, "cleaning"], how="left")
        .join(main, on=keys, how="left")
        .with_columns(
            delta=pl.col("coef") - pl.col("base_coef"),
            delta_vs_main=pl.col("coef") - pl.col("main_coef"),
        )  # fmt: skip
        .with_columns(
            moves_beta=pl.col("delta").abs() > pl.col("base_se"),
            moves_vs_main=pl.col("delta_vs_main").abs() > pl.col("main_se"),
        )  # fmt: skip
        .drop("base_coef", "main_coef")
    )


def run() -> pl.DataFrame:
    t0 = time.time()
    bounds = panel_bounds()
    print("bounds: " + "  ".join(f"{q}: uv {b['dln_uv'][0]:+.2f}/{b['dln_uv'][1]:+.2f}"
                                 for q, b in bounds.items()), flush=True)  # fmt: skip
    rows = []
    n = sum(len(grid(p)) for p in bp.PERIODS) * len(OUTCOMES)
    i = 0
    for period in bp.PERIODS:
        df, months = bp.load_pt(period)
        df = df.filter(pl.col("drop_reason").is_null())
        print(f"{period}: {df.height:,} price rows ({time.time() - t0:.0f}s)", flush=True)
        for spec in grid(period):
            v = spec.variant
            s, m = apply_variant(df, v, period, months)
            for o, y in OUTCOMES.items():
                i += 1
                d, ycol = clean(s, spec.cleaning, y, bounds)
                r = bp.fit_terms(d, ycol, [bp.X], v.fe, v.cluster, weights=v.weights)[0]
                rows.append({"period": period, "outcome": o, "cleaning": spec.cleaning,
                             "variant": v.name, "label": v.label, **r, "weights": v.weights,
                             "start": m[0], "end": m[1]})  # fmt: skip
                print(f"[{i:>3}/{n}] {period} {o:<4} {spec.cleaning:<6} {v.name:<19} "
                      f"b = {r['coef']:+.3f} ({r['se']:.3f})  n = {r['n']:,}  "
                      f"{time.time() - t0:.0f}s", flush=True)  # fmt: skip
    est = flag_moves(pl.DataFrame(rows, infer_schema_length=None))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    est.write_csv(OUT, float_precision=5)
    return est


if __name__ == "__main__":
    run()

"""Border pass-through regressions (P15, P16).

Static design (Amiti-Redding-Weinstein): 12-month log change of an outcome on the 12-month change
in ln(1 + tau), tau the statutory additional duty (P10), at HS10-family x country x month (P12):

    dln y_ijt = FE + beta * dln(1 + tau_ijt) + e_ijt

Outcomes: pre-duty unit value (beta = 0: US buyers pay the full tariff; beta = -1: foreign
exporters absorb it), duty-inclusive unit value (built from duties actually collected, so not
exactly 1 + beta), quantity and value. Price outcomes use the P12 price sample (drop_reason null);
value uses every row with a 12-month base and comparable product codes, with or without quantity.

Specs (REPLICATION, 2018-19):
- main: HS6 x month + country x month FE, SEs clustered by HS8 (CLAUDE.md); twoway: same, clustered
  by HS8 and country.
- main_trim3: main FE on unwinsorised changes with ARW's outlier rule (unit-value ratio vs 12
  months earlier beyond 3 or 1/3 dropped). The 1/99 winsor bounds are +/-4.2 log points (70x), so
  winsorising keeps the composition jumps that dominate the unit-value estimate in 2018-19 (P15
  diagnosis, DATA.md); 19% of price-sample rows exceed the ratio.
- arw: as in ARW (2019) Table 1: 2018 only (changes vs 2017), HS10 product FE + country x year
  FE, unwinsorised changes, unit-value ratios beyond 3 dropped for price outcomes, HS8 clusters.
- fgkk: as in Fajgelbaum et al. (2020) Table IV: 2018-01..2019-04, product x month, country x
  month and country x sector (HS2 here; theirs is NAICS) FE, two-way clusters (country, HS8).

Event study (Fajgelbaum et al. 2020, eq. 1), in levels 2017-19:

    ln y_igt = a_ig + a_gt + a_it + sum_k b_k 1(k_igt = k) x target_ig + e_igt

variety (product x country x unit), HS6 x month and country x month FE; k = months since the
first tariff increase of the variety (half-rate rule, as their 15th-of-month cutoff), binned at
+6, targeted observations before -6 dropped, k = -1 the reference; untargeted varieties are the
controls (all dummies 0). Clusters: HS8.

2025-26 (P16, DESIGNS): the same static design on 12-month changes 2024-01..latest and 2018-19,
plus pre_ruling (to 2026-01), implied rates (OLS, and IV with the statutory change), and
Delta ln(1 + tau) interacted with country, China, authority (split by authority), Rauch class and
months since the first tariff increase; each heterogeneity design also with the ARW trim. MXP
cross-check: BLS locality-of-origin import prices on our locality tariff changes. 2025-26 event
study: steps over each variety's Dec 2024 rate (event_months base/start, no half-rate rule).

Run: make models, or python -m tpt.models.border_pt static|events|pt|events25 (writes
data/published/border_pt_replication.csv, border_pt_event_2018_19.csv, border_pt.csv,
border_pt_mxp.csv, border_pt_event_2025_26.csv)
"""

import math
import sys
import time
from dataclasses import dataclass, field
from datetime import date

import polars as pl
import pyfixest as pf

from tpt import config
from tpt.build.import_panel import OUT as PANEL

OUT = config.PUBLISHED_DIR / "border_pt_replication.csv"
EVENT_OUT = config.PUBLISHED_DIR / "border_pt_event_2018_19.csv"
X = "dln_1p_tau_stat"
OUTCOMES = {"uv": "dln_uv", "uv_dut": "dln_uv_dut", "qty": "dln_qty", "val": "dln_val"}
PRICE = {"dln_uv", "dln_uv_dut", "dln_qty"}
VALUE_REASONS = ("no_quantity", "unit_change", "mixed_units")  # value change still comparable
LEVEL_DROP = ("special_provision", "duty_outlier", "mixed_units")
EVENT_WINDOW = (-6, 6)  # binned at the top, dropped below
MIN_STEP = 0.025  # smallest monthly rate counted as a tariff increase (event studies)
# fgkk: their sample (2017-01..2019-04, before List 4A); full: through 2019, where the run-up to
# the September 2019 actions shows as a pre-trend in quantities (P15, DATA.md)
EVENT_SAMPLES = {"fgkk": (date(2017, 1, 1), date(2019, 4, 1)),
                 "full": (date(2017, 1, 1), date(2019, 12, 1))}  # fmt: skip
EVENT_COLS = [f"ev_{'m' if k < 0 else ''}{abs(k)}" for k in range(EVENT_WINDOW[0], 7) if k != -1]


@dataclass(frozen=True)
class Spec:
    name: str
    y: str
    fe: tuple[str, ...]
    cluster: str = "hs8"
    months: tuple[date, date] = (date(2018, 1, 1), date(2019, 12, 1))
    trim: float | None = None  # drop |dln uv| > ln(trim) (ARW)
    x: str = X
    note: str = ""
    label: str = field(default="", compare=False)


def _specs() -> list[Spec]:
    out = []
    for o, y in OUTCOMES.items():
        out.append(Spec("main", y, ("hs6^ym", "cty_code^ym"), label=o))
        out.append(Spec("twoway", y, ("hs6^ym", "cty_code^ym"), "hs8+cty_code", label=o))
    for o in ("uv", "uv_dut", "qty"):
        out.append(Spec("main_trim3", f"{OUTCOMES[o]}_raw", ("hs6^ym", "cty_code^ym"),
                        trim=3.0, label=o))  # fmt: skip
    for o in ("uv", "qty", "val"):
        out.append(Spec("arw", f"{OUTCOMES[o]}_raw", ("prod_id", "cty_code^year"),
                        months=(date(2018, 1, 1), date(2018, 12, 1)),
                        trim=None if o == "val" else 3.0, label=o))  # fmt: skip
    for o in ("uv", "uv_dut", "qty", "val"):
        out.append(Spec("fgkk", OUTCOMES[o], ("prod_id^ym", "cty_code^ym", "cty_code^hs2"),
                        "hs8+cty_code", months=(date(2018, 1, 1), date(2019, 4, 1)),
                        label=o))  # fmt: skip
    return out


REPLICATION = _specs()
# Published estimates (pre-duty unit value, quantity, value) used by the P15 gate.
PUBLISHED = {
    "arw": {"source": "Amiti, Redding and Weinstein (2019), NBER w25672 Table 1",
            "uv": (-0.003, 0.024), "qty": (-1.299, 0.094), "val": (-1.380, 0.090)},
    "fgkk": {"source": "Fajgelbaum, Goldberg, Kennedy and Khandelwal (2020), QJE Table IV",
             "uv": (0.00, 0.08), "qty": (-1.47, 0.24), "val": (-1.52, 0.18),
             "uv_dut": (0.58, 0.13)},
}  # fmt: skip


# --- data -----------------------------------------------------------------------


def add_keys(df: pl.DataFrame) -> pl.DataFrame:
    """HS2/6/8 from the product id (family ids are 'F' + an HS10 member), month and year keys."""
    code = pl.when(pl.col("level") == "family").then(pl.col("prod_id").str.slice(1))
    code = code.otherwise(pl.col("prod_id"))
    return df.with_columns(
        hs2=code.str.slice(0, 2), hs6=code.str.slice(0, 6), hs8=code.str.slice(0, 8),
        ym=pl.col("month").dt.strftime("%Y-%m"), year=pl.col("month").dt.year(),
    )  # fmt: skip


def trim_ratio(df: pl.DataFrame, ratio: float) -> pl.DataFrame:
    return df.filter(pl.col("dln_uv_raw").abs() <= math.log(ratio))


def load_changes(months: tuple[date, date]) -> pl.DataFrame:
    keep = pl.col("drop_reason").is_null() | pl.col("drop_reason").is_in(VALUE_REASONS)
    cols = ["prod_id", "level", "cty_code", "month", "drop_reason", X, "dln_1p_tau_eff",
            *OUTCOMES.values(), *(f"{c}_raw" for c in OUTCOMES.values())]  # fmt: skip
    df = (
        pl.scan_parquet(PANEL)
        .filter(pl.col("month").is_between(*months), keep, pl.col(X).is_not_null())
        .select(cols)
        .collect()
    )
    return add_keys(df)


def sample(df: pl.DataFrame, spec: Spec) -> pl.DataFrame:
    s = df.filter(pl.col("month").is_between(*spec.months), pl.col(spec.y).is_not_null())
    if spec.y.removesuffix("_raw") in PRICE:
        s = s.filter(pl.col("drop_reason").is_null())
    if spec.trim is not None:
        s = trim_ratio(s, spec.trim)
    return s


# --- static regressions ---------------------------------------------------------


def fit(df: pl.DataFrame, spec: Spec) -> dict:
    keys = {f for fe in spec.fe for f in fe.split("^")} | set(spec.cluster.split("+"))
    data = df.select(spec.y, spec.x, *keys).to_pandas()
    m = pf.feols(f"{spec.y} ~ {spec.x} | {' + '.join(spec.fe)}", data=data,
                 vcov={"CRV1": spec.cluster})  # fmt: skip
    t = m.tidy().loc[spec.x]
    return {
        "coef": float(t["Estimate"]), "se": float(t["Std. Error"]),
        "ci_low": float(t["2.5%"]), "ci_high": float(t["97.5%"]), "n": int(m._N),
        "r2": float(m._r2), "fe": " + ".join(spec.fe), "cluster": spec.cluster,
    }  # fmt: skip


# --- event study ----------------------------------------------------------------


def event_months(df: pl.DataFrame, base: pl.DataFrame | None = None, start: date | None = None,
                 half_rule: bool = True) -> pl.DataFrame:  # fmt: skip
    """First month of a tariff increase per variety: rate >= MIN_STEP and at least half the next
    month's rate (a day-weighted month is >= half the new rate iff the change took effect by
    about the 15th). df: prod_id, cty_code, month, stat_rate (monthly, sorted per variety).

    base (prod_id, cty_code, base_rate): measure steps over the variety's base rate (2025: China
    already paid Section 301 duties); varieties without a base are dropped. start: earliest event
    month. half_rule=False for 2025, when rates rose in successive monthly steps (China: Feb, Mar,
    Apr) and the rule would push events to the last step; nearly all 2025 actions took effect in
    the first 12 days of a month (DATA.md)."""
    step = pl.col("stat_rate")
    if base is not None:
        df = df.join(base, on=["prod_id", "cty_code"], how="inner")
        step = step - pl.col("base_rate")
    hit = step >= MIN_STEP
    if half_rule:
        nxt = step.shift(-1).over("prod_id", "cty_code", order_by="month")
        hit = hit & (step >= 0.5 * nxt.fill_null(0))
    if start is not None:
        hit = hit & (pl.col("month") >= start)
    return (
        df.filter(hit.fill_null(False))
        .group_by("prod_id", "cty_code")
        .agg(event=pl.col("month").min())
    )


def event_dummies(df: pl.DataFrame, events: pl.DataFrame) -> pl.DataFrame:
    lo, hi = EVENT_WINDOW
    months = pl.col("month").dt.year() * 12 + pl.col("month").dt.month()
    ev = pl.col("event").dt.year() * 12 + pl.col("event").dt.month()
    out = (
        df.join(events, on=["prod_id", "cty_code"], how="left")
        .with_columns(k=months - ev)
        .filter(pl.col("k").is_null() | (pl.col("k") >= lo))
        .with_columns(pl.col("k").clip(upper_bound=hi))
    )
    dummies = [
        (pl.col("k") == k).fill_null(False).cast(pl.Int8).alias(c)
        for k, c in zip([k for k in range(lo, hi + 1) if k != -1], EVENT_COLS, strict=True)
    ]
    return out.with_columns(dummies).drop("event")


def event_study(df: pl.DataFrame, y: str, fe: tuple[str, ...] = ("variety", "hs6^ym",
                "cty_code^ym"), cluster: str = "hs8",
                events: pl.DataFrame | None = None) -> pl.DataFrame:  # fmt: skip
    """df: add_keys(levels) with y and stat_rate; events: event_months(df) by default.
    Returns k, coef, se, ci_low, ci_high, n."""
    events = event_months(df) if events is None else events
    d = event_dummies(df, events).with_columns(
        variety=pl.concat_str(
            "prod_id", "cty_code", *(["unit"] if "unit" in df.columns else []), separator="|"
        )  # fmt: skip
    )
    keys = {f for e in fe for f in e.split("^")} | set(cluster.split("+"))
    data = d.select(y, *EVENT_COLS, *keys).to_pandas()
    m = pf.feols(f"{y} ~ {' + '.join(EVENT_COLS)} | {' + '.join(fe)}", data=data,
                 vcov={"CRV1": cluster})  # fmt: skip
    t = m.tidy()
    ks = [k for k in range(EVENT_WINDOW[0], EVENT_WINDOW[1] + 1) if k != -1]
    rows = [
        {"k": k, "coef": float(t.loc[c, "Estimate"]), "se": float(t.loc[c, "Std. Error"]),
         "ci_low": float(t.loc[c, "2.5%"]), "ci_high": float(t.loc[c, "97.5%"])}
        for k, c in zip(ks, EVENT_COLS, strict=True)
    ]  # fmt: skip
    rows.append({"k": -1, "coef": 0.0, "se": 0.0, "ci_low": 0.0, "ci_high": 0.0})
    targeted = d.filter(pl.col("k").is_not_null())
    return (
        pl.DataFrame(rows)
        .sort("k")
        .with_columns(
            n=pl.lit(int(m._N)), varieties_targeted=pl.lit(targeted.select("variety").n_unique())
        )
    )


def load_levels(months: tuple[date, date]) -> pl.DataFrame:
    """Levels for the event study: positive quantity in a quantity unit, comparable products."""
    df = (
        pl.scan_parquet(PANEL)
        .filter(
            pl.col("month").is_between(*months), pl.col("qty") > 0,
            ~pl.col("unit").is_in(["X", "-"]),
            pl.col("drop_reason").is_null() | ~pl.col("drop_reason").is_in(LEVEL_DROP),
        )
        .select("prod_id", "level", "cty_code", "month", "unit", "stat_rate",
                ln_uv=pl.col("unit_value").log(), ln_uv_dut=pl.col("uv_duty_incl").log(),
                ln_qty=pl.col("qty").log(), ln_val=pl.col("con_val").log())
        .collect()
    )  # fmt: skip
    return add_keys(df)


# --- 2025-26 and heterogeneity (P16) ----------------------------------------------

PT_OUT = config.PUBLISHED_DIR / "border_pt.csv"
EVENT25_OUT = config.PUBLISHED_DIR / "border_pt_event_2025_26.csv"
MXP_OUT = config.PUBLISHED_DIR / "border_pt_mxp.csv"
X_EFF = "dln_1p_tau_eff"  # implied rate: calculated duties / customs value
# 12-month changes; 2025_26 runs to the latest month. RULING: IEEPA duties struck down
# 2026-02-20, collection ended 2026-02-24 (EO 14389; DATA.md), so pre_ruling ends 2026-01.
PERIODS = {"2018_19": (date(2018, 1, 1), date(2019, 12, 1)), "2025_26": (date(2024, 1, 1), None)}
RULING = date(2026, 2, 1)
AUTHORITY = {
    "s232": ("rate_s232",),
    "ieepa": ("rate_ieepa_fentanyl", "rate_ieepa_reciprocal", "rate_ieepa_other"),
    "s301": ("rate_s301",),  # China lists; from 2026-07 also the forced-labor and Brazil actions
    "other": ("rate_s201", "rate_s122", "rate_s338"),
}  # fmt: skip
RATE_COLS = [c for cols in AUTHORITY.values() for c in cols]
COUNTRY = {"5700": "china", "1220": "canada", "2010": "mexico"}
TIME_BINS = ((0, 2), (3, 5), (6, 8), (9, 11))  # months since the first increase; then m12p
# Event dating per period (time-since bins and event study): base month for 2025 steps
EVENT_SETUP = {
    "2018_19": {"from": date(2017, 1, 1), "base_month": None, "start": None, "half_rule": True},
    "2025_26": {"from": date(2024, 1, 1), "base_month": date(2024, 12, 1),
                "start": date(2025, 1, 1), "half_rule": False},
}  # fmt: skip
EVENT25_SAMPLES = {"pre_ruling": (date(2023, 1, 1), date(2026, 1, 1)),
                   "full": (date(2023, 1, 1), None)}  # fmt: skip
# BLS locality-of-origin import price indexes (all industries, NSA, before duties)
EU27 = "EU27"
ASEAN = ["5460", "5490", "5520", "5530", "5550", "5570", "5590", "5600", "5610", "5650"]
MXP_LOCALITIES = {
    "EIUCOCHNTOT": ("China", ["5700"]), "EIUCOCANTOT": ("Canada", ["1220"]),
    "EIUCOMEXTOT": ("Mexico", ["2010"]), "EIUCOJPNTOT": ("Japan", ["5880"]),
    "EIUCOUKTOT": ("United Kingdom", ["4120"]), "EIUCOTWNTOT": ("Taiwan", ["5830"]),
    "EIUCOEECTOT": ("European Union", EU27), "EIUCOASEANTOT": ("ASEAN", ASEAN),
}  # fmt: skip


@dataclass(frozen=True)
class Design:
    """One row family of border_pt.csv: outcomes regressed on X, or on X split into terms."""

    name: str
    outcomes: tuple[str, ...] = ("uv", "uv_dut", "qty")
    split: str | None = None  # country, china, authority, rauch, tbin
    trim: float | None = None
    cluster: str = "hs8"
    x: str = X
    iv: str | None = None  # instrument for x (single endogenous regressor)
    end: date | None = None
    periods: tuple[str, ...] = ("2018_19", "2025_26")
    fe: tuple[str, ...] = ("hs6^ym", "cty_code^ym")
    note: str = ""


ALL4 = ("uv", "uv_dut", "qty", "val")
IMPLIED = (
    "implied rate (duties/value) is endogenous: specific duties and composition move it "
    "with unit values; IV uses the statutory change"
)
DESIGNS = [
    Design("main", ALL4),
    Design("twoway", ALL4, cluster="hs8+cty_code"),
    Design("main_trim3", trim=3.0, note="unwinsorised, unit-value ratio beyond 3 dropped (ARW)"),
    Design("pre_ruling", ALL4, end=RULING.replace(month=1), periods=("2025_26",),
           note="to 2026-01, before IEEPA duties ended"),
    Design("implied_ols", x=X_EFF, note=IMPLIED),
    Design("implied_iv", x=X_EFF, iv=X, note=IMPLIED),
] + [
    d
    for split in ("country", "china", "authority", "rauch", "tbin")
    for d in (Design(split, split=split), Design(f"{split}_trim3", ("uv",), split=split, trim=3.0))
]  # fmt: skip


def country_group() -> pl.Expr:
    return pl.col("cty_code").replace_strict(COUNTRY, default="other")


def rauch_class() -> pl.Expr:
    con = pl.col("rauch_con")
    return (
        pl.when(con == "n").then(pl.lit("differentiated"))
        .when(con.is_in(["r", "w"])).then(pl.lit("homogeneous"))
        .otherwise(pl.lit("unclassified"))
    )  # fmt: skip


def time_bin() -> pl.Expr:
    k = pl.col("k")
    e = pl.when(k.is_null()).then(pl.lit("none")).when(k < 0).then(pl.lit("pre"))
    for lo, hi in TIME_BINS:
        e = e.when(k <= hi).then(pl.lit(f"m{lo}_{hi}"))
    return e.otherwise(pl.lit("m12p"))


def authority_terms(df: pl.DataFrame) -> pl.DataFrame:
    """Split dln(1 + tau) by authority: the change in each authority's rate over the midpoint
    1 + mean(tau_t, tau_t-12). Terms sum to dln(1 + tau) up to the log-mean approximation
    (exact for small changes; 5% low for China's April 2025 145% month)."""
    mid = 1 + (pl.col("stat_rate") + pl.col("stat_rate_b")) / 2
    return df.with_columns(
        ((pl.sum_horizontal(cols) - pl.sum_horizontal(f"{c}_b" for c in cols)) / mid).alias(
            f"{X}__{a}"
        )
        for a, cols in AUTHORITY.items()
    )


def split_x(df: pl.DataFrame, by: str, x: str = X) -> tuple[pl.DataFrame, list[str]]:
    levels = sorted(df[by].unique().drop_nulls().to_list())
    terms = [f"{x}__{v}" for v in levels]
    out = df.with_columns(
        pl.when(pl.col(by) == v).then(pl.col(x)).otherwise(0.0).alias(t)
        for v, t in zip(levels, terms, strict=True)
    )
    return out, terms


def fit_terms(df: pl.DataFrame, y: str, xs: list[str], fe: tuple[str, ...],
              cluster: str = "hs8", iv: str | None = None,
              weights: str | None = None) -> list[dict]:  # fmt: skip
    """FE regression of y on xs (or IV: xs[0] instrumented by iv), optionally weighted; one
    dict per term."""
    keys = {f for e in fe for f in e.split("^")} | set(cluster.split("+"))
    extra = [c for c in (iv, weights) if c]
    data = df.select(y, *xs, *extra, *keys).to_pandas()
    fml = (f"{y} ~ 1 | {' + '.join(fe)} | {xs[0]} ~ {iv}" if iv
           else f"{y} ~ {' + '.join(xs)} | {' + '.join(fe)}")  # fmt: skip
    m = pf.feols(fml, data=data, vcov={"CRV1": cluster}, weights=weights)
    t = m.tidy()
    r2 = getattr(m, "_r2", None)
    return [
        {"term": x, "coef": float(t.loc[x, "Estimate"]), "se": float(t.loc[x, "Std. Error"]),
         "ci_low": float(t.loc[x, "2.5%"]), "ci_high": float(t.loc[x, "97.5%"]),
         "n": int(m._N), "n_term": int((df[x] != 0).sum()),
         "r2": float(r2) if r2 is not None else None, "fe": " + ".join(fe), "cluster": cluster}
        for x in xs if x in t.index
    ]  # fmt: skip


def base_rates(month: date) -> pl.DataFrame:
    """Each variety's statutory rate in the base month (else its last month traded in the 12
    months to it): prod_id, cty_code, base_rate."""
    lo = date(month.year - 1, month.month, 1)
    return (
        pl.scan_parquet(PANEL)
        .filter(pl.col("month").is_between(lo, month, closed="right"))
        .sort("month")
        .group_by("prod_id", "cty_code")
        .agg(base_rate=pl.col("stat_rate").last())
        .collect()
    )


def period_events(period: str, end: date) -> tuple[pl.DataFrame, pl.DataFrame | None]:
    """Event month per variety (EVENT_SETUP) from every traded month; and the base rates."""
    cfg = EVENT_SETUP[period]
    rates = (
        pl.scan_parquet(PANEL)
        .filter(pl.col("month").is_between(cfg["from"], end))
        .select("prod_id", "cty_code", "month", "stat_rate")
        .sort("prod_id", "cty_code", "month")
        .collect()
    )
    base = base_rates(cfg["base_month"]) if cfg["base_month"] else None
    ev = event_months(rates, base=base, start=cfg["start"], half_rule=cfg["half_rule"])
    return ev, base


def rauch_map() -> pl.DataFrame:
    return (
        pl.read_parquet(
            config.PROCESSED_DIR / "hs10_attributes.parquet", columns=["hs6", "rauch_con"]
        )  # fmt: skip
        .drop_nulls()
        .group_by("hs6")
        .agg(pl.col("rauch_con").mode().sort().first())
    )


def panel_end() -> date:
    return pl.scan_parquet(PANEL).select(pl.col("month").max()).collect().item()


def load_pt(period: str) -> tuple[pl.DataFrame, tuple[date, date]]:
    """Changes panel for a period with lagged authority rates, group labels and months since the
    variety's first tariff increase (k; varieties without a 2024 base have none)."""
    lo, hi = PERIODS[period]
    months = (lo, hi or panel_end())
    df = load_changes(months)
    cur = ["prod_id", "level", "cty_code", "month"]
    rates = pl.scan_parquet(PANEL).select(*cur, "stat_rate", "con_val", *RATE_COLS)
    lagged = rates.filter(
        pl.col("month").is_between(
            lo.replace(year=lo.year - 1), months[1].replace(year=months[1].year - 1)
        )  # fmt: skip
    ).select(
        *cur[:3],
        pl.col("month").dt.offset_by("12mo"),
        *(pl.col(c).alias(f"{c}_b") for c in ["stat_rate", "con_val", *RATE_COLS]),
    )
    rates = rates.filter(pl.col("month").is_between(*months))
    df = df.join(rates.collect(), on=cur, how="left").join(lagged.collect(), on=cur, how="left")
    ev, _ = period_events(period, months[1])
    mon = pl.col("month").dt.year() * 12 + pl.col("month").dt.month()
    evm = pl.col("event").dt.year() * 12 + pl.col("event").dt.month()
    df = (
        authority_terms(df)
        .join(rauch_map(), on="hs6", how="left")
        .join(ev, on=["prod_id", "cty_code"], how="left")
        .with_columns(k=mon - evm)
        .with_columns(
            country=country_group(),
            rauch=rauch_class(),
            tbin=time_bin(),
            china=pl.when(pl.col("cty_code") == "5700")
            .then(pl.lit("china"))
            .otherwise(pl.lit("other")),
        )  # fmt: skip
    )
    return df, months


def fit_design(df: pl.DataFrame, d: Design, period: str, months: tuple[date, date]) -> list[dict]:
    rows = []
    end = min(d.end, months[1]) if d.end else months[1]
    base = df.filter(pl.col("month") <= end)
    for o in d.outcomes:
        y = f"{OUTCOMES[o]}_raw" if d.trim else OUTCOMES[o]
        s = sample(base, Spec(d.name, y, d.fe, months=(months[0], end), trim=d.trim))
        s = s.filter(pl.col(d.x).is_not_null())
        if d.split == "authority":  # 2.6% of rows have a P12 base but no lagged panel row
            s = s.filter(pl.col("stat_rate_b").is_not_null())
            terms = [f"{X}__{a}" for a in AUTHORITY]
        elif d.split:
            s, terms = split_x(s, d.split, d.x)
        else:
            terms = [d.x]
        terms = [t for t in terms if s[t].abs().max() > 1e-9]  # e.g. no IEEPA in 2018-19
        for r in fit_terms(s, y, terms, d.fe, d.cluster, d.iv):
            group = r["term"].split("__")[1] if "__" in r["term"] else "all"
            rows.append(
                {
                    "period": period,
                    "spec": d.name,
                    "outcome": o,
                    "group": group,
                    **r,
                    "x": d.x,
                    "iv": d.iv,
                    "start": months[0],
                    "end": end,
                    "note": d.note,
                }
            )
    return rows


def locality_rates(df: pl.DataFrame, localities: dict[str, list[str]]) -> pl.DataFrame:
    """Value-weighted statutory and effective rates by locality and month, with 12-month changes
    in ln(1 + rate). df: cty_code, month, con_val, cal_dut, stat_rate."""
    lv = (
        pl.concat(
            df.filter(pl.col("cty_code").is_in(c)).with_columns(locality=pl.lit(name))
            for name, c in localities.items()
        )  # fmt: skip
        .group_by("locality", "month")
        .agg(
            con_val=pl.col("con_val").sum(),
            cal_dut=pl.col("cal_dut").sum(),
            stat_val=(pl.col("stat_rate") * pl.col("con_val")).sum(),
        )  # fmt: skip
        .with_columns(
            stat_rate=pl.col("stat_val") / pl.col("con_val"),
            eff_rate=pl.col("cal_dut") / pl.col("con_val"),
        )  # fmt: skip
    )
    lag = lv.select("locality", pl.col("month").dt.offset_by("12mo"),
                    stat_b="stat_rate", eff_b="eff_rate")  # fmt: skip
    return (
        lv.join(lag, on=["locality", "month"], how="left")
        .with_columns(
            dln_1p_tau_stat=(1 + pl.col("stat_rate")).log() - (1 + pl.col("stat_b")).log(),
            dln_1p_tau_eff=(1 + pl.col("eff_rate")).log() - (1 + pl.col("eff_b")).log(),
        )
        .select(
            "locality",
            "month",
            "con_val",
            "stat_rate",
            "eff_rate",
            "dln_1p_tau_stat",
            "dln_1p_tau_eff",
        )  # fmt: skip
        .sort("locality", "month")
    )


def mxp_panel() -> pl.DataFrame:
    """BLS import price index by locality of origin (12-month log change) with our tariff
    changes for the same countries; months without an index value (Oct 2025) drop out."""
    eu = pl.read_csv(config.REFERENCE_DIR / "country_groups.csv", schema_overrides={
        "cty_code": pl.String}).filter(pl.col("group") == EU27)["cty_code"].to_list()  # fmt: skip
    loc = {name: (eu if codes == EU27 else codes) for name, codes in MXP_LOCALITIES.values()}
    trade = (
        pl.scan_parquet(PANEL)
        .filter(pl.col("drop_reason").is_null() | (pl.col("drop_reason") != "special_provision"))
        .select("cty_code", "month", "con_val", "cal_dut", "stat_rate")
        .collect()
    )
    rates = locality_rates(trade, loc)
    names = {sid: name for sid, (name, _) in MXP_LOCALITIES.items()}
    mxp = (
        pl.read_parquet(config.INTERIM_DIR / "bls" / "mxp.parquet")
        .filter(pl.col("series_id").is_in(list(names)), pl.col("value").is_not_null())
        .select(locality=pl.col("series_id").replace_strict(names), month="month", mxp="value")
    )
    lag = mxp.select("locality", pl.col("month").dt.offset_by("12mo"), mxp_b="mxp")
    mxp = mxp.join(lag, on=["locality", "month"], how="inner").with_columns(
        dln_mxp=(pl.col("mxp") / pl.col("mxp_b")).log()
    )
    return mxp.join(rates, on=["locality", "month"], how="inner").sort("locality", "month")


def fit_mxp(panel: pl.DataFrame, period: str, months: tuple[date, date]) -> list[dict]:
    """Locality x month: dln MXP on dln(1 + tau), locality and month FE; heteroskedasticity-
    robust SEs (8 localities are too few clusters)."""
    s = panel.filter(pl.col("month").is_between(*months)).with_columns(
        ym=pl.col("month").dt.strftime("%Y-%m")
    )
    rows = []
    for x in (X, X_EFF):
        m = pf.feols(f"dln_mxp ~ {x} | locality + ym", data=s.to_pandas(), vcov="hetero")
        t = m.tidy().loc[x]
        rows.append(
            {
                "period": period,
                "spec": "mxp_locality",
                "outcome": "mxp",
                "group": "all",
                "term": x,
                "coef": float(t["Estimate"]),
                "se": float(t["Std. Error"]),
                "ci_low": float(t["2.5%"]),
                "ci_high": float(t["97.5%"]),
                "n": int(m._N),
                "n_term": int(m._N),
                "r2": float(m._r2),
                "fe": "locality + ym",
                "cluster": "hetero",
                "x": x,
                "iv": None,
                "start": months[0],
                "end": months[1],
                "note": "BLS locality-of-origin import price indexes",
            }
        )
    return rows


def run_pt() -> pl.DataFrame:
    """2018-19 and 2025-26 static designs, heterogeneity and the MXP cross-check."""
    t0 = time.time()
    rows: list[dict] = []
    mxp = mxp_panel()
    n = sum(len(d.outcomes) for p in PERIODS for d in DESIGNS if p in d.periods)
    i = 0
    for period in PERIODS:
        df, months = load_pt(period)
        print(f"{period}: {df.height:,} rows, {months[0]}..{months[1]} "
              f"({time.time() - t0:.0f}s)", flush=True)  # fmt: skip
        for d in DESIGNS:
            if period not in d.periods:
                continue
            out = fit_design(df, d, period, months)
            rows += out
            i += len(d.outcomes)
            for r in out:
                print(f"[{i:>3}/{n}] {period} {d.name:<16} {r['outcome']:<6} {r['group']:<14} "
                      f"b = {r['coef']:+.3f} ({r['se']:.3f})  n = {r['n']:,}  "
                      f"{time.time() - t0:.0f}s", flush=True)  # fmt: skip
        rows += fit_mxp(mxp, period, months)
        print(f"{period} MXP locality: " + "  ".join(
            f"{r['x']} b = {r['coef']:+.3f} ({r['se']:.3f}) n = {r['n']}" for r in rows[-2:]),
            flush=True)  # fmt: skip
    est = pl.DataFrame(rows, infer_schema_length=None).with_columns(
        buyer_share=pl.when(pl.col("outcome") == "uv").then(1 + pl.col("coef"))
    )
    PT_OUT.parent.mkdir(parents=True, exist_ok=True)
    est.write_csv(PT_OUT, float_precision=5)
    mxp.write_csv(MXP_OUT, float_precision=5)
    return est


def run_events25() -> pl.DataFrame:
    """2025-26 levels event studies: steps over each variety's Dec 2024 rate from 2025-01;
    pre_ruling ends 2026-01, before IEEPA duties ended (about 6 minutes per outcome)."""
    t0 = time.time()
    end = panel_end()
    ev, base = period_events("2025_26", end)
    events = []
    for name, (lo, hi) in EVENT25_SAMPLES.items():
        lv = load_levels((lo, hi or end)).join(base.select("prod_id", "cty_code"),
                                               on=["prod_id", "cty_code"], how="semi")  # fmt: skip
        print(f"levels panel {name}: {lv.height:,} rows, {ev.height:,} varieties with an event "
              f"({time.time() - t0:.0f}s)", flush=True)  # fmt: skip
        for o in ("uv", "uv_dut", "qty", "val"):
            es = event_study(lv, f"ln_{o}", events=ev)
            events.append(es.with_columns(sample=pl.lit(name), outcome=pl.lit(o)))
            print(f"event study {name} {o:<7} k=-6..6: "
                  + " ".join(f"{c:+.3f}" for c in es["coef"])
                  + f"  ({time.time() - t0:.0f}s)", flush=True)  # fmt: skip
    out = pl.concat(events).select("sample", "outcome", "k", "coef", "se", "ci_low", "ci_high",
                                   "n", "varieties_targeted")  # fmt: skip
    out.write_csv(EVENT25_OUT, float_precision=5)
    return out


# --- run ------------------------------------------------------------------------


def run_static() -> pl.DataFrame:
    t0 = time.time()
    df = load_changes((date(2018, 1, 1), date(2019, 12, 1)))
    print(f"changes panel: {df.height:,} rows ({time.time() - t0:.0f}s)", flush=True)
    rows = []
    for i, spec in enumerate(REPLICATION, 1):
        r = fit(sample(df, spec), spec)
        pub = PUBLISHED.get(spec.name, {}).get(spec.label)
        src = PUBLISHED[spec.name]["source"] if pub else None
        rows.append({"spec": spec.name, "outcome": spec.label, "y": spec.y, **r,
                     "start": spec.months[0], "end": spec.months[1],
                     "published_coef": pub[0] if pub else None,
                     "published_se": pub[1] if pub else None, "published_source": src})  # fmt: skip
        print(f"[{i:>2}/{len(REPLICATION)}] {spec.name:<10} {spec.label:<7} "
              f"b = {r['coef']:+.3f} ({r['se']:.3f})  n = {r['n']:,}  "
              f"{time.time() - t0:.0f}s", flush=True)  # fmt: skip
    est = pl.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    est.write_csv(OUT, float_precision=5)
    return est


def run_events() -> pl.DataFrame:
    """Levels event studies for each EVENT_SAMPLES window (about 4 minutes per outcome)."""
    t0 = time.time()
    events = []
    for name, months in EVENT_SAMPLES.items():
        lv = load_levels(months)
        print(f"levels panel {name}: {lv.height:,} rows ({time.time() - t0:.0f}s)", flush=True)
        for o in ("uv", "uv_dut", "qty", "val"):
            es = event_study(lv, f"ln_{o}")
            events.append(es.with_columns(sample=pl.lit(name), outcome=pl.lit(o)))
            print(f"event study {name} {o:<7} k=-6..6: "
                  + " ".join(f"{c:+.3f}" for c in es["coef"])
                  + f"  ({time.time() - t0:.0f}s)", flush=True)  # fmt: skip
    ev = pl.concat(events).select("sample", "outcome", "k", "coef", "se", "ci_low", "ci_high",
                                  "n", "varieties_targeted")  # fmt: skip
    EVENT_OUT.parent.mkdir(parents=True, exist_ok=True)
    ev.write_csv(EVENT_OUT, float_precision=5)
    return ev


def run(part: str = "all") -> None:
    if part in ("all", "static"):
        run_static()
    if part in ("all", "events"):
        run_events()
    if part in ("all", "pt"):
        run_pt()
    if part in ("all", "events25"):
        run_events25()


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "all")

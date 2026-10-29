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

Run: make models, or python -m tpt.models.border_pt static|events (writes
data/published/border_pt_replication.csv and border_pt_event_2018_19.csv)
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


def event_months(df: pl.DataFrame) -> pl.DataFrame:
    """First month of a tariff increase per variety: rate >= MIN_STEP and at least half the next
    month's rate (a day-weighted month is >= half the new rate iff the change took effect by
    about the 15th). df: prod_id, cty_code, month, stat_rate (monthly, sorted per variety)."""
    nxt = pl.col("stat_rate").shift(-1).over("prod_id", "cty_code", order_by="month")
    hit = (pl.col("stat_rate") >= MIN_STEP) & (pl.col("stat_rate") >= 0.5 * nxt.fill_null(0))
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
                "cty_code^ym"), cluster: str = "hs8") -> pl.DataFrame:  # fmt: skip
    """df: add_keys(levels) with y and stat_rate. Returns k, coef, se, ci_low, ci_high, n."""
    d = event_dummies(df, event_months(df)).with_columns(
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


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "all")

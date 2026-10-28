"""Statutory additional duties (P10 panel) vs duties actually assessed (Census), P11.

Implied additional rate per HS10 x country x month:

    (calculated duties - MFN rate x MFN base) / consumption value

The MFN base is the dutiable value, capped at the pair's dutiable share in a reference year
before the action period (2017 for 2018-24 months, 2024 for 2025-26) times the month's value.
The cap matters because a Chapter 99 duty makes goods "dutiable" that pay no MFN duty (FTA or
USMCA claims, e.g. USMCA pickups that pay the Section 232 duty but not the 25% MFN rate); without
it the MFN term is overstated. Before 2018, MFN x dutiable value is 1.38% of value against 1.40%
calculated duties (2017-06), so the MFN term is accurate when no additional duties apply.

Each pair-month is put in one gap category (first match in CATEGORIES order); the bridge sums
the duty gap (statutory - implied, $) by category and month. Census calculated duties are as
assessed at entry: no refunds, no drawback (those are in Treasury receipts, P04).

Run: make validate-rates   (writes reports/qa/rate_validation_*.csv)
"""

from datetime import date

import duckdb
import polars as pl

from tpt import config
from tpt.build.tariff_rates import IMPORTS
from tpt.build.tariff_rates import OUT as RATES

QA = config.PROJECT_ROOT / "reports" / "qa"
GAP_PP = 0.05
USMCA_CTY = ("1220", "2010")
# Census records no duty on these: estimated low-value shipments, Chapter 98 special provisions
# (US goods returned etc.), pipeline natural gas and electricity from Canada and Mexico (entered
# under rate provision 10, free, with no duty even when the 10% energy duty applied).
NOT_COMPARABLE_PREFIX = ("9999", "98")
NOT_COMPARABLE_CA_MX = ("27112100", "2716")
# Months covered by in-transit exemptions in the orders: goods loaded before the effective date
# entered at the old rate. EO 14195 (China fentanyl, loaded before 2025-02-01), EO 14257
# (reciprocal, loaded before 2025-04-05 / 04-09), EO 14326 (country rates, loaded before
# 2025-08-07, entered before 2025-10-05).
IN_TRANSIT_MONTHS = tuple(
    date.fromisoformat(m + "-01")
    for m in ("2025-02", "2025-03", "2025-04", "2025-05", "2025-08", "2025-09")
)
CATEGORIES = {
    "not_comparable": "Census records no duty (low-value estimates, Ch. 98, pipeline energy)",
    "metal_content": "Section 232 metal/copper duty on metal content only (panel: full value)",
    "in_transit": "rate rose this or last month; in-transit exemptions (EO 14195, 14257, 14326)",
    "usmca": "Canada/Mexico: USMCA share and claims, vehicle US content",
    "s201": "Section 201 safeguards: tariff-rate quotas (solar cells), bifacial exclusion",
    "s301_china": "Section 301 China: product exclusions (USTR), not modelled",
    "medical": "medical devices: Nairobi Protocol (9817.00.92-.96) and other end-use exemptions",
    "aircraft": "civil aircraft, engines, parts: aircraft exemptions beyond identifiable lines",
    "precious_metals": "gold, silver, platinum-group metals: bullion exemptions (Annex II, S122)",
    "other": "other (exclusions, Annex II changes, classification, undervaluation)",
}
DETAIL = ("rate_s232", "rate_metal_content", "rate_s301", "rate_ieepa_fentanyl",
          "rate_ieepa_reciprocal", "rate_s122", "mfn_rate")  # fmt: skip
# 2025-26 product groups that pay far less than the panel's rate for exemptions the trade
# statistics cannot identify line by line (P11 drill-down; see DATA.md)
GROUPS_2025 = {
    "medical": ("9018", "9019", "9021", "9022", "8713"),
    "aircraft": ("8802", "8803", "8805", "8411", "840710", "840910"),
    "precious_metals": ("7106", "7107", "7108", "7109", "7110", "7111", "7112", "7118"),
}
PERIODS = {
    "2018-19": (date(2018, 7, 1), date(2019, 12, 1)),
    "2020-24": (date(2020, 1, 1), date(2024, 12, 1)),
    "2025-26": (date(2025, 2, 1), date(2100, 1, 1)),
}


def reference_year(month: pl.Expr) -> pl.Expr:
    return pl.when(month.dt.year() >= 2025).then(2024).otherwise(2017)


def implied(df: pl.DataFrame, ref: pl.DataFrame) -> pl.DataFrame:
    """Add mfn_dut, impl_add (implied additional rate) and gap_dut (statutory - implied, $).

    df: hs10, cty_code, month, con_val, dut_val, cal_dut, mfn_rate, rate_total.
    ref: hs10, cty_code, ref_year, ref_share (dutiable / consumption value in the ref year)."""
    out = (
        df.with_columns(ref_year=reference_year(pl.col("month")))
        .join(ref, on=["hs10", "cty_code", "ref_year"], how="left")
        .with_columns(
            mfn_base=pl.min_horizontal(
                "dut_val", pl.col("con_val") * pl.col("ref_share").fill_null(1.0)
            )
        )
        .with_columns(mfn_dut=pl.col("mfn_rate").fill_null(0) * pl.col("mfn_base"))
        .with_columns(
            impl_add=(pl.col("cal_dut") - pl.col("mfn_dut")) / pl.col("con_val"),
            gap_dut=pl.col("rate_total") * pl.col("con_val")
            - (pl.col("cal_dut") - pl.col("mfn_dut")),
        )
    )
    return out.drop("ref_year", "ref_share", "mfn_base")


def ref_shares(df: pl.DataFrame) -> pl.DataFrame:
    """Dutiable share of consumption value by pair in each reference year."""
    return (
        df.filter(pl.col("month").dt.year().is_in([2017, 2024]))
        .group_by("hs10", "cty_code", ref_year=pl.col("month").dt.year())
        .agg(ref_share=pl.col("dut_val").sum() / pl.col("con_val").sum())
        .with_columns(pl.col("ref_year").cast(pl.Int32))
    )


def _starts(*prefixes: str) -> pl.Expr:
    return pl.any_horizontal([pl.col("hs10").str.starts_with(p) for p in prefixes])


def categorize(df: pl.DataFrame) -> pl.DataFrame:
    """Gap category per pair-month (needs rate_total_prev: the pair's rate the month before)."""
    camx = pl.col("cty_code").is_in(USMCA_CTY)
    rose = (pl.col("rate_total") - pl.col("rate_total_prev").fill_null(0)) > 0.01
    rose_before = (
        pl.col("rate_total_prev").fill_null(0) - pl.col("rate_total_prev2").fill_null(0)
    ) > 0.01
    y2025 = pl.col("month") >= date(2025, 1, 1)
    expr = (
        pl.when(_starts(*NOT_COMPARABLE_PREFIX) | (camx & _starts(*NOT_COMPARABLE_CA_MX)))
        .then(pl.lit("not_comparable"))
        .when(pl.col("rate_metal_content") > 0).then(pl.lit("metal_content"))
        .when(pl.col("month").is_in(IN_TRANSIT_MONTHS) & (rose | rose_before))
        .then(pl.lit("in_transit"))
        .when(camx & y2025).then(pl.lit("usmca"))
        .when(pl.col("rate_s201") > 0).then(pl.lit("s201"))
        .when((pl.col("cty_code") == "5700") & (pl.col("rate_s301") > 0))
        .then(pl.lit("s301_china"))
    )  # fmt: skip
    for name, prefixes in GROUPS_2025.items():
        expr = expr.when(y2025 & _starts(*prefixes)).then(pl.lit(name))
    return df.with_columns(category=expr.otherwise(pl.lit("other")))


def _weighted_corr(x: pl.Expr, y: pl.Expr, w: pl.Expr) -> pl.Expr:
    mx, my = (x * w).sum() / w.sum(), (y * w).sum() / w.sum()
    cov = ((x - mx) * (y - my) * w).sum()
    return cov / (((x - mx) ** 2 * w).sum() * ((y - my) ** 2 * w).sum()).sqrt()


def metrics(df: pl.DataFrame) -> pl.DataFrame:
    """By period: pair-month correlation (unweighted, value-weighted) of statutory and implied
    additional rates, share of value with |statutory - implied| > 5 pp; comparable pairs only."""
    rows = []
    comp = df.filter(pl.col("category") != "not_comparable")
    for name, (lo, hi) in PERIODS.items():
        p = comp.filter(pl.col("month").is_between(lo, hi))
        stat, impl, w = pl.col("rate_total"), pl.col("impl_add"), pl.col("con_val")
        rows.append(
            p.select(
                period=pl.lit(name),
                pair_months=pl.len(),
                value_bn=w.sum() / 1e9,
                corr=pl.corr("rate_total", "impl_add"),
                corr_weighted=_weighted_corr(stat, impl, w),
                share_value_gt_5pp=(w * ((stat - impl).abs() > GAP_PP)).sum() / w.sum(),
                statutory=(stat * w).sum() / w.sum(),
                implied=(impl * w).sum() / w.sum(),
            )
        )
    return pl.concat(rows)


def bridge(df: pl.DataFrame) -> pl.DataFrame:
    """Monthly statutory and implied additional rates and the duty gap by category, as shares
    of total consumption value (pp of value)."""
    tot = df.group_by("month").agg(
        value=pl.col("con_val").sum(),
        statutory=(pl.col("rate_total") * pl.col("con_val")).sum(),
        implied=(pl.col("impl_add") * pl.col("con_val")).sum(),
    )
    gap = pl.col("gap_dut")
    cats = df.group_by("month").agg(
        [gap.filter(pl.col("category") == c).sum().alias(f"gap_{c}") for c in CATEGORIES]
    )
    out = tot.join(cats, on="month").sort("month")
    cols = ["statutory", "implied", *[f"gap_{c}" for c in CATEGORIES]]
    return (
        out.with_columns([pl.col(c) / pl.col("value") for c in cols])
        .with_columns(gap=pl.col("statutory") - pl.col("implied"), value_bn=pl.col("value") / 1e9)
        .drop("value")
    )


def top_pairs(df: pl.DataFrame, lo: date, n: int = 30) -> pl.DataFrame:
    """Largest absolute duty gaps by HS10 x country from `lo`, with the dominant category."""
    p = df.filter(pl.col("month") >= lo)
    dom = (
        p.group_by("hs10", "cty_code", "category").agg(g=pl.col("gap_dut").sum().abs())
        .sort("g", descending=True).unique(["hs10", "cty_code"], keep="first")
        .select("hs10", "cty_code", "category")
    )  # fmt: skip
    w = pl.col("con_val")
    agg = p.group_by("hs10", "cty_code").agg(
        value_bn=w.sum() / 1e9,
        statutory=(pl.col("rate_total") * w).sum() / w.sum(),
        implied=(pl.col("impl_add") * w).sum() / w.sum(),
        gap_bn=pl.col("gap_dut").sum() / 1e9,
        **{c: (pl.col(c) * w).sum() / w.sum() for c in DETAIL if c in p.columns},
    )  # fmt: skip
    return (
        agg.join(dom, on=["hs10", "cty_code"])
        .sort(pl.col("gap_bn").abs(), descending=True)
        .head(n)
        .with_columns(cause=pl.col("category").replace_strict(CATEGORIES))
    )


def load() -> pl.DataFrame:
    con = duckdb.connect()
    df = con.sql(f"""
        with i as (
          select hs10, cty_code, month, sum(con_val_mo)::double con_val,
                 sum(dut_val_mo)::double dut_val, sum(cal_dut_mo)::double cal_dut
          from read_parquet('{IMPORTS}/*/*.parquet', hive_partitioning=true) group by all)
        select r.hs10, r.cty_code, r.month, i.con_val, i.dut_val, i.cal_dut, r.mfn_rate,
               r.rate_total, r.rate_s232, r.rate_metal_content, r.rate_s301, r.rate_s201,
               r.rate_s122, r.rate_ieepa_fentanyl, r.rate_ieepa_reciprocal,
               lag(r.rate_total) over w rate_total_prev,
               lag(r.rate_total, 2) over w rate_total_prev2,
               lag(r.month) over w month_prev, lag(r.month, 2) over w month_prev2
        from '{RATES}' r join i using (hs10, cty_code, month)
        where i.con_val > 0
        window w as (partition by r.hs10, r.cty_code order by r.month)
    """).pl()  # fmt: skip

    # lags only count when the pair traded in the previous months
    def index(col: str) -> pl.Expr:
        return pl.col(col).dt.month() + 12 * pl.col(col).dt.year()

    return df.with_columns(
        pl.when(index("month") - index("month_prev") == 1).then("rate_total_prev"),
        pl.when(index("month") - index("month_prev2") == 2).then("rate_total_prev2"),
    ).drop("month_prev", "month_prev2")


def run() -> dict[str, pl.DataFrame]:
    df = load()
    df = categorize(implied(df, ref_shares(df)))
    QA.mkdir(parents=True, exist_ok=True)
    out = {
        "metrics": metrics(df),
        "bridge": bridge(df),
        "top30_2025": top_pairs(df, date(2025, 1, 1)),
        "top30_2018": top_pairs(df.filter(pl.col("month") < date(2025, 1, 1)), date(2018, 7, 1)),
    }
    for name, t in out.items():
        t.write_csv(QA / f"rate_validation_{name}.csv", float_precision=5)
    pl.Config.set_tbl_cols(20)
    pl.Config.set_tbl_rows(80)
    pl.Config.set_tbl_width_chars(250)
    for name, t in out.items():
        print(name)
        print(t)
    return out


if __name__ == "__main__":
    run()

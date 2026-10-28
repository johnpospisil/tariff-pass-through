"""Front-running around the major 2025 tariff actions: event studies (P14).

For each action, the treated set is the HS6 x country pairs whose statutory rate (P10) for the
action's authority rose between a month before and a month after the effective date (HS6 is
stable within HS 2022, so the set does not shift with HS10 code changes). Monthly imports for
consumption of the set are compared with a counterfactual built from the set's own seasonal
pattern: value 12 months earlier x the set's year-on-year growth before the 2024 election
(PRE = 2023-10..2024-09, geometric mean). Excess = actual / counterfactual - 1. Where a control
set is defined (the August 2025 country rates: pairs whose reciprocal rate stayed at 10%), the
control's own excess is divided out, removing common shocks. Band: +/- 2 s.d. of monthly log
year-on-year growth in PRE (the noise of the counterfactual).

Summary: stockpile_months = consecutive months just before the effective month with excess above
the band (conservative) and excess_pre their excess imports ($); positive_months / excess_positive
the same for excess > 0 (how long stockpiling lasted); shortfall_post = excess in months 0..+5.

Run: make front-running   (writes data/published/front_running*.csv)
"""

from dataclasses import dataclass
from datetime import date

import duckdb
import polars as pl

from tpt import config
from tpt.build.tariff_rates import IMPORTS
from tpt.build.tariff_rates import OUT as RATES

OUT = config.PUBLISHED_DIR / "front_running.csv"
SUMMARY = config.PUBLISHED_DIR / "front_running_summary.csv"
PRE = (date(2023, 10, 1), date(2024, 9, 1))
WINDOW = (-9, 9)
POST_MONTHS = 6
CA_MX_CN_HK = ("1220", "2010", "5700", "5820")


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    effective: date  # month containing the effective date (event month 0)
    citation: str
    col: str | None = None  # P10 rate column whose rise defines treatment
    before: str = ""  # YYYY-MM
    after: str = ""
    min_rise: float = 0.05
    countries: tuple[str, ...] = ()  # only these (empty = all)
    exclude_countries: tuple[str, ...] = ()
    hs_prefixes: tuple[str, ...] = ()  # only these (empty = all)
    exclude_hs: tuple[str, ...] = ()
    control_max_rise: float | None = None  # control: same col, rise below this, rate > 0 after


ACTIONS = [
    Action("cn_fentanyl", "China: fentanyl duty (Feb 2025)", date(2025, 2, 1),
           "EO 14195, 90 FR 9121", "rate_ieepa_fentanyl", "2025-01", "2025-03",
           countries=("5700",)),
    Action("metals", "Steel and aluminum (Mar 2025)", date(2025, 3, 1),
           "Proclamations 10895, 10896", "rate_s232", "2025-02", "2025-04", min_rise=0.10,
           exclude_hs=("87",)),
    Action("reciprocal", "Reciprocal baseline, excl. China (Apr 2025)", date(2025, 4, 1),
           "EO 14257, 90 FR 15041", "rate_ieepa_reciprocal", "2025-03", "2025-05",
           exclude_countries=CA_MX_CN_HK),
    Action("autos", "Autos (Apr 2025)", date(2025, 4, 1), "Proclamation 10908",
           "rate_s232", "2025-03", "2025-05", min_rise=0.10, hs_prefixes=("8703",)),
    Action("country_rates", "Country-specific rates (Aug 2025)", date(2025, 8, 1),
           "EO 14326, 90 FR 37963", "rate_ieepa_reciprocal", "2025-07", "2025-09",
           min_rise=0.04, exclude_countries=CA_MX_CN_HK, control_max_rise=0.005),
    Action("pharma", "Pharmaceuticals (inquiry opened Apr 2025)", date(2025, 4, 1),
           "Section 232 investigation initiated 2025-04-01 (90 FR 15951); duty from 2026-09-29",
           hs_prefixes=("30",)),
]  # fmt: skip


# --- event study on a monthly series ------------------------------------------


def _yoy(s: pl.DataFrame) -> pl.DataFrame:
    """month, value -> month, value, base (value 12 months earlier), lr (log ratio)."""
    s = s.select("month", "value").sort("month")
    prev = s.select(pl.col("month").dt.offset_by("12mo"), base=pl.col("value"))
    return s.join(prev, on="month", how="left").with_columns(
        lr=(pl.col("value") / pl.col("base")).log()
    )


def _pre_stats(y: pl.DataFrame) -> tuple[float, float]:
    pre = y.filter(pl.col("month").is_between(*PRE))["lr"]
    return pre.mean(), pre.std()


def event_study(treated: pl.DataFrame, effective: date,
                control: pl.DataFrame | None = None) -> pl.DataFrame:  # fmt: skip
    """treated (and control): month, value. Returns one row per event month k in WINDOW."""
    t = _yoy(treated)
    mu, sd = _pre_stats(t)
    t = t.with_columns(counterfactual=pl.col("base") * pl.lit(mu).exp())
    if control is not None:
        c = _yoy(control)
        cmu, csd = _pre_stats(c)
        adj = c.select("month", adj=(pl.col("lr") - cmu).exp())
        t = t.join(adj, on="month", how="left").with_columns(
            counterfactual=pl.col("counterfactual") * pl.col("adj")
        )
        # noise of the difference in log growth
        both = _yoy(treated).join(_yoy(control), on="month", suffix="_c")
        sd = (
            both.filter(pl.col("month").is_between(*PRE))
            .select((pl.col("lr") - pl.col("lr_c")).std())
            .item()
        )
    months = pl.col("month").dt.year() * 12 + pl.col("month").dt.month()
    k = months - (effective.year * 12 + effective.month)
    return (
        t.with_columns(k=k)
        .filter(pl.col("k").is_between(*WINDOW))
        .with_columns(
            excess_pct=pl.col("value") / pl.col("counterfactual") - 1,
            band=pl.lit(float(pl.Series([2 * sd]).exp()[0] - 1)),
            band_low=pl.lit(float(pl.Series([-2 * sd]).exp()[0] - 1)),
        )
        .select("k", "month", "value", "counterfactual", "excess_pct", "band", "band_low")
        .sort("k")
    )


def _run(pre: pl.DataFrame, threshold: pl.Series) -> int:
    """Consecutive months just before month 0 with excess above the threshold."""
    n = 0
    for pct, thr in zip(pre["excess_pct"], threshold, strict=True):
        if pct is None or pct <= thr:
            break
        n += 1
    return n


def summarize(es: pl.DataFrame) -> dict:
    pre = es.filter(pl.col("k") < 0).sort("k", descending=True)
    months = _run(pre, pre["band"])
    positive = _run(pre, pl.Series([0.0] * pre.height))
    stock, run = pre.head(months), pre.head(positive)
    post = es.filter(pl.col("k").is_between(0, POST_MONTHS - 1))
    peak = pre.sort("excess_pct", descending=True).row(0, named=True)
    return {
        "stockpile_months": months,
        "excess_pre": (stock["value"] - stock["counterfactual"]).sum(),
        "positive_months": positive,
        "excess_positive": (run["value"] - run["counterfactual"]).sum(),
        "shortfall_post": (post["value"] - post["counterfactual"]).sum(),
        "peak_k": peak["k"],
        "peak_pct": peak["excess_pct"],
    }


# --- treated sets from the rate panel and imports -----------------------------


def _filters(a: Action, alias: str = "") -> str:
    p = f"{alias}." if alias else ""
    conds = ["true"]
    if a.countries:
        conds.append(f"{p}cty_code in ({', '.join(repr(c) for c in a.countries)})")
    if a.exclude_countries:
        conds.append(f"{p}cty_code not in ({', '.join(repr(c) for c in a.exclude_countries)})")
    if a.hs_prefixes:
        conds.append("(" + " or ".join(f"{p}hs6 like '{h}%'" for h in a.hs_prefixes) + ")")
    for h in a.exclude_hs:
        conds.append(f"{p}hs6 not like '{h}%'")
    return " and ".join(conds)


def sets_sql(a: Action) -> tuple[str, str | None]:
    """SQL for the treated (and control) HS6 x country sets."""
    if a.col is None:
        q = f"select distinct hs6, cty_code from m6 where {_filters(a)}"
        return q, None
    rates = f"""
        select substr(r.hs10, 1, 6) hs6, r.cty_code,
          sum(case when strftime(r.month, '%Y-%m') = '{a.before}' then {a.col} * i.v end)
            / nullif(sum(case when strftime(r.month, '%Y-%m') = '{a.before}' then i.v end), 0) b,
          sum(case when strftime(r.month, '%Y-%m') = '{a.after}' then {a.col} * i.v end)
            / nullif(sum(case when strftime(r.month, '%Y-%m') = '{a.after}' then i.v end), 0) f
        from '{RATES}' r join i10 i using (hs10, cty_code, month)
        where strftime(r.month, '%Y-%m') in ('{a.before}', '{a.after}')
        group by 1, 2"""  # fmt: skip
    base = f"with w as ({rates}) select hs6, cty_code from w where {_filters(a)}"
    treated = f"{base} and f - coalesce(b, 0) > {a.min_rise}"
    control = None
    if a.control_max_rise is not None:
        control = f"{base} and abs(f - coalesce(b, 0)) <= {a.control_max_rise} and f > 0.05"
    return treated, control


def run() -> tuple[pl.DataFrame, pl.DataFrame]:
    con = duckdb.connect()
    con.sql(f"""
        create table i10 as
        select hs10, cty_code, month, sum(con_val_mo)::double v
        from read_parquet('{IMPORTS}/*/data.parquet', hive_partitioning = 1)
        where summary_lvl = 'DET' and cty_code <> '-' and month >= '2022-01-01'
          and con_val_mo > 0 and hs10 not like '98%' and hs10 not like '99%'
        group by all""")  # fmt: skip
    con.sql("create table m6 as select substr(hs10, 1, 6) hs6, cty_code, month, sum(v) v "
            "from i10 group by all")  # fmt: skip
    rows, summaries = [], []
    for a in ACTIONS:
        tq, cq = sets_sql(a)
        sets = {"treated": tq} | ({"control": cq} if cq else {})
        monthly = {}
        for name, q in sets.items():
            monthly[name] = con.sql(f"""
                select m.month, sum(m.v) as value, count(distinct (m.hs6, m.cty_code)) pairs
                from m6 m join ({q}) s using (hs6, cty_code)
                group by 1 order by 1""").pl()  # fmt: skip
        es = event_study(monthly["treated"], a.effective, monthly.get("control"))
        rows.append(es.with_columns(action=pl.lit(a.id), label=pl.lit(a.label)))
        s = summarize(es)
        base = monthly["treated"].filter(pl.col("month").dt.year() == 2024)["value"].sum()
        summaries.append({
            "action": a.id, "label": a.label, "effective_month": a.effective,
            "citation": a.citation,
            "treated_pairs": int(monthly["treated"]["pairs"].max()),
            "imports_2024_bn": base / 1e9, "control": cq is not None, **s,
            "excess_pre_bn": s["excess_pre"] / 1e9,
            "excess_positive_bn": s["excess_positive"] / 1e9,
            "excess_positive_pct_of_2024": s["excess_positive"] / base,
            "excess_pre_pct_of_2024": s["excess_pre"] / base,
            "shortfall_post_bn": s["shortfall_post"] / 1e9,
            "band": float(es["band"][0]),
        })  # fmt: skip
    out = pl.concat(rows).select("action", "label", "k", "month", "value", "counterfactual",
                                 "excess_pct", "band", "band_low")  # fmt: skip
    summary = pl.DataFrame(summaries).drop("excess_pre", "excess_positive", "shortfall_post")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.write_csv(OUT, float_precision=5)
    summary.write_csv(SUMMARY, float_precision=4)
    pl.Config.set_tbl_cols(16)
    pl.Config.set_tbl_width_chars(250)
    print(summary.drop("citation"))
    return out, summary


if __name__ == "__main__":
    run()

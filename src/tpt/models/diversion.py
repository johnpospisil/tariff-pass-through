"""Trade diversion and transshipment proxies (P20).

Imports for consumption from individual countries (chapters 98-99 excluded), HS6 x country x
month. Statutory rates (P10 rate_total) are averaged to HS6 x country x month with HS10 weights
= the pair's customs value in the weight year (2017 / 2024; unweighted when none), and carried
forward / back to months in which the pair did not trade.

1. Long differences: two seasonally matched 8-month windows two years apart (2023-06..2024-01 vs
   2025-06..2026-01, i.e. before the 2024-election front-running and before the IEEPA ruling;
   2017-06..2018-01 vs 2019-06..2020-01). Delta ln value and Delta share (pp) of each HS6 x country
   on Delta ln(1 + tau), with HS6 FE, so the tariff change is relative to other suppliers of the
   same product. Clustered by HS6. For 2025-26 also net of each pair's own pre-trend (growth
   2021-06..12 to 2023-06..12): suppliers taking share from China since 2018 (Vietnam, Taiwan,
   Thailand) also face mid-level 2025 rates, so a plain long difference confounds their trend
   with their tariff.
2. Gravity, PPML (pyfixest fepois), quarterly: value on ln(1 + tau) with HS6 x quarter and
   HS6 x country FE (and + country x quarter, which absorbs country-wide rates such as the
   reciprocal tariffs, leaving product-specific variation). Balanced over the window for pairs
   that traded in the weight year, zeros kept.
3. Transshipment proxies, framed as patterns, not proof: HS6 products where China's share of US
   imports fell by >= 10 pp while a country with under 5% before reached >= 10% and gained at
   least $25m a year; with the gap between its HS10 unit values and China's (value-weighted mean
   |ln UV ratio|) before and after. Episodes: 2017 -> 2024 (after the 2018-19 Section 301
   tariffs) and 2024 -> the latest 12 months.
4. Chart 4 data: 12-month rolling import shares by supplier group for products on the 2018-19
   Section 301 lists (HS10 families with a China Section 301 rate in 2019-12) and all others.

Run: make diversion -> data/published/diversion.csv, diversion_shares.csv,
     transshipment_flags.csv
"""

import time
from dataclasses import dataclass
from datetime import date

import duckdb
import polars as pl
import pyfixest as pf

from tpt import config
from tpt.build import concordance
from tpt.build.tariff_rates import OUT as RATES
from tpt.ingest import census_trade
from tpt.models import border_pt as bp

OUT = config.PUBLISHED_DIR / "diversion.csv"
SHARES_OUT = config.PUBLISHED_DIR / "diversion_shares.csv"
FLAGS_OUT = config.PUBLISHED_DIR / "transshipment_flags.csv"
COUNTRIES = config.REFERENCE_DIR / "census_countries.csv"
GROUPS_CSV = config.REFERENCE_DIR / "country_groups.csv"
IMPORTS = census_trade.INTERIM_IMPORTS
CHINA = "5700"

CHINA_DROP = -0.10  # China's share change in the product
PRIOR_MAX = 0.05  # country's share before
POST_MIN = 0.10  # country's share after
MIN_GAIN = 25e6  # annual value gained, $

# Chart 4 supplier groups (Census codes from data/reference/census_countries.csv), fixed order.
OTHER_SEA = ["5490", "5570", "5600", "5550", "5650", "5590", "5530", "5460"]
GROUPS = {
    "China": [CHINA], "Vietnam": ["5520"], "Taiwan": ["5830"], "Mexico": ["2010"],
    "Other Southeast Asia": OTHER_SEA, "India": ["5330"], "EU": None,  # EU27 from country_groups
    "Rest of world": [],
}  # fmt: skip


def months_between(a: date, b: date) -> list[date]:
    out, m = [], a
    while m <= b:
        out.append(m)
        m = date(m.year + m.month // 12, m.month % 12 + 1, 1)
    return out


@dataclass(frozen=True)
class Period:
    start: date
    end: date | None  # None: latest full quarter
    weight_year: int
    base: tuple[date, date]
    post: tuple[date, date]
    pre: tuple[tuple[date, date], tuple[date, date]] | None = None  # pair pre-trend windows


PERIODS = {
    "2018_19": Period(date(2017, 1, 1), date(2019, 12, 1), 2017,
                      (date(2017, 6, 1), date(2018, 1, 1)), (date(2019, 6, 1), date(2020, 1, 1))),
    "2025_26": Period(date(2023, 1, 1), None, 2024,
                      (date(2023, 6, 1), date(2024, 1, 1)), (date(2025, 6, 1), date(2026, 1, 1)),
                      ((date(2021, 6, 1), date(2021, 12, 1)),
                       (date(2023, 6, 1), date(2023, 12, 1)))),
}  # fmt: skip
FLAG_EPISODES = {
    "2017_to_2024": ((date(2017, 1, 1), date(2017, 12, 1)), (date(2024, 1, 1), date(2024, 12, 1))),
    "2024_to_latest": ((date(2024, 1, 1), date(2024, 12, 1)), None),  # post: latest 12 months
}


# --- rates -------------------------------------------------------------------------


def hs6_rates(rates: pl.DataFrame, base: pl.DataFrame) -> pl.DataFrame:
    """HS6 x country x month statutory rate: HS10 rates weighted by base-year value (unweighted
    when no HS10 of the pair has base value)."""
    r = (
        rates.join(base, on=["hs10", "cty_code"], how="left")
        .with_columns(hs6=pl.col("hs10").str.slice(0, 6), w=pl.col("w").fill_null(0.0))
        .group_by("hs6", "cty_code", "month")
        .agg(
            wr=(pl.col("w") * pl.col("rate_total")).sum(),
            w=pl.col("w").sum(),
            mean=pl.col("rate_total").mean(),
        )  # fmt: skip
    )
    rate = pl.when(pl.col("w") > 0).then(pl.col("wr") / pl.col("w")).otherwise(pl.col("mean"))
    return r.select("hs6", "cty_code", "month", rate=rate)


def fill_rates(r: pl.DataFrame, months: list[date]) -> pl.DataFrame:
    """Every pair x month in `months`; months without a rate take the previous (else next)."""
    grid = r.select("hs6", "cty_code").unique().join(pl.DataFrame({"month": months}), how="cross")
    return (
        grid.join(r, on=["hs6", "cty_code", "month"], how="left")
        .sort("hs6", "cty_code", "month")
        .with_columns(pl.col("rate").forward_fill().backward_fill().over("hs6", "cty_code"))
    )


# --- long differences and PPML -------------------------------------------------------


def _window_sum(flows: pl.DataFrame, w: tuple[date, date], s: str) -> pl.DataFrame:
    return (
        flows.filter(pl.col("month").is_between(*w))
        .group_by("hs6", "cty_code")
        .agg(
            pl.col("value").sum().alias(f"v_{s}"), pl.col("rate").log1p().mean().alias(f"tau_{s}")
        )  # fmt: skip
    )


def long_diff(flows: pl.DataFrame, p: Period) -> pl.DataFrame:
    """HS6 x country: values, shares and mean ln(1 + tau) in the base and post windows."""
    d = _window_sum(flows, p.base, "b").join(
        _window_sum(flows, p.post, "p"), on=["hs6", "cty_code"], how="full", coalesce=True
    )
    d = d.with_columns(pl.col("v_b", "v_p").fill_null(0.0))
    share = [(pl.col(f"v_{s}") / pl.col(f"v_{s}").sum().over("hs6")).alias(f"share_{s}")
             for s in "bp"]  # fmt: skip
    pos = (pl.col("v_b") > 0) & (pl.col("v_p") > 0)
    return d.with_columns(share).with_columns(
        dtau=pl.col("tau_p") - pl.col("tau_b"),
        dln_v=pl.when(pos).then(pl.col("v_p").log() - pl.col("v_b").log()),
        dshare=pl.col("share_p") - pl.col("share_b"),
        china=(pl.col("cty_code") == CHINA).cast(pl.Float64),
    )


def pre_growth(p: Period) -> pl.DataFrame:
    """hs6 x country: ln value growth between the two pre-trend windows (two years apart)."""
    (a0, a1), (b0, b1) = p.pre
    v = flows_hs6(a0, b1)
    win = [v.filter(pl.col("month").is_between(lo, hi)).group_by("hs6", "cty_code")
           .agg(pl.col("value").sum().alias(n))
           for (lo, hi), n in (((a0, a1), "a"), ((b0, b1), "b"))]  # fmt: skip
    return (
        win[0]
        .join(win[1], on=["hs6", "cty_code"])
        .select("hs6", "cty_code", dln_v_pre=pl.col("b").log() - pl.col("a").log())
    )


def fit_ld(ld: pl.DataFrame, y: str, fe: tuple[str, ...], weights: str | None = None,
           xs: tuple[str, ...] = ("dtau",)) -> dict:  # fmt: skip
    d = ld.drop_nulls([y, *xs])
    if weights:
        d = d.filter(pl.col(weights) > 0)
    rows = bp.fit_terms(d, y, list(xs), fe, "hs6", weights=weights)
    return rows[0] if len(xs) == 1 else {r["term"]: r for r in rows}


def quarterly(flows: pl.DataFrame) -> pl.DataFrame:
    q = pl.col("month").dt.year() * 10 + pl.col("month").dt.quarter()
    return (
        flows.with_columns(quarter=q.cast(pl.String))
        .group_by("hs6", "cty_code", "quarter")
        .agg(pl.col("value").sum(), lntau=pl.col("rate").log1p().mean())
        .sort("hs6", "cty_code", "quarter")
    )


def fit_ppml(q: pl.DataFrame, fe: tuple[str, ...], cluster: str = "hs6") -> dict:
    keys = {f for e in fe for f in e.split("^")} | {cluster}
    data = q.select("value", "lntau", *keys).to_pandas()
    m = pf.fepois(f"value ~ lntau | {' + '.join(fe)}", data=data, vcov={"CRV1": cluster})
    t = m.tidy()
    return {"term": "lntau", "coef": float(t.loc["lntau", "Estimate"]),
            "se": float(t.loc["lntau", "Std. Error"]), "ci_low": float(t.loc["lntau", "2.5%"]),
            "ci_high": float(t.loc["lntau", "97.5%"]), "n": int(m._N), "fe": " + ".join(fe),
            "cluster": cluster}  # fmt: skip


# --- transshipment proxies ------------------------------------------------------------


def flag_pairs(d: pl.DataFrame, min_gain: float = MIN_GAIN) -> pl.DataFrame:
    """Countries that went from under PRIOR_MAX to at least POST_MIN of a product's imports
    while China's share fell by at least |CHINA_DROP|, gaining min_gain or more."""
    s = d.with_columns(
        share_b=pl.col("v_b") / pl.col("v_b").sum().over("hs6"),
        share_p=pl.col("v_p") / pl.col("v_p").sum().over("hs6"),
    )
    cn = s.filter(pl.col("cty_code") == CHINA).select(
        "hs6", china_share_b="share_b", china_share_p="share_p"
    )
    return (
        s.join(cn, on="hs6")
        .filter(
            pl.col("cty_code") != CHINA,
            pl.col("china_share_p") - pl.col("china_share_b") <= CHINA_DROP,
            pl.col("share_b") < PRIOR_MAX,
            pl.col("share_p") >= POST_MIN,
            pl.col("v_p") - pl.col("v_b") >= min_gain,
        )  # fmt: skip
        .with_columns(gain=pl.col("v_p") - pl.col("v_b"))
        .sort("gain", descending=True)
        .select(
            "hs6",
            "cty_code",
            "v_b",
            "v_p",
            "gain",
            "share_b",
            "share_p",
            "china_share_b",
            "china_share_p",
        )  # fmt: skip
    )


def uv_gap(df: pl.DataFrame) -> pl.DataFrame:
    """hs6 x country: value-weighted mean |ln(UV / China's UV)| over HS10s both supplied."""
    u = df.filter(pl.col("qty") > 0).with_columns(uv=pl.col("value") / pl.col("qty"))
    cn = u.filter(pl.col("cty_code") == CHINA).select("hs10", uv_cn="uv")
    return (
        u.filter(pl.col("cty_code") != CHINA)
        .join(cn, on="hs10")
        .with_columns(g=(pl.col("uv") / pl.col("uv_cn")).log().abs())
        .group_by("hs6", "cty_code")
        .agg(uv_gap=(pl.col("g") * pl.col("value")).sum() / pl.col("value").sum())
    )


# --- shares for chart 4 ----------------------------------------------------------------


def group_shares(df: pl.DataFrame, window: int = 12) -> pl.DataFrame:
    """panel x month x group: rolling `window`-month value and share of the panel's total."""
    grid = (
        df.select("panel").unique()
        .join(df.select("month").unique(), how="cross")
        .join(df.select("group").unique(), how="cross")
    )  # fmt: skip
    g = (
        grid.join(
            df.group_by("panel", "month", "group").agg(pl.col("value").sum()),
            on=["panel", "month", "group"],
            how="left",
        )  # fmt: skip
        .with_columns(pl.col("value").fill_null(0.0))
        .sort("panel", "group", "month")
        .with_columns(
            value_r=pl.col("value").rolling_sum(window).over("panel", "group"),
        )
        .drop_nulls("value_r")
    )
    return g.with_columns(
        share=pl.col("value_r") / pl.col("value_r").sum().over("panel", "month")
    ).sort("panel", "month", "group")


# --- data --------------------------------------------------------------------------


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def _flows_sql(start: date, end: date, level: str = "hs6") -> str:
    key = "substr(i.hs10, 1, 6) as hs6" if level == "hs6" else "i.hs10, substr(i.hs10, 1, 6) as hs6"
    qty = "" if level == "hs6" else ", sum(i.con_qy1_mo)::double as qty"
    return f"""
        select {key}, i.cty_code, i.month, sum(i.con_val_mo)::double as value{qty}
        from read_parquet('{IMPORTS}/*/data.parquet', hive_partitioning = 1) i
        join (select cty_code from read_csv('{COUNTRIES}', all_varchar = true)
              where is_individual = 'true') c using (cty_code)
        where i.summary_lvl = 'DET' and i.con_val_mo > 0
          and substr(i.hs10, 1, 2) not in ('98', '99')
          and i.month between date '{start}' and date '{end}'
        group by all
    """


def flows_hs6(start: date, end: date) -> pl.DataFrame:
    return _con().sql(_flows_sql(start, end)).pl()


def base_weights(year: int) -> pl.DataFrame:
    return (
        _con()
        .sql(f"""select hs10, cty_code, sum(value) as w
                 from ({_flows_sql(date(year, 1, 1), date(year, 12, 1), "hs10")}) group by all""")
        .pl()
    )


def period_flows(p: Period, end: date) -> pl.DataFrame:
    """HS6 x country x month value and filled statutory rate, start..max(end, post window)."""
    last = max(end, p.post[1])
    rates = (
        pl.scan_parquet(RATES)
        .filter(pl.col("month").is_between(p.start, last))
        .select("hs10", "cty_code", "month", "rate_total")
        .collect()
    )
    r = fill_rates(hs6_rates(rates, base_weights(p.weight_year)), months_between(p.start, last))
    v = flows_hs6(p.start, last)
    return r.join(v, on=["hs6", "cty_code", "month"], how="left").with_columns(
        pl.col("value").fill_null(0.0)
    )


def latest_month() -> date:
    return pl.scan_parquet(RATES).select(pl.col("month").max()).collect().item()


def full_quarter_end(m: date) -> date:
    q_end = {3: 3, 6: 6, 9: 9, 12: 12}
    while m.month not in q_end:
        m = date(m.year - (m.month == 1), (m.month - 2) % 12 + 1, 1)
    return m


# --- run ---------------------------------------------------------------------------


def run_estimates(t0: float) -> pl.DataFrame:
    rows = []
    for name, p in PERIODS.items():
        end = p.end or full_quarter_end(latest_month())
        flows = period_flows(p, end)
        print(f"{name}: {flows.height:,} HS6 x country x month rows, "
              f"{flows.select('hs6', 'cty_code').n_unique():,} pairs ({time.time() - t0:.0f}s)",
              flush=True)  # fmt: skip
        ld = long_diff(flows, p)
        specs = [
            ("ld_main", "dln_v", ("hs6",), None),
            ("ld_cty_fe", "dln_v", ("hs6", "cty_code"), None),
            ("ld_weighted", "dln_v", ("hs6",), "v_b"),
            ("ld_share", "dshare", ("hs6",), "v_b"),
            ("ld_share_unweighted", "dshare", ("hs6",), None),
        ]
        for spec, y, fe, w in specs:
            r = fit_ld(ld, y, fe, w)
            rows.append({"period": name, "model": "long_diff", "spec": spec, "outcome": y,
                         **r, "weights": w})  # fmt: skip
        if p.pre:
            ld = ld.join(pre_growth(p), on=["hs6", "cty_code"], how="left").with_columns(
                dln_v_dd=pl.col("dln_v") - pl.col("dln_v_pre")
            )
            specs = [("ld_pretrend", "dln_v_dd", ("hs6",), None),
                     ("ld_pretrend_cty_fe", "dln_v_dd", ("hs6", "cty_code"), None),
                     ("ld_pretrend_weighted", "dln_v_dd", ("hs6",), "v_b")]  # fmt: skip
            for spec, y, fe, w in specs:
                r = fit_ld(ld, y, fe, w)
                rows.append({"period": name, "model": "long_diff", "spec": spec, "outcome": y,
                             **r, "weights": w})  # fmt: skip
        split = ld.with_columns(dtau_china=pl.col("dtau") * pl.col("china"),
                                dtau_other=pl.col("dtau") * (1 - pl.col("china")))  # fmt: skip
        for r in fit_ld(split, "dln_v", ("hs6",), xs=("dtau_china", "dtau_other")).values():
            rows.append({"period": name, "model": "long_diff", "spec": "ld_china_split",
                         "outcome": "dln_v", **r, "weights": None})  # fmt: skip
        # flow size: small pairs that trade in both windows are noisy and selected on growth
        for spec, q in (("ld_base_ge_median", 0.5), ("ld_base_ge_p90", 0.9)):
            r = fit_ld(ld.filter(pl.col("v_b") >= ld["v_b"].quantile(q)), "dln_v", ("hs6",))
            rows.append({"period": name, "model": "long_diff", "spec": spec, "outcome": "dln_v",
                         **r, "weights": None})  # fmt: skip
        for r in [r for r in rows if r["period"] == name]:
            print(f"  {name} {r['spec']:<20} {r['term']:<10} b = {r['coef']:+.3f} ({r['se']:.3f})"
                  f"  n = {r['n']:,}", flush=True)  # fmt: skip

        traded = (
            flows.filter(pl.col("month").dt.year() == p.weight_year, pl.col("value") > 0)
            .select("hs6", "cty_code").unique()
        )  # fmt: skip
        q = quarterly(
            flows.filter(pl.col("month").is_between(p.start, end)).join(
                traded, on=["hs6", "cty_code"]
            )
        )
        for spec, fe in (("ppml", ("hs6^quarter", "hs6^cty_code")),
                         ("ppml_cty_quarter", ("hs6^quarter", "hs6^cty_code",
                                               "cty_code^quarter"))):  # fmt: skip
            r = fit_ppml(q, fe)
            rows.append({"period": name, "model": "ppml", "spec": spec, "outcome": "value",
                         **r, "weights": None})  # fmt: skip
            print(f"  {name} {spec:<20} b = {r['coef']:+.3f} ({r['se']:.3f})  n = {r['n']:,} "
                  f"({time.time() - t0:.0f}s)", flush=True)  # fmt: skip
    return pl.DataFrame(rows, infer_schema_length=None)


def run_flags(t0: float) -> pl.DataFrame:
    latest = latest_month()
    names = (
        pl.read_csv(COUNTRIES, infer_schema=False).select("cty_code", "cty_name").unique("cty_code")
    )
    desc = (
        pl.scan_parquet(concordance.ATTRIBUTES_PATH)
        .select("year", "hs6", "desc_short")
        .sort("year")
        .group_by("hs6")
        .agg(desc=pl.col("desc_short").last())
        .collect()
    )
    out = []
    for ep, (b, post) in FLAG_EPISODES.items():
        post = post or (months_between(date(latest.year - 1, latest.month, 1), latest)[1],
                        latest)  # fmt: skip
        con = _con()
        h = {s: con.sql(_flows_sql(*w, level="hs10")).pl() for s, w in (("b", b), ("p", post))}
        v = (
            h["b"].group_by("hs6", "cty_code").agg(v_b=pl.col("value").sum())
            .join(h["p"].group_by("hs6", "cty_code").agg(v_p=pl.col("value").sum()),
                  on=["hs6", "cty_code"], how="full", coalesce=True)
            .with_columns(pl.col("v_b", "v_p").fill_null(0.0))
        )  # fmt: skip
        # products in both periods only (HS 2022 renumbered some HS6s)
        both = (
            v.group_by("hs6")
            .agg(pl.col("v_b").sum(), pl.col("v_p").sum())
            .filter((pl.col("v_b") > 0) & (pl.col("v_p") > 0))
        )
        f = flag_pairs(v.join(both.select("hs6"), on="hs6"))
        gaps = {s: uv_gap(h[s].group_by("hs10", "hs6", "cty_code")
                          .agg(pl.col("value", "qty").sum())).rename({"uv_gap": f"uv_gap_{s}"})
                for s in "bp"}  # fmt: skip
        f = (
            f.join(gaps["b"], on=["hs6", "cty_code"], how="left")
            .join(gaps["p"], on=["hs6", "cty_code"], how="left")
            .with_columns(
                uv_converged=pl.col("uv_gap_p") < pl.col("uv_gap_b"),
                episode=pl.lit(ep),
                base_start=b[0],
                base_end=b[1],
                post_start=post[0],
                post_end=post[1],
            )  # fmt: skip
            .join(names, on="cty_code", how="left")
            .join(desc, on="hs6", how="left")
        )
        out.append(f)
        print(f"flags {ep}: {f.height} pairs, ${f['gain'].sum() / 1e9:.1f}bn gained; "
              f"{f['uv_converged'].sum()} with unit values converging on China's "
              f"({time.time() - t0:.0f}s)", flush=True)  # fmt: skip
    return pl.concat(out)


def run_shares(t0: float) -> pl.DataFrame:
    con = _con()
    s301 = (
        pl.scan_parquet(RATES)
        .filter(pl.col("month") == date(2019, 12, 1), pl.col("cty_code") == CHINA,
                pl.col("rate_s301") > 0)  # fmt: skip
        .select("hs10").collect()
        .join(pl.read_parquet(concordance.FAMILIES_PATH), on="hs10")
        .select("family").unique()
    )  # fmt: skip
    eu = pl.read_csv(GROUPS_CSV, infer_schema=False).filter(pl.col("group") == "EU27")
    code_group = {c: g for g, cs in GROUPS.items() if cs for c in cs} | {
        c: "EU" for c in eu["cty_code"]
    }
    v = con.sql(_flows_sql(date(2017, 1, 1), latest_month(), level="hs10")).pl()
    fam = pl.read_parquet(concordance.FAMILIES_PATH)
    v = (
        v.join(fam, on="hs10", how="left")
        .with_columns(
            panel=pl.when(pl.col("family").is_in(s301["family"].implode()))
            .then(pl.lit("s301")).otherwise(pl.lit("other")),
            group=pl.col("cty_code").replace_strict(code_group, default="Rest of world"),
        )
        .group_by("panel", "month", "group").agg(pl.col("value").sum())
    )  # fmt: skip
    s = group_shares(v)
    print(f"shares: {s['month'].min()}..{s['month'].max()} ({time.time() - t0:.0f}s)",
          flush=True)  # fmt: skip
    return s


def run() -> None:
    t0 = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shares = run_shares(t0)
    shares.write_csv(SHARES_OUT, float_precision=6)
    flags = run_flags(t0)
    flags.write_csv(FLAGS_OUT, float_precision=4)
    est = run_estimates(t0)
    est.write_csv(OUT, float_precision=5)
    print(f"wrote {OUT.name}, {SHARES_OUT.name}, {FLAGS_OUT.name} ({time.time() - t0:.0f}s)",
          flush=True)  # fmt: skip


if __name__ == "__main__":
    run()

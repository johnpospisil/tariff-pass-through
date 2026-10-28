"""HS10-family x country x month import panel (P12).

Product unit: the HS10 code when its family (P06) has the same codes this year and last year,
otherwise the family aggregate (`level` = "hs10" | "family"), so 12-month changes compare like
with like without blurring codes that did not change (P06 recommendation). Imports for
consumption only (duties are assessed on them), individual countries, value > 0.

Columns: prod_id, level, family, cty_code, month; con_val, cal_dut, dut_val, qty, unit;
unit_value (pre-duty: value / quantity), uv_duty_incl ((value + duties) / quantity),
eff_rate (calculated duties / value, all duties incl. MFN), stat_rate (P10 statutory additional
rate, value-weighted for families), mfn_rate and the P10 authority rates; 12-month changes
dln_val, dln_qty, dln_uv, dln_uv_dut (winsorised; raw in *_raw), dln_1p_tau_stat and
dln_1p_tau_eff (change in ln(1 + rate)); drop_reason (null = in the price sample).

Rows are flagged, not deleted: value changes stay usable for rows without a usable quantity.
drop_reason, first match: special_provision (HS chapters 98-99: US goods returned, low-value
estimates; Census records no duty), duty_outlier (duties above 5x value now or 12 months
earlier: over-quota tobacco/dairy shipments of a few $1,000; eff_rate set to null), no_base
(no imports 12 months earlier), mixed_units (a family aggregate mixing quantity units),
no_quantity (zero/missing quantity now or 12 months earlier), unit_change (quantity unit
differs from 12 months earlier), trimmed (only with mode="trim").

The quantity unit is the one in that year's Census HS10 list: the API's UNIT_QY1 is the current
unit for every month, so codes that had no quantity unit ("X") before 2020 (e.g. 8473.30.1180,
9503.00.0073; 10-15% of 2017-19 value) would otherwise look like real zero quantities.

All cleaning choices are in `Cleaning` (P17 varies them).

Run: make import-panel   (writes data/processed/import_panel.parquet, reports/qa/import_panel_*.csv)
"""

from dataclasses import dataclass

import duckdb
import polars as pl

from tpt import config
from tpt.build.tariff_rates import IMPORTS, RATE_COLS
from tpt.build.tariff_rates import OUT as RATES

OUT = config.PROCESSED_DIR / "import_panel.parquet"
STAGE = config.INTERIM_DIR / "import_panel_unwinsorised.parquet"
FAMILIES = config.PROCESSED_DIR / "hs10_families.parquet"
CODES = config.INTERIM_DIR / "hs10_codes.parquet"
COUNTRIES = config.REFERENCE_DIR / "census_countries.csv"
QA = config.PROJECT_ROOT / "reports" / "qa"

CHANGE_COLS = ("dln_uv", "dln_uv_dut", "dln_qty", "dln_val")
PRICE_COLS = ("dln_uv", "dln_uv_dut", "dln_qty")  # need a usable quantity
EXTRA_RATES = list(RATE_COLS)  # authority rates carried for heterogeneity (P16)


@dataclass(frozen=True)
class Cleaning:
    """Cleaning rules, kept in one place for the robustness grid (P17)."""

    winsor: tuple[float, float] = (0.01, 0.99)
    mode: str = "winsorize"  # or "trim": flag rows outside the bounds as drop_reason "trimmed"
    cols: tuple[str, ...] = CHANGE_COLS
    trim_cols: tuple[str, ...] = ("dln_uv",)
    special_prefixes: tuple[str, ...] = ("98", "99")
    no_quantity_units: tuple[str, ...] = ("X", "-")
    max_eff_rate: float = 5.0  # duties / value above this (tiny over-quota shipments) are outliers


def _wavg(col: str) -> str:
    return f"sum({col} * con_val) / sum(con_val) as {col}"


def _sql(imp: str, fam: str, codes: str, rules: Cleaning) -> str:
    rates = ["rate_total", "mfn_rate", *EXTRA_RATES]
    rate_list = ", ".join(rates)
    special = " or ".join(f"c.prod_id like '{p}%'" for p in rules.special_prefixes)
    noq = ", ".join(f"'{u}'" for u in rules.no_quantity_units)
    return f"""
    with d as (
      select i.*, coalesce(f.family, i.hs10) as family
      from {imp} i left join {fam} f using (hs10)),
    cf as (
      select c.year, coalesce(f.family, c.hs10) as family, list_sort(list(distinct c.hs10)) codes
      from {codes} c left join {fam} f using (hs10) group by all),
    stab as (
      select a.family, a.year, (b.codes is null or a.codes = b.codes) as stable
      from cf a left join cf b on b.family = a.family and b.year = a.year - 1),
    lvl as (
      select d.*, coalesce(s.stable, true) as stable
      from d left join stab s on s.family = d.family and s.year = year(d.month)),
    h as (
      select hs10 as prod_id, 'hs10' as level, family, cty_code, month, con_val, cal_dut,
             dut_val, qty, unit, false as mixed, {rate_list}, stable
      from lvl),
    fa as (
      select family as prod_id, 'family' as level, family, cty_code, month,
             sum(con_val) as con_val, sum(cal_dut) as cal_dut, sum(dut_val) as dut_val,
             case when count(distinct unit) = 1 then sum(qty) end as qty,
             case when count(distinct unit) = 1 then min(unit) end as unit,
             count(distinct unit) > 1 as mixed,
             {", ".join(_wavg(r) for r in rates)},
             bool_and(stable) as stable
      from lvl where family in (select family from stab where not stable)
      group by family, cty_code, month),
    cur as (
      select * from h where stable
      union all by name
      select * from fa where not stable),
    base as (select * from h union all by name select * from fa),
    j as (
      select c.*, b.con_val as con_val_b, b.cal_dut as cal_dut_b, b.qty as qty_b,
             b.unit as unit_b, b.mixed as mixed_b, b.rate_total as rate_total_b,
             b.prod_id is not null as has_base
      from cur c left join base b
        on b.prod_id = c.prod_id and b.level = c.level and b.cty_code = c.cty_code
       and b.month = c.month - interval 12 month),
    r as (
      select *,
        case when {special} then 'special_provision'
             when cal_dut > {rules.max_eff_rate} * con_val
               or cal_dut_b > {rules.max_eff_rate} * con_val_b then 'duty_outlier'
             when not has_base then 'no_base'
             when mixed or mixed_b then 'mixed_units'
             when coalesce(qty, 0) <= 0 or coalesce(qty_b, 0) <= 0 or unit in ({noq})
               then 'no_quantity'
             when unit <> unit_b then 'unit_change'
        end as drop_reason
      from j c)
    select prod_id, level, family, cty_code, month, con_val, cal_dut, dut_val, qty, unit,
      case when drop_reason is distinct from 'mixed_units' and qty > 0 then con_val / qty end
        as unit_value,
      case when drop_reason is distinct from 'mixed_units' and qty > 0
        then (con_val + cal_dut) / qty end as uv_duty_incl,
      case when cal_dut <= {rules.max_eff_rate} * con_val then cal_dut / con_val end as eff_rate,
      rate_total as stat_rate, {", ".join(rates[1:])},
      case when drop_reason is null
             or drop_reason not in ('special_provision', 'no_base', 'duty_outlier')
        then ln(con_val / con_val_b) end as dln_val,
      case when drop_reason is null then ln(qty / qty_b) end as dln_qty,
      case when drop_reason is null then ln((con_val / qty) / (con_val_b / qty_b)) end
        as dln_uv,
      case when drop_reason is null
        then ln(((con_val + cal_dut) / qty) / ((con_val_b + cal_dut_b) / qty_b)) end
        as dln_uv_dut,
      case when has_base then ln(1 + rate_total) - ln(1 + rate_total_b) end
        as dln_1p_tau_stat,
      case when has_base and drop_reason is distinct from 'duty_outlier'
        then ln(1 + cal_dut / con_val) - ln(1 + cal_dut_b / con_val_b) end as dln_1p_tau_eff,
      drop_reason
    from r
    """


def build(imports: pl.DataFrame, families: pl.DataFrame, codes: pl.DataFrame,
          rules: Cleaning | None = None) -> pl.DataFrame:  # fmt: skip
    """Unwinsorised panel from in-memory inputs (same SQL as `run`).

    imports: hs10, cty_code, month, con_val, cal_dut, dut_val, qty, unit, rate_total, mfn_rate
    (authority rate columns optional); families: hs10, family; codes: year, hs10."""
    rules = rules or Cleaning()
    imp = imports.with_columns(
        [pl.lit(0.0).alias(c) for c in EXTRA_RATES if c not in imports.columns]
    )
    con = duckdb.connect()
    con.register("imp", imp)
    con.register("fam", families)
    con.register("codes", codes)
    return con.sql(_sql("imp", "fam", "codes", rules)).pl()


def winsorise(df: pl.DataFrame | pl.LazyFrame, rules: Cleaning,
              cols: list[str] | None = None) -> pl.DataFrame | pl.LazyFrame:  # fmt: skip
    """Winsorise (or trim) log changes at the rules' percentiles, pooled over the sample rows
    (drop_reason null); raw values are kept in <col>_raw."""
    lazy = df.lazy()
    names = lazy.collect_schema().names()
    lo, hi = rules.winsor
    cols = list(cols or (rules.trim_cols if rules.mode == "trim" else rules.cols))
    sample = lazy.filter(pl.col("drop_reason").is_null())
    q = sample.select(
        [pl.col(c).quantile(lo).alias(f"{c}_lo") for c in cols]
        + [pl.col(c).quantile(hi).alias(f"{c}_hi") for c in cols]
    ).collect()
    bounds = {c: (q[f"{c}_lo"][0], q[f"{c}_hi"][0]) for c in cols}
    out = lazy.with_columns([pl.col(c).alias(f"{c}_raw") for c in cols])
    if rules.mode == "winsorize":
        out = out.with_columns([pl.col(c).clip(*bounds[c]) for c in cols])
    elif rules.mode == "trim":
        outside = pl.any_horizontal(
            [(pl.col(c) < bounds[c][0]) | (pl.col(c) > bounds[c][1]) for c in cols]
        )
        flag = pl.col("drop_reason").is_null() & outside.fill_null(False)
        out = out.with_columns(
            drop_reason=pl.when(flag).then(pl.lit("trimmed")).otherwise("drop_reason")
        ).with_columns(
            [pl.when(pl.col("drop_reason") == "trimmed").then(None).otherwise(c).alias(c)
             for c in PRICE_COLS if c in names]
        )  # fmt: skip
    else:
        raise ValueError(f"unknown cleaning mode {rules.mode!r}")
    return out.collect() if isinstance(df, pl.DataFrame) else out


def drop_report(df: pl.DataFrame | pl.LazyFrame, by: list[str] | None = None) -> pl.DataFrame:
    """Rows and import value by drop_reason (null = retained), with value shares within `by`."""
    by = by or []
    total = pl.col("value_bn").sum()
    t = (
        df.lazy()
        .group_by([*by, "drop_reason"])
        .agg(rows=pl.len(), value_bn=pl.col("con_val").sum() / 1e9)
        .with_columns(value_share=pl.col("value_bn") / (total.over(by) if by else total))
    )
    return t.collect().sort([*by, "drop_reason"], nulls_last=True)


def _imports_sql() -> str:
    rates = ", ".join(f"r.{c}" for c in ["rate_total", "mfn_rate", *EXTRA_RATES])
    return f"""
        select i.hs10, i.cty_code, i.month, sum(i.con_val_mo)::double as con_val,
               sum(i.cal_dut_mo)::double as cal_dut, sum(i.dut_val_mo)::double as dut_val,
               sum(i.con_qy1_mo)::double as qty,
               coalesce(any_value(u.unit_qy1), any_value(i.unit_qy1)) as unit, {rates}
        from read_parquet('{IMPORTS}/*/data.parquet', hive_partitioning = 1) i
        join (select cty_code from read_csv('{COUNTRIES}', all_varchar = true)
              where is_individual = 'true') c using (cty_code)
        left join '{RATES}' r using (hs10, cty_code, month)
        left join (select year, hs10, any_value(unit_qy1) as unit_qy1 from '{CODES}'
                   group by all) u on u.hs10 = i.hs10 and u.year = year(i.month)
        where i.summary_lvl = 'DET' and i.con_val_mo > 0
        group by i.hs10, i.cty_code, i.month, {rates}
    """


def run(rules: Cleaning | None = None) -> pl.DataFrame:
    rules = rules or Cleaning()
    con = duckdb.connect()
    con.sql("set memory_limit = '8GB'; set preserve_insertion_order = false")
    con.sql(f"create view imp as {_imports_sql()}")
    con.sql(f"create view fam as select hs10, family from '{FAMILIES}'")
    con.sql(f"create view codes as select distinct year, hs10 from '{CODES}'")
    STAGE.parent.mkdir(parents=True, exist_ok=True)
    print("building panel (DuckDB) ...", flush=True)
    con.sql(f"copy ({_sql('imp', 'fam', 'codes', rules)}) to '{STAGE}' (format parquet)")
    print("winsorising ...", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    winsorise(pl.scan_parquet(STAGE), rules).sink_parquet(OUT)
    panel = pl.scan_parquet(OUT)
    QA.mkdir(parents=True, exist_ok=True)
    period = (
        pl.when(pl.col("month").dt.year() <= 2019).then(pl.lit("2017-19"))
        .when(pl.col("month").dt.year() <= 2024).then(pl.lit("2020-24"))
        .otherwise(pl.lit("2025-26"))
    )  # fmt: skip
    overall = drop_report(panel)
    by_period = drop_report(panel.with_columns(period=period), by=["period"])
    overall.write_csv(QA / "import_panel_drops.csv", float_precision=4)
    by_period.write_csv(QA / "import_panel_drops_by_period.csv", float_precision=4)
    summary = panel.select(
        rows=pl.len(), keys=pl.struct("prod_id", "cty_code", "month").n_unique(),
        family_rows=(pl.col("level") == "family").sum(),
        value_bn=pl.col("con_val").sum() / 1e9,
        sample_rows=pl.col("drop_reason").is_null().sum(),
        sample_value_share=pl.col("con_val").filter(pl.col("drop_reason").is_null()).sum()
        / pl.col("con_val").sum(),
    ).collect()  # fmt: skip
    pl.Config.set_tbl_cols(12)
    print(summary)
    print(overall)
    print(by_period)
    return summary


if __name__ == "__main__":
    run()

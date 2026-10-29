"""CPI item tariff exposure (P18).

For each CPI item, the import share of what consumers buy and the import-weighted tariff change,
by two routes:

- bea (main): HS10 -> NAICS -> BEA commodity (P06 attributes) -> PCE bridge line -> CPI item (P06
  crosswalk). Item -> commodity weights: each of the item's ELIs counts equally; an ELI mapped to
  several bridge lines splits by the lines' purchasers' value; a line splits over its commodities
  by producers' value. `w` (producers' basis) sums to 1 within each item; `w_purch` divides by
  purchasers' value instead, so trade and transport margins (domestic) dilute exposure.
  BEA commodities that one NAICS 2022 or 2012 code spans (cars 336111 + light trucks 336112 under
  336110, batteries, photographic equipment, ...) are pooled into one group: Census lists put
  every HS10 of such a code on the first commodity, so tariff changes and import shares are both
  measured on the pooled group.
- hand: CPI item -> HS prefixes for major goods (data/reference/cpi_hs_hand_map.csv, headings
  checked against Census HS10 descriptions); tariff change over those HS10s, import share from
  the bea route. It checks the HS -> item mapping of the tariff change, not the import share.

Import share of supply: imports (MCIF) / total product supply at basic prices (T013), BEA 2017
detail supply table. Tariff change: dln(1 + tau) against December of the base year, tau the
statutory additional rate (P10 rate_total), weighted by base-year customs value of HS10 x
individual country (chapters 98-99 excluded); an HS10 whose code changed takes its family's mean
rate. Effective: ln(1 + calculated duties / customs value) of the group's actual imports that
month, against the base-year average. Exposure = sum over goods groups of w_purch x import share
x dtau; dtau reported is that sum over the mapped goods import share.

Run: make exposure
Outputs: data/processed/cpi_exposure.parquet (window means), cpi_exposure_monthly.parquet,
         cpi_commodity_weights.parquet; data/published/cpi_exposure_top_bottom.csv;
         reports/qa/cpi_exposure_coverage.csv
"""

import time
from dataclasses import dataclass
from datetime import date

import polars as pl

from tpt import config
from tpt.build import concordance
from tpt.build.tariff_rates import OUT as RATES
from tpt.ingest import bea_io, census_trade

OUT = config.PROCESSED_DIR / "cpi_exposure.parquet"
MONTHLY_OUT = config.PROCESSED_DIR / "cpi_exposure_monthly.parquet"
WEIGHTS_OUT = config.PROCESSED_DIR / "cpi_commodity_weights.parquet"
TOP_OUT = config.PUBLISHED_DIR / "cpi_exposure_top_bottom.csv"
COVERAGE_OUT = config.PROJECT_ROOT / "reports" / "qa" / "cpi_exposure_coverage.csv"
HAND_MAP = config.REFERENCE_DIR / "cpi_hs_hand_map.csv"
COUNTRIES = config.REFERENCE_DIR / "census_countries.csv"
CPI_SERIES = config.REFERENCE_DIR / "bls_cpi_series.csv"

GOODS_SECTORS = ("11", "21", "31", "32", "33", "S00401", "S00402")  # plus scrap, used goods
SPECIAL_CHAPTERS = concordance.SPECIAL_CHAPTERS
GOODS_ITEM_MIN = 0.5  # goods share of an item's weight to count it as a goods item
TOP_N = 20


@dataclass(frozen=True)
class Period:
    base_year: int
    start: date  # exposure window
    end: date | None  # None: latest rate month

    @property
    def base_month(self) -> date:
        return date(self.base_year, 12, 1)


PERIODS = {
    "2018_19": Period(2017, date(2018, 1, 1), date(2019, 12, 1)),
    "2025_26": Period(2024, date(2025, 1, 1), None),
}


# --- concordance -------------------------------------------------------------------


def commodity_groups(splits: dict[str, list[str]], bea: pl.DataFrame) -> pl.DataFrame:
    """bea_code -> group: commodities that one older/newer NAICS code spans are pooled (id: the
    sorted member codes joined by '+'); every other commodity is its own group."""
    parent = {c: c for c in bea["bea_code"].unique()}

    def find(c: str) -> str:
        while parent[c] != c:
            parent[c] = parent[parent[c]]
            c = parent[c]
        return c

    for codes in splits.values():
        if len(codes) < 2:
            continue
        hits = concordance.naics_to_bea(pl.Series(codes), bea)["bea_code"].drop_nulls().unique()
        hits = [h for h in hits if h in parent]
        for h in hits[1:]:
            parent[find(h)] = find(hits[0])
    roots = {c: find(c) for c in parent}
    members: dict[str, list[str]] = {}
    for c, r in roots.items():
        members.setdefault(r, []).append(c)
    gid = {r: "+".join(sorted(m)) for r, m in members.items()}
    return pl.DataFrame({"bea_code": list(roots), "group": [gid[r] for r in roots.values()]}).sort(
        "bea_code"
    )


def _to_group(df: pl.DataFrame, groups: pl.DataFrame, col: str) -> pl.DataFrame:
    return df.join(groups, left_on=col, right_on="bea_code", how="left").with_columns(
        pl.coalesce("group", col).alias("group")
    )


def import_shares(supply: pl.DataFrame, groups: pl.DataFrame) -> pl.DataFrame:
    """Imports / total product supply (basic prices) per group, in [0, 1]."""
    s = (
        supply.filter(pl.col("column_code").is_in(["MCIF", "T013"]))
        .pivot(on="column_code", index="commodity_code", values="value", aggregate_function="sum")
        .pipe(_to_group, groups, "commodity_code")
        .group_by("group")
        .agg(imports=pl.col("MCIF").fill_null(0).sum(), supply=pl.col("T013").fill_null(0).sum())
    )
    share = pl.when(pl.col("supply") > 0).then(pl.col("imports") / pl.col("supply")).otherwise(0)
    return s.with_columns(import_share=share.clip(0, 1)).sort("group")


def item_weights(xwalk: pl.DataFrame, bridge: pl.DataFrame, groups: pl.DataFrame) -> pl.DataFrame:
    """item_code x group weights: w (producers' value, sums to 1 per item) and w_purch (share of
    purchasers' value; sums to 1 minus the margin share)."""
    lines = bridge.group_by("nipa_line").agg(
        purch=pl.col("purchasers_value").sum(),
        prod=pl.col("producers_value").clip(lower_bound=0).sum(),
    )
    x = (
        xwalk.drop_nulls(["item_code", "nipa_line"])
        .select("item_code", "eli", "nipa_line")
        .unique()
        .join(lines, on="nipa_line")
        .with_columns(w_line=pl.col("purch") / pl.col("purch").sum().over("item_code", "eli"))
        .with_columns(w_eli=1 / pl.col("eli").n_unique().over("item_code"))
    )
    comm = (
        bridge.filter(pl.col("producers_value") > 0)
        .pipe(_to_group, groups, "commodity_code")
        .join(lines, on="nipa_line")
        .select(
            "nipa_line",
            "group",
            wc=pl.col("producers_value") / pl.col("prod"),
            wc_purch=pl.col("producers_value") / pl.col("purch"),
        )
    )
    return (
        x.join(comm, on="nipa_line")
        .group_by("item_code", "group")
        .agg(
            w=(pl.col("w_eli") * pl.col("w_line") * pl.col("wc")).sum(),
            w_purch=(pl.col("w_eli") * pl.col("w_line") * pl.col("wc_purch")).sum(),
        )
        .sort("item_code", "group")
    )


# --- tariff changes ----------------------------------------------------------------


def pair_dtau(base: pl.DataFrame, rates: pl.DataFrame, families: pl.DataFrame,
              base_month: date) -> pl.DataFrame:  # fmt: skip
    """HS10 x country x month (from base_month): ln(1 + tau) - ln(1 + tau at base_month), with
    the base-year value. The rate panel has rows only for pairs traded that month: an HS10
    missing in a month (code change, or not traded) takes its family's mean ln(1 + tau) for the
    country; failing both at base_month, the pair's latest earlier rate in the base year."""
    r = rates.filter(pl.col("month").dt.year() >= base_month.year).select(
        "hs10", "cty_code", "month", ln=pl.col("rate_total").log1p()
    )
    fam = (
        r.join(families, on="hs10")
        .group_by("family", "cty_code", "month")
        .agg(ln_fam=pl.col("ln").mean())
    )
    months = r.select(pl.col("month").unique())
    p = (
        base.join(families, on="hs10", how="left")
        .with_columns(pl.coalesce("family", "hs10").alias("family"))
        .join(months, how="cross")
        .join(r, on=["hs10", "cty_code", "month"], how="left")
        .join(fam, on=["family", "cty_code", "month"], how="left")
        .with_columns(ln=pl.coalesce("ln", "ln_fam"))
        .drop("ln_fam")
        .drop_nulls("ln")
    )
    b = (
        p.filter(pl.col("month") <= base_month)
        .sort("month")
        .group_by("hs10", "cty_code")
        .agg(ln_b=pl.col("ln").last())
    )
    return (
        p.filter(pl.col("month") >= base_month)
        .join(b, on=["hs10", "cty_code"])
        .select("hs10", "cty_code", "group", "value", "month", dtau=pl.col("ln") - pl.col("ln_b"))
        .sort("hs10", "cty_code", "month")
    )


def group_dtau(pairs: pl.DataFrame) -> pl.DataFrame:
    """Base-value-weighted mean dtau per group and month."""
    return (
        pairs.group_by("group", "month")
        .agg(
            dtau=(pl.col("dtau") * pl.col("value")).sum() / pl.col("value").sum(),
            value=pl.col("value").sum(),
        )  # fmt: skip
        .sort("group", "month")
    )


def effective_dtau(flows: pl.DataFrame, base_year: int, key: str = "group") -> pl.DataFrame:
    """ln(1 + duties / customs value) per key and month, against the base-year average."""
    b = (
        flows.filter(pl.col("month").dt.year() == base_year)
        .group_by(key)
        .agg(ln_b=(pl.col("cal_dut").sum() / pl.col("con_val").sum()).log1p())
    )
    return (
        flows.group_by(key, "month")
        .agg(ln=(pl.col("cal_dut").sum() / pl.col("con_val").sum()).log1p())
        .join(b, on=key)
        .select(key, "month", dtau_eff=pl.col("ln") - pl.col("ln_b"))
        .sort(key, "month")
    )


def prefix_join(hand: pl.DataFrame, df: pl.DataFrame) -> pl.DataFrame:
    """Rows of df (with hs10) under each item's HS prefixes."""
    parts = [
        df.with_columns(hs_prefix=pl.col("hs10").str.slice(0, n)).join(
            hand.filter(pl.col("hs_prefix").str.len_chars() == n).select("item_code", "hs_prefix"),
            on="hs_prefix",
        )
        for n in hand["hs_prefix"].str.len_chars().unique()
    ]
    return pl.concat(parts).drop("hs_prefix").unique()


def hand_dtau(hand: pl.DataFrame, pairs: pl.DataFrame) -> pl.DataFrame:
    return (
        prefix_join(hand, pairs)
        .group_by("item_code", "month")
        .agg(dtau=(pl.col("dtau") * pl.col("value")).sum() / pl.col("value").sum())
        .sort("item_code", "month")
    )


# --- item series -------------------------------------------------------------------


def item_series(weights: pl.DataFrame, shares: pl.DataFrame, dtau: pl.DataFrame,
                goods: set[str]) -> pl.DataFrame:  # fmt: skip
    """item_code x month: import shares (purchasers' basis), exposure, dtau and coverage (mapped
    share of the goods import weight). Items with no tariffed imports get exposure 0."""
    w = weights.join(shares.select("group", "import_share"), on="group", how="left").with_columns(
        m=pl.col("w_purch") * pl.col("import_share").fill_null(0),
        goods=pl.col("group").is_in(list(goods)),
    )
    items = w.group_by("item_code").agg(
        import_share=pl.col("m").sum(),
        goods_import_share=pl.col("m").filter(pl.col("goods")).sum(),
        goods_weight=pl.col("w").filter(pl.col("goods")).sum(),
    )
    months = dtau.select(pl.col("month").unique())

    def agg(col: str, name: str) -> pl.DataFrame:
        d = dtau.drop_nulls(col).select("group", "month", col)
        return (
            w.filter("goods")
            .join(d, on="group")
            .group_by("item_code", "month")
            .agg(num=(pl.col("m") * pl.col(col)).sum(), den=pl.col("m").sum())
            .select(
                "item_code",
                "month",
                pl.col("num").alias(f"exposure{name}"),
                (pl.col("num") / pl.col("den")).alias(f"dtau{name}"),
                pl.col("den").alias(f"mapped{name}"),
            )  # fmt: skip
        )

    s = (
        items.join(months, how="cross")
        .join(agg("dtau", ""), on=["item_code", "month"], how="left")
        .join(agg("dtau_eff", "_eff"), on=["item_code", "month"], how="left")
        .with_columns(pl.col("exposure", "exposure_eff").fill_null(0))
    )
    cov = pl.col("mapped").fill_null(0) / pl.col("goods_import_share")
    return (
        s.with_columns(coverage=pl.when(pl.col("goods_import_share") > 0).then(cov))
        .drop("mapped", "mapped_eff")
        .sort("item_code", "month")
    )


def window_mean(s: pl.DataFrame, keys: list[str], cols: list[str], start: date,
                end: date) -> pl.DataFrame:  # fmt: skip
    return (
        s.filter(pl.col("month").is_between(start, end))
        .group_by(keys)
        .agg(pl.col(cols).mean())
        .sort(keys)
    )


# --- run ---------------------------------------------------------------------------


def _splits() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, old in (("naics_2022_2017", "naics_2022"), ("naics_2012_2017", "naics_2012")):
        for (code,), g in pl.read_parquet(bea_io.OUT[key]).group_by(old):
            out[f"{old}:{code}"] = g["naics_2017"].unique().to_list()
    return out


def _imports(years: list[int]) -> pl.LazyFrame:
    """HS10 x individual country x month customs value and calculated duties (DET rows)."""
    ctys = pl.read_csv(COUNTRIES, infer_schema=False).filter(pl.col("is_individual") == "true")
    return (
        pl.scan_parquet(census_trade.INTERIM_IMPORTS / "*" / "data.parquet")
        .filter(
            pl.col("summary_lvl") == "DET",
            pl.col("con_val_mo") > 0,
            pl.col("month").dt.year().is_in(years),
            ~pl.col("hs10").str.slice(0, 2).is_in(list(SPECIAL_CHAPTERS)),
        )  # fmt: skip
        .join(ctys.lazy().select("cty_code"), on="cty_code")
        .group_by("hs10", "cty_code", "month")
        .agg(
            con_val=pl.col("con_val_mo").sum().cast(pl.Float64),
            cal_dut=pl.col("cal_dut_mo").sum().cast(pl.Float64),
        )  # fmt: skip
    )


def goods_groups(groups: pl.DataFrame, mapped: set[str]) -> set[str]:
    is_goods = pl.col("bea_code").str.starts_with(GOODS_SECTORS[0])
    for p in GOODS_SECTORS[1:]:
        is_goods = is_goods | pl.col("bea_code").str.starts_with(p)
    return set(groups.filter(is_goods)["group"]) | mapped


def run_period(name: str, p: Period, attrs: pl.DataFrame, groups: pl.DataFrame,
               families: pl.DataFrame, hand: pl.DataFrame,
               t0: float) -> tuple[pl.DataFrame, pl.DataFrame, set[str]]:  # fmt: skip
    """Group-level (statutory and effective) and hand-item-level monthly changes."""
    end = p.end or pl.scan_parquet(RATES).select(pl.col("month").max()).collect().item()
    years = list(range(p.base_year, end.year + 1))
    hs_group = attrs.select("year", "hs10", "group")
    flows = (
        _imports(years)
        .filter(pl.col("month") <= end)
        .with_columns(year=pl.col("month").dt.year().cast(pl.Int32))
        .collect()
        .join(hs_group, on=["year", "hs10"], how="left")
    )
    base = (
        flows.filter(pl.col("year") == p.base_year)
        .group_by("hs10", "cty_code", "group")
        .agg(value=pl.col("con_val").sum())
    )
    unmapped = base.filter(pl.col("group").is_null())["value"].sum() / base["value"].sum()
    base = base.drop_nulls("group")
    print(f"{name}: {base.height:,} base HS10 x country pairs, "
          f"{unmapped:.2%} of base value without a BEA commodity ({time.time() - t0:.0f}s)",
          flush=True)  # fmt: skip
    rates = (
        pl.scan_parquet(RATES)
        .filter(pl.col("month").is_between(date(p.base_year, 1, 1), end))
        .select("hs10", "cty_code", "month", "rate_total")
        .collect()
    )
    pairs = pair_dtau(base, rates, families, p.base_month)
    cov = pairs.filter(pl.col("month") == end)["value"].sum() / base["value"].sum()
    print(f"{name}: {pairs.height:,} pair-months; {cov:.1%} of base value has a rate in {end} "
          f"({time.time() - t0:.0f}s)", flush=True)  # fmt: skip
    eff = effective_dtau(flows.drop_nulls("group"), p.base_year)
    g = group_dtau(pairs).join(eff, on=["group", "month"], how="full", coalesce=True)
    hand_eff = effective_dtau(prefix_join(hand, flows), p.base_year, key="item_code")
    h = hand_dtau(hand, pairs).join(hand_eff, on=["item_code", "month"], how="full",
                                    coalesce=True)  # fmt: skip
    g = g.filter(pl.col("month") >= p.base_month).with_columns(period=pl.lit(name), end=end)
    h = h.filter(pl.col("month") >= p.base_month).with_columns(period=pl.lit(name), end=end)
    return g, h, set(base["group"])


def run() -> pl.DataFrame:
    t0 = time.time()
    bea = pl.read_parquet(bea_io.OUT["naics"]).drop_nulls("naics_prefix")
    groups = commodity_groups(_splits(), bea)
    pooled = groups.filter(pl.col("group").str.contains(r"\+"))["group"].unique().sort()
    print(f"{groups.height} BEA commodities, {pooled.len()} pooled groups: "
          f"{', '.join(pooled)}", flush=True)  # fmt: skip
    supply = pl.read_parquet(bea_io.OUT["supply"])
    bridge = pl.read_parquet(bea_io.OUT["bridge"])
    xwalk = pl.read_parquet(concordance.CPI_PCE_PATH)
    shares = import_shares(supply, groups)
    weights = item_weights(xwalk, bridge, groups)
    names = (
        pl.read_csv(CPI_SERIES, infer_schema=False)
        .select("item_code", "item_name", "display_level")
        .unique("item_code")
    )
    attrs = (
        pl.read_parquet(concordance.ATTRIBUTES_PATH, columns=["year", "hs10", "bea_commodity"])
        .pipe(_to_group, groups, "bea_commodity")
        .select("year", "hs10", "group")
    )
    families = pl.read_parquet(concordance.FAMILIES_PATH)
    hand = pl.read_csv(HAND_MAP, infer_schema=False)

    monthly, mapped = [], set()
    for name, p in PERIODS.items():
        g, h, m = run_period(name, p, attrs, groups, families, hand, t0)
        mapped |= m
        monthly.append((name, p, g, h))
    goods = goods_groups(groups, mapped)

    out_m = []
    for name, p, g, h in monthly:
        s = item_series(weights, shares, g, goods).with_columns(route=pl.lit("bea"))
        hs = (
            s.select("item_code", "month", "import_share", "goods_import_share", "goods_weight")
            .join(h, on=["item_code", "month"])
            .with_columns(
                exposure=pl.col("goods_import_share") * pl.col("dtau"),
                exposure_eff=pl.col("goods_import_share") * pl.col("dtau_eff"),
                coverage=pl.lit(None, pl.Float64),
                route=pl.lit("hand"),
            )  # fmt: skip
            .select(s.columns)
        )
        end = g["end"][0]
        for r in (s, hs):
            out_m.append(r.with_columns(period=pl.lit(name), start=p.start, end=end))
    mon = pl.concat(out_m).join(names, on="item_code", how="left")
    cols = ["import_share", "goods_import_share", "goods_weight", "dtau", "exposure",
            "dtau_eff", "exposure_eff", "coverage"]  # fmt: skip
    summary = (
        mon.filter(pl.col("month").is_between(pl.col("start"), pl.col("end")))
        .group_by("route", "period", "item_code", "item_name", "display_level", "start", "end")
        .agg(pl.col(cols).mean())
        .sort("route", "period", "item_code")
    )

    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    weights.join(shares.select("group", "import_share"), on="group", how="left").with_columns(
        goods=pl.col("group").is_in(list(goods))
    ).write_parquet(WEIGHTS_OUT)
    mon.write_parquet(MONTHLY_OUT)
    summary.write_parquet(OUT)
    top_bottom(summary).write_csv(TOP_OUT, float_precision=5)
    coverage_report(summary, xwalk, names).write_csv(COVERAGE_OUT, float_precision=4)
    print(f"wrote {OUT.name}: {summary.height} rows; {MONTHLY_OUT.name}: {mon.height:,} rows "
          f"({time.time() - t0:.0f}s)", flush=True)  # fmt: skip
    return summary


def top_bottom(summary: pl.DataFrame, period: str = "2025_26") -> pl.DataFrame:
    """Top and bottom TOP_N goods items by bea-route exposure, with the hand route alongside."""
    keys = ["item_code", "item_name", "display_level"]
    bea = summary.filter(pl.col("route") == "bea", pl.col("period") == period,
                         pl.col("goods_weight") >= GOODS_ITEM_MIN)  # fmt: skip
    hand = summary.filter(pl.col("route") == "hand", pl.col("period") == period).select(
        "item_code", dtau_hand="dtau", exposure_hand="exposure"
    )
    t = bea.sort("exposure", descending=True)
    sel = ["rank_group", *keys, "import_share", "goods_import_share", "dtau", "exposure",
           "dtau_eff", "exposure_eff", "coverage", "dtau_hand", "exposure_hand"]  # fmt: skip
    return (
        pl.concat(
            [
                t.head(TOP_N).with_columns(rank_group=pl.lit("top")),
                t.tail(TOP_N).with_columns(rank_group=pl.lit("bottom")),
            ]
        )  # fmt: skip
        .join(hand, on="item_code", how="left")
        .select(sel)
    )


def coverage_report(summary: pl.DataFrame, xwalk: pl.DataFrame,
                    names: pl.DataFrame) -> pl.DataFrame:  # fmt: skip
    """Goods items whose tariff change covers under 90% of their goods import weight, and items
    with no bridge line (no exposure computed)."""
    low = summary.filter(pl.col("route") == "bea", pl.col("goods_weight") >= GOODS_ITEM_MIN,
                         pl.col("coverage") < 0.9).select(
        "period", "item_code", "item_name", "goods_weight", "goods_import_share", "coverage",
        issue=pl.lit("low_coverage"),
    )  # fmt: skip
    all_items = xwalk.drop_nulls("item_code").select("item_code").unique()
    have = summary.select("item_code").unique()
    none = (
        all_items.join(have, on="item_code", how="anti")
        .join(names.select("item_code", "item_name"), on="item_code", how="left")
        .with_columns(issue=pl.lit("no_bridge_line"))
    )
    return pl.concat([low, none], how="diagonal").sort("issue", "item_code")


if __name__ == "__main__":
    run()

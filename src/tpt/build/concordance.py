"""Reference concordances (P06).

1. HS10 families over time. Pierce & Schott (2012) link codes that change between years into
   time-invariant "families", using official change records. Their published concordance ends in
   2007 and Census publishes no machine-readable change list for 2017+, so codes are linked by
   prefix, in the same spirit:
     - a code dropped in year t is linked to codes added in t+1 that share its HS8; failing that
       its HS6; failing that its HS4;
     - a dropped code with no added match (merged into an existing code), and an added code with
       no dropped match (carved out of an existing code), are linked to continuing codes in the
       same HS8.
   Families are connected components; a single-code family keeps the HS10 as its id, otherwise
   the id is "F" + the smallest member code. Code sets per year are Census's annual list plus
   every HS10 seen in the trade data that year.
2. HS10 -> NAICS (Census annual lists; latest available year as fallback) -> BEA detail
   commodity (see `naics_to_bea`; NAICS 2012/2022 codes translated to 2017; Census scrap and
   used-goods codes hand-mapped in data/reference/census_special_naics_to_bea.csv).
3. HS6 -> Rauch class, by HS revision (HS2017 for 2017-2021, HS2022 from 2022).
4. CPI items <-> PCE categories: BLS ELI mapping; ELI -> current CPI strata ("SE" + first four
   characters), else its expenditure class; PCE series -> BEA bridge line by normalised text, else
   the hand map in data/reference/pce_series_to_bridge_line.csv (renamed goods lines).

Run: make concordance   (after make ingest-reference)
Outputs: data/processed/hs10_families.parquet, hs10_attributes.parquet, cpi_pce_crosswalk.parquet;
         reports/qa/concordance_coverage.csv
"""

import re
from collections import defaultdict
from collections.abc import Iterable

import polars as pl

from tpt import config
from tpt.ingest import bea_io, census_trade, cpi_pce_map, hs_codes, rauch

CENSUS_GLOB = census_trade.INTERIM_IMPORTS / "*" / "data.parquet"
FAMILIES_PATH = config.PROCESSED_DIR / "hs10_families.parquet"
ATTRIBUTES_PATH = config.PROCESSED_DIR / "hs10_attributes.parquet"
CPI_PCE_PATH = config.PROCESSED_DIR / "cpi_pce_crosswalk.parquet"
COVERAGE_REPORT = config.PROJECT_ROOT / "reports" / "qa" / "concordance_coverage.csv"
SPECIAL_NAICS_CSV = config.REFERENCE_DIR / "census_special_naics_to_bea.csv"
PCE_HAND_CSV = config.REFERENCE_DIR / "pce_series_to_bridge_line.csv"

PREFIX_LEVELS = (8, 6, 4)


# --- 1. families -------------------------------------------------------------


class _UnionFind:
    def __init__(self, items: Iterable[str]):
        self.parent = {x: x for x in items}

    def find(self, x: str) -> str:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _by_prefix(codes: Iterable[str], n: int) -> dict[str, list[str]]:
    index = defaultdict(list)
    for c in codes:
        index[c[:n]].append(c)
    return index


def hs10_families(codes_by_year: dict[int, set[str]]) -> pl.DataFrame:
    uf = _UnionFind(set().union(*codes_by_year.values()))
    years = sorted(codes_by_year)
    for y0, y1 in zip(years, years[1:], strict=False):
        prev, cur = codes_by_year[y0], codes_by_year[y1]
        dropped, added, kept = prev - cur, cur - prev, prev & cur
        added_idx = {n: _by_prefix(added, n) for n in PREFIX_LEVELS}
        kept_hs8 = _by_prefix(kept, 8)
        matched_added = set()
        for d in sorted(dropped):
            for n in PREFIX_LEVELS:
                if cands := added_idx[n].get(d[:n]):
                    for a in cands:
                        uf.union(d, a)
                    matched_added.update(cands)
                    break
            else:
                for k in kept_hs8.get(d[:8], []):
                    uf.union(d, k)
        for a in sorted(added - matched_added):
            for k in kept_hs8.get(a[:8], []):
                uf.union(a, k)

    members = defaultdict(list)
    for code in uf.parent:
        members[uf.find(code)].append(code)
    rows = []
    for group in members.values():
        fid = group[0] if len(group) == 1 else "F" + min(group)
        rows += [(code, fid) for code in group]
    return pl.DataFrame(rows, schema=["hs10", "family"], orient="row").sort("hs10")


# --- 2. NAICS -> BEA ---------------------------------------------------------


def naics_to_bea(
    naics: pl.Series,
    bea: pl.DataFrame,
    naics_2017: dict[str, list[str]] | None = None,
    special: dict[str, str] | None = None,
) -> pl.DataFrame:
    """Map Census NAICS codes onto BEA 2017 detail commodities, in order:

    1. longest-prefix match on BEA's "Related 2017 NAICS Codes";
    2. via the NAICS 2022->2017 and 2012->2017 concordances (`naics_2017`), first match wins;
    3. Census special codes hand-mapped in data/reference (`special`: scrap, used goods);
    4. a truncated code such as '1121XX': the first BEA code whose NAICS prefix starts with its
       digits.
    """
    prefixes = dict(zip(bea["naics_prefix"], bea["bea_code"], strict=True))
    lengths = sorted({len(p) for p in prefixes}, reverse=True)
    naics_2017, special = naics_2017 or {}, special or {}

    def digits_of(code: str) -> str:
        return re.sub(r"\D.*$", "", code)  # Census NAICS can carry trailing letters/X

    def direct(code: str) -> str | None:
        digits = digits_of(code)
        for n in lengths:
            if len(digits) >= n and (hit := prefixes.get(digits[:n])):
                return hit
        return None

    def match(code: str | None) -> str | None:
        if not code:
            return None
        if hit := direct(code):
            return hit
        if hit := next((h for c in naics_2017.get(code, []) if (h := direct(c))), None):
            return hit
        if code in special:
            return special[code]
        digits = digits_of(code)
        if len(digits) >= 3:
            return next((prefixes[p] for p in sorted(prefixes) if p.startswith(digits)), None)
        return None

    uniq = naics.unique().drop_nulls()
    return pl.DataFrame({"naics": uniq, "bea_code": [match(c) for c in uniq]},
                        schema={"naics": pl.String, "bea_code": pl.String})  # fmt: skip


def rauch_with_fallback(attrs: pl.DataFrame, rauch_hs6: pl.DataFrame) -> pl.DataFrame:
    """HS6 class for the year's HS revision; else the other revision's; else the HS4 mode."""
    cols = ["rauch_con", "rauch_lib", "rauch_mixed"]
    other = (
        rauch_hs6.sort("hs_revision", descending=True)
        .unique("hs6", keep="first")
        .drop("hs_revision")
    )
    hs4 = (
        rauch_hs6.with_columns(pl.col("hs6").str.slice(0, 4).alias("hs4"))
        .group_by("hs4", "rauch_con", "rauch_lib")
        .len()
        .sort(["hs4", "len", "rauch_con"], descending=[False, True, False])
        .unique("hs4", keep="first")
        .select("hs4", "rauch_con", "rauch_lib", pl.lit(True).alias("rauch_mixed"))
    )
    out = (
        attrs.join(rauch_hs6, on=["hs_revision", "hs6"], how="left")
        .join(other, on="hs6", how="left", suffix="_other")
        .join(
            hs4, left_on=pl.col("hs6").str.slice(0, 4), right_on="hs4", how="left", suffix="_hs4"
        )  # fmt: skip
    )
    source = (
        pl.when(pl.col("rauch_con").is_not_null()).then(pl.lit("hs6"))
        .when(pl.col("rauch_con_other").is_not_null()).then(pl.lit("hs6_other_revision"))
        .when(pl.col("rauch_con_hs4").is_not_null()).then(pl.lit("hs4_mode"))
    )  # fmt: skip
    return out.with_columns(
        source.alias("rauch_source"),
        *[pl.coalesce(c, f"{c}_other", f"{c}_hs4").alias(c) for c in cols],
    ).drop([f"{c}_{s}" for c in cols for s in ("other", "hs4")], strict=False)


# --- 4. CPI <-> PCE ----------------------------------------------------------


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _normalise_expr(col: str) -> pl.Expr:
    return pl.col(col).str.replace_all(r"\s+", " ").str.strip_chars().str.to_lowercase()


def eli_to_strata(eli: pl.Expr) -> pl.Expr:
    """2011-vintage ELI 'AA011' -> current CPI item strata series code 'SEAA01'."""
    return pl.when(eli.str.contains(r"^[A-Z]{2}\d{3}$")).then(pl.lit("SE") + eli.str.slice(0, 4))


def eli_to_expenditure_class(eli: pl.Expr) -> pl.Expr:
    """Fallback when a strata no longer exists: 'AB011' -> expenditure class 'SEAB'."""
    return pl.when(eli.str.contains(r"^[A-Z]{2}\d{3}$")).then(pl.lit("SE") + eli.str.slice(0, 2))


def cpi_pce_crosswalk(
    mapping: pl.DataFrame,
    bridge: pl.DataFrame,
    cpi: pl.DataFrame,
    hand_lines: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """ELI -> current CPI item (strata, else its expenditure class) and PCE series -> bridge line
    (normalised description match, else the hand map in data/reference)."""
    items = cpi.select("item_code", "item_name", "display_level").unique("item_code")
    lines = (
        bridge.select("nipa_line", "pce_category")
        .unique()
        .with_columns(_normalise_expr("pce_category").alias("pce_norm"))
        .unique("pce_norm")
    )
    known = set(items["item_code"])
    out = (
        mapping.with_columns(
            eli_to_strata(pl.col("eli")).alias("strata"),
            eli_to_expenditure_class(pl.col("eli")).alias("exp_class"),
            _normalise_expr("pce_desc").alias("pce_norm"),
        )
        .with_columns(
            pl.when(pl.col("strata").is_in(known))
            .then(pl.col("strata"))
            .when(pl.col("exp_class").is_in(known))
            .then(pl.col("exp_class"))
            .alias("item_code"),
            pl.when(pl.col("strata").is_in(known))
            .then(pl.lit("strata"))
            .when(pl.col("exp_class").is_in(known))
            .then(pl.lit("expenditure_class"))
            .alias("cpi_match"),
        )  # fmt: skip
        .join(items, on="item_code", how="left")
        .join(lines, on="pce_norm", how="left")
    )
    if hand_lines is not None:
        hand = hand_lines.select(
            "pce_code", pl.col("nipa_line").cast(pl.Int32).alias("hand_line"),
            pl.col("bridge_category").alias("hand_category"),
        )  # fmt: skip
        out = out.join(hand, on="pce_code", how="left").with_columns(
            pl.when(pl.col("nipa_line").is_null() & pl.col("hand_line").is_not_null())
            .then(pl.lit("hand")).when(pl.col("nipa_line").is_not_null())
            .then(pl.lit("description")).alias("pce_match"),
            pl.coalesce("nipa_line", "hand_line").alias("nipa_line"),
            pl.coalesce("pce_category", "hand_category").alias("pce_category"),
        ).drop("hand_line", "hand_category")  # fmt: skip
    return out.with_columns(
        pl.col("item_name").is_not_null().alias("strata_in_current_cpi"),
        pl.col("nipa_line").is_not_null().alias("pce_in_bridge"),
    ).drop("pce_norm", "strata", "exp_class")


# --- run ---------------------------------------------------------------------


def _codes_by_year(codes: pl.DataFrame, trade: pl.DataFrame) -> dict[int, set[str]]:
    both = pl.concat([codes.select("year", "hs10"), trade.select("year", "hs10")]).unique()
    return {y: set(g["hs10"]) for (y,), g in both.group_by("year")}


SPECIAL_CHAPTERS = ("98", "99")  # US goods returned, special provisions, low-value estimates


def _coverage(attrs: pl.DataFrame, trade_value: pl.DataFrame) -> pl.DataFrame:
    """Share of import value mapped, over regular goods (excluding HS chapters 98-99) and all."""
    df = trade_value.join(attrs, on=["year", "hs10"], how="left")
    regular = df.filter(~pl.col("hs10").str.slice(0, 2).is_in(SPECIAL_CHAPTERS))

    def share(frame: pl.DataFrame, col: str) -> float:
        return frame.filter(pl.col(col).is_not_null())["value"].sum() / frame["value"].sum()

    rows = [
        (col, share(regular, col), share(df, col))
        for col in ("family", "naics", "bea_commodity", "rauch_con")
    ]
    return pl.DataFrame(rows, schema=["mapping", "share_of_value", "share_incl_ch98_99"],
                        orient="row")  # fmt: skip


def run() -> None:
    codes = pl.read_parquet(hs_codes.INTERIM_PATH)
    trade_value = (
        pl.scan_parquet(CENSUS_GLOB)
        .group_by(pl.col("month").dt.year().cast(pl.Int32).alias("year"), "hs10")
        .agg(pl.col("gen_val_mo").sum().cast(pl.Float64).alias("value"))
        .collect()
    )

    families = hs10_families(_codes_by_year(codes, trade_value))
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    families.write_parquet(FAMILIES_PATH)

    # Attributes per (year, hs10): Census fields for that year, else the latest year listing it.
    latest = codes.sort("year").group_by("hs10").last().drop("year")
    keys = pl.concat([codes.select("year", "hs10"), trade_value.select("year", "hs10")]).unique()
    attrs = keys.join(codes, on=["year", "hs10"], how="left").join(
        latest, on="hs10", how="left", suffix="_latest"
    )
    for col in hs_codes.COLUMNS[1:]:
        attrs = attrs.with_columns(pl.coalesce(col, f"{col}_latest").alias(col)).drop(
            f"{col}_latest"
        )

    bea = pl.read_parquet(bea_io.OUT["naics"]).drop_nulls("naics_prefix")
    naics_2017: dict[str, list[str]] = defaultdict(list)
    for key, old_col in (("naics_2022_2017", "naics_2022"), ("naics_2012_2017", "naics_2012")):
        for (code,), g in pl.read_parquet(bea_io.OUT[key]).group_by(old_col):
            naics_2017[code] += g["naics_2017"].to_list()
    special = pl.read_csv(SPECIAL_NAICS_CSV, infer_schema=False)
    special_map = dict(zip(special["naics"], special["bea_code"], strict=True))
    attrs = attrs.join(
        naics_to_bea(attrs["naics"], bea, naics_2017, special_map), on="naics", how="left"
    ).rename({"bea_code": "bea_commodity"})

    rauch_hs6 = pl.read_parquet(rauch.INTERIM_PATH)
    attrs = (
        attrs.with_columns(
            pl.col("hs10").str.slice(0, 6).alias("hs6"),
            pl.col("year")
            .map_elements(rauch.hs_revision, return_dtype=pl.String)
            .alias("hs_revision"),
        )
        .pipe(rauch_with_fallback, rauch_hs6)
        .join(families, on="hs10", how="left")
        .sort("year", "hs10")
    )
    attrs.write_parquet(ATTRIBUTES_PATH)

    cpi = pl.read_csv(config.REFERENCE_DIR / "bls_cpi_series.csv", infer_schema=False)
    xwalk = cpi_pce_crosswalk(
        pl.read_parquet(cpi_pce_map.INTERIM_PATH),
        pl.read_parquet(bea_io.OUT["bridge"]),
        cpi,
        pl.read_csv(PCE_HAND_CSV, infer_schema=False),
    )
    xwalk.write_parquet(CPI_PCE_PATH)

    cov = _coverage(attrs, trade_value)
    COVERAGE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    cov.write_csv(COVERAGE_REPORT)

    multi = families.group_by("family").len().filter(pl.col("len") > 1)
    fam_value = trade_value.join(families, on="hs10").filter(pl.col("family").str.starts_with("F"))
    share = fam_value["value"].sum() / trade_value["value"].sum()
    print(
        f"HS10 families: {families.height:,} codes -> {families['family'].n_unique():,} families; "
        f"{multi.height:,} multi-code families (largest {multi['len'].max()} codes) hold "
        f"{share:.1%} of import value"
    )
    print("Coverage by import value 2017+ (regular goods / incl. ch. 98-99):")
    for m, a, b in cov.iter_rows():
        print(f"  {m:14} {a:.2%} / {b:.2%}")
    print("Rauch source by value:", attrs.join(trade_value, on=["year", "hs10"])
          .group_by("rauch_source").agg(pl.col("value").sum()).with_columns(
              (pl.col("value") / pl.col("value").sum()).round(4)).sort("value").rows())  # fmt: skip
    print(f"CPI-PCE crosswalk: {xwalk['eli'].n_unique()} ELIs; "
          f"{xwalk.filter('strata_in_current_cpi')['eli'].n_unique()} map to a current CPI item; "
          f"{xwalk.filter('pce_in_bridge')['pce_code'].n_unique()}/{xwalk['pce_code'].n_unique()} "
          "PCE series matched to a bridge line")  # fmt: skip


if __name__ == "__main__":
    run()

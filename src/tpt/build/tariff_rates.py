"""Expand tariff_actions.csv into an HS10 x country x month additional-duty panel (P10).

For every HS10 x country x month with recorded imports, the additional ad valorem duty from each
authority, as the day-weighted average over the month of the daily rate. On each day:

1. Actions covering the product and country that are in force (effective <= day < end).
   Products: hs_scope less hs_exclude, matched on HS prefixes; list files are extended to HS10
   codes that replaced listed codes (P06 families, see `_family_fill`). DE_MINIMIS rows are
   event markers and carry no rate.
2. supersedes: an action replaced by another in-force action covering the product drops out.
3. stacking: an action whose not_with names the authority or action group of another in-force
   action drops out (e.g. reciprocal on Section 232 goods). Actions with value_basis
   unidentified_subset (patented drugs, advanced chips, drones) do not trigger exclusions.
4. Rates: ad valorem as stated; all_in_floor as max(0, floor - MFN) with the HS10 MFN rate.
   USMCA (Canada, Mexico only): "exempt" scales the rate by (1 - s), "non_us_content" by
   (1 - s * US_CONTENT_SHARE), where s is the share of the HS10 x country x month import value
   entered duty-free under a special program or the Chapter 99 USMCA exemption (Census rate
   provisions 18 and 19; see census_rp.py).

Columns: rate_<authority> per authority, rate_total (their sum), rate_metal_content (the part of
rate_s232 that legally applies to metal content only; P11 compares), rate_unidentified (duties on
subsets that trade data cannot identify; NOT in rate_total or rate_s232), mfn_rate, usmca_share.

Implementation: product-country pairs are grouped by the set of actions covering them
("signature"); monthly components are computed once per signature by splitting each month at
action dates, then joined back to the pairs.

Run: make rates   (writes data/processed/tariff_rates.parquet)
Watch: make ingest-status SOURCE=rates
"""

import calendar
from datetime import date
from pathlib import Path

import duckdb
import polars as pl

from tpt import config
from tpt.build import tariff_timeline as tt
from tpt.ingest.progress import ProgressFile, progress_path

OUT = config.PROCESSED_DIR / "tariff_rates.parquet"
FAMILIES = config.PROCESSED_DIR / "hs10_families.parquet"
MFN = config.PROCESSED_DIR / "mfn_rates.parquet"
USMCA_SHARE = config.PROCESSED_DIR / "usmca_share.parquet"
IMPORTS = config.INTERIM_DIR / "census_imports"

USMCA_COUNTRIES = {"1220", "2010"}
# Assumed US content of USMCA-qualifying vehicles (the Section 232 autos duty applies to non-US
# content only). Not observed in trade data; P11 checks it against implied rates.
US_CONTENT_SHARE = 0.30
RATE_AUTHORITIES = [a for a in tt.AUTHORITIES if a not in ("DE_MINIMIS", "AD_CVD", "OTHER")]
RATE_COLS = [f"rate_{a.lower()}" for a in RATE_AUTHORITIES]


# --- products and countries per action ---------------------------------------


def _family_fill(direct: set[str], code_years: dict[str, set[int]],
                 families: dict[str, str], members: dict[str, set[str]]) -> set[str]:  # fmt: skip
    """Codes not in the list's vintage year whose whole family in that year is covered.

    The vintage is the year in which most covered codes exist (list files come from one HTSUS
    edition). A code that did not exist then (renamed, split or merged later or earlier) is
    added when every vintage-year member of its family is covered."""
    if not direct:
        return set()
    counts: dict[int, int] = {}
    for c in direct:
        for y in code_years.get(c, ()):
            counts[y] = counts.get(y, 0) + 1
    if not counts:
        return set()
    vintage = max(counts, key=counts.get)
    extra = set()
    for fam in {families[c] for c in direct if c in families}:
        in_vintage = {m for m in members[fam] if vintage in code_years.get(m, ())}
        if in_vintage and in_vintage <= direct:
            extra |= {m for m in members[fam] if m not in direct and m not in in_vintage}
    return extra


def product_sets(actions: list[tt.TariffAction], codes: set[str], base_dir: Path,
                 families: pl.DataFrame | None = None,
                 code_years: dict[str, set[int]] | None = None) -> list[set[str]]:  # fmt: skip
    fam = members = None
    if families is not None and code_years:
        fam = dict(zip(families["hs10"], families["family"], strict=True))
        members = {}
        for c, f in fam.items():
            members.setdefault(f, set()).add(c)
    out = []
    for a in actions:
        direct = tt.resolve_hs10(a.hs_scope, a.hs_exclude, base_dir, codes)
        if fam is not None and "file:" in a.hs_scope:
            excluded = (tt.resolve_hs10(a.hs_exclude, None, base_dir, codes)
                        if a.hs_exclude else set())  # fmt: skip
            direct |= (_family_fill(direct, code_years, fam, members) - excluded) & codes
        out.append(direct)
    return out


def country_member(a: tt.TariffAction, cty: str, groups: dict[str, set[str]]) -> bool:
    if a.cty_code == "ALL":
        return cty not in tt.expand_countries(a.excluded, groups)
    return cty in groups.get(a.cty_code, {a.cty_code})


# --- per-signature monthly components ----------------------------------------


def _months(first: date, last: date) -> list[date]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _supersede_pairs(actions: list[tt.TariffAction]) -> set[tuple[int, int]]:
    """(winner, loser) index pairs, transitive (a chain of supersedes)."""
    idx = {a.action_id: i for i, a in enumerate(actions)}
    direct = {i: {idx[s] for s in tt._split(a.supersedes) if s in idx}
              for i, a in enumerate(actions)}  # fmt: skip
    pairs = set()
    for i in direct:
        stack, seen = list(direct[i]), set()
        while stack:
            j = stack.pop()
            if j not in seen:
                seen.add(j)
                pairs.add((i, j))
                stack += direct[j]
    return pairs


class _Resolver:
    def __init__(self, actions: list[tt.TariffAction]):
        self.actions = actions
        self.beats = _supersede_pairs(actions)
        self.memo: dict[frozenset[int], tuple] = {}

    def applied(self, active: frozenset[int]) -> tuple:
        if active in self.memo:
            return self.memo[active]
        acts = self.actions
        live = {i for i in active if not any((j, i) in self.beats for j in active)}
        names = {}
        for j in live:
            if acts[j].value_basis != "unidentified_subset":
                names[j] = {acts[j].authority, acts[j].action_group}
        kept = [i for i in sorted(live)
                if not any(acts[i].not_with & n for j, n in names.items() if j != i)]  # fmt: skip
        out = tuple(
            (acts[i].authority, acts[i].rate_type, acts[i].rate or 0.0, acts[i].usmca or "",
             acts[i].value_basis or "full")
            for i in kept
        )  # fmt: skip
        self.memo[active] = out
        return out


def signature_components(sig: tuple[int, ...], actions: list[tt.TariffAction],
                         months: list[date], resolver: _Resolver) -> list[tuple]:  # fmt: skip
    """[(month, authority, kind, floor, usmca, basis, value)] with kind 'av' (value = mean rate)
    or 'floor' (value = share of the month under a floor of that level)."""
    starts = {i: actions[i].effective_date for i in sig}
    ends = {i: actions[i].end for i in sig}
    cuts = sorted({d for i in sig for d in (starts[i], ends[i]) if d != date.max})
    first = min(starts.values())
    out = []
    for m in months:
        n = calendar.monthrange(m.year, m.month)[1]
        m_end = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        if m_end <= first:
            continue
        points = [m] + [d for d in cuts if m < d < m_end] + [m_end]
        acc: dict[tuple, float] = {}
        for a, b in zip(points, points[1:], strict=False):
            active = frozenset(i for i in sig if starts[i] <= a < ends[i])
            if not active:
                continue
            w = (b - a).days / n
            for auth, rtype, rate, usmca, basis in resolver.applied(active):
                if rtype == "all_in_floor":
                    key = (auth, "floor", rate, usmca, basis)
                    acc[key] = acc.get(key, 0.0) + w
                else:
                    key = (auth, "av", 0.0, usmca, basis)
                    acc[key] = acc.get(key, 0.0) + w * rate
        out += [(m, *k, v) for k, v in acc.items() if v]
    return out


# --- expansion ---------------------------------------------------------------


def expand(actions: list[tt.TariffAction], keys: pl.DataFrame, *, base_dir: Path,
           groups: dict[str, set[str]], mfn: pl.DataFrame,
           usmca_share: pl.DataFrame | None = None,
           families: pl.DataFrame | None = None,
           progress: ProgressFile | None = None) -> pl.DataFrame:  # fmt: skip
    """keys: hs10, cty_code, month (first of month). Returns keys with rate columns."""
    actions = [a for a in actions if a.authority in RATE_AUTHORITIES]
    keys = keys.select("hs10", "cty_code", "month").unique()
    codes = set(keys["hs10"])
    code_years: dict[str, set[int]] = {}
    for c, y in keys.select("hs10", pl.col("month").dt.year().alias("y")).unique().iter_rows():
        code_years.setdefault(c, set()).add(y)
    psets = product_sets(actions, codes, base_dir, families, code_years)

    # signatures: bitmask of covering actions per (hs10, cty)
    code_mask = dict.fromkeys(codes, 0)
    for i, s in enumerate(psets):
        for c in s:
            code_mask[c] |= 1 << i
    ctys = set(keys["cty_code"])
    cty_mask = {c: sum(1 << i for i, a in enumerate(actions) if country_member(a, c, groups))
                for c in ctys}  # fmt: skip
    pairs = keys.select("hs10", "cty_code").unique()
    sig_of = [code_mask[h] & cty_mask[c] for h, c in pairs.iter_rows()]
    uniq = {m: n for n, m in enumerate(sorted(set(sig_of)))}
    pairs = pairs.with_columns(sig=pl.Series([uniq[m] for m in sig_of], dtype=pl.Int32))

    months = _months(keys["month"].min(), keys["month"].max())
    resolver = _Resolver(actions)
    comp_rows = []
    progress_done = progress_rows = 0
    if progress:
        progress.start(len(uniq), label=f"rate signatures ({pairs.height:,} product-country pairs)")
    for mask, n in uniq.items():
        if mask:
            sig = tuple(i for i in range(len(actions)) if mask >> i & 1)
            comp_rows += [(n, *c) for c in signature_components(sig, actions, months, resolver)]
        if progress and (n % 50 == 49 or n == len(uniq) - 1):
            progress.advance(steps=n + 1 - progress_done, rows=len(comp_rows) - progress_rows)
            progress_done, progress_rows = n + 1, len(comp_rows)
    if progress:
        progress.finish()
    comps = pl.DataFrame(
        comp_rows, orient="row",
        schema={"sig": pl.Int32, "month": pl.Date, "authority": pl.String, "kind": pl.String,
                "floor": pl.Float64, "usmca": pl.String, "basis": pl.String, "value": pl.Float64},
    )  # fmt: skip
    return _apply(keys.join(pairs, on=["hs10", "cty_code"]), comps, mfn, usmca_share)


def _apply(keys: pl.DataFrame, comps: pl.DataFrame, mfn: pl.DataFrame,
           usmca_share: pl.DataFrame | None) -> pl.DataFrame:  # fmt: skip
    k = keys.join(mfn.select("hs10", "mfn_rate"), on="hs10", how="left").with_columns(
        pl.col("mfn_rate").fill_null(0.0)
    )
    if usmca_share is not None and usmca_share.height:
        k = k.join(usmca_share.select("hs10", "cty_code", "month", "usmca_share"),
                   on=["hs10", "cty_code", "month"], how="left")  # fmt: skip
    else:
        k = k.with_columns(usmca_share=pl.lit(None, pl.Float64))
    k = k.with_columns(
        pl.when(pl.col("cty_code").is_in(list(USMCA_COUNTRIES)))
        .then(pl.col("usmca_share").fill_null(0.0))
        .otherwise(None)
        .alias("usmca_share")
    )
    long = k.join(comps, on=["sig", "month"], how="inner")
    s = pl.col("usmca_share").fill_null(0.0)
    factor = (
        pl.when(pl.col("usmca") == "exempt").then(1 - s)
        .when(pl.col("usmca") == "non_us_content").then(1 - s * US_CONTENT_SHARE)
        .otherwise(1.0)
    )  # fmt: skip
    amount = (
        pl.when(pl.col("kind") == "floor")
        .then(pl.col("value") * (pl.col("floor") - pl.col("mfn_rate")).clip(lower_bound=0))
        .otherwise(pl.col("value"))
    )
    long = long.with_columns(r=amount * factor)
    ident = pl.col("basis") != "unidentified_subset"
    aggs = [pl.col("r").filter(ident & (pl.col("authority") == a)).sum().alias(c)
            for a, c in zip(RATE_AUTHORITIES, RATE_COLS, strict=True)]  # fmt: skip
    aggs += [
        pl.col("r").filter(pl.col("basis") == "metal_content").sum().alias("rate_metal_content"),
        pl.col("r").filter(~ident).sum().alias("rate_unidentified"),
    ]
    wide = long.group_by("hs10", "cty_code", "month").agg(aggs)
    out = k.drop("sig").join(wide, on=["hs10", "cty_code", "month"], how="left")
    zero = RATE_COLS + ["rate_metal_content", "rate_unidentified"]
    out = out.with_columns([pl.col(c).fill_null(0.0) for c in zero])
    return out.with_columns(rate_total=pl.sum_horizontal(RATE_COLS)).select(
        "hs10", "cty_code", "month", *RATE_COLS, "rate_total", "rate_metal_content",
        "rate_unidentified", "mfn_rate", "usmca_share",
    )  # fmt: skip


# --- run ---------------------------------------------------------------------


def import_keys() -> pl.DataFrame:
    return duckdb.sql(f"""
        select hs10, cty_code, month, sum(con_val_mo) as con_val, sum(gen_val_mo) as gen_val,
               sum(cal_dut_mo) as cal_dut, sum(dut_val_mo) as dut_val
        from read_parquet('{IMPORTS}/*/data.parquet', hive_partitioning = 1)
        where summary_lvl = 'DET' and cty_code <> '-' and (con_val_mo > 0 or gen_val_mo > 0)
        group by all
    """).pl()  # fmt: skip


def run() -> None:
    from tpt.build import mfn as mfn_mod
    from tpt.ingest import census_rp

    imports = import_keys()
    if not MFN.exists():
        mfn_mod.run()
    if not USMCA_SHARE.exists():
        census_rp.run()
    actions = tt.load_actions()
    progress = ProgressFile(progress_path("rates"), label="tariff rates")
    rates = expand(
        actions, imports, base_dir=tt.ACTIONS_CSV.parent, groups=tt._groups(),
        mfn=pl.read_parquet(MFN), usmca_share=pl.read_parquet(USMCA_SHARE),
        families=pl.read_parquet(FAMILIES), progress=progress,
    )  # fmt: skip
    rates = rates.join(imports.select("hs10", "cty_code", "month", "con_val"),
                       on=["hs10", "cty_code", "month"])  # fmt: skip
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rates.drop("con_val").sort("month", "hs10", "cty_code").write_parquet(OUT)
    print(f"{OUT.name}: {rates.height:,} rows, {rates['month'].min()} to {rates['month'].max()}")
    summary(rates)


def summary(rates: pl.DataFrame) -> pl.DataFrame:
    """Import-weighted (imports for consumption, same month) statutory rate by month."""
    w = pl.col("con_val")
    cols = ["rate_total", *RATE_COLS, "rate_unidentified"]
    s = (
        rates.group_by("month")
        .agg([((pl.col(c) * w).sum() / w.sum()).alias(c) for c in cols]
             + [w.sum().alias("con_val")])  # fmt: skip
        .sort("month")
    )  # fmt: skip
    out = config.PROJECT_ROOT / "reports" / "qa" / "statutory_rate_by_month.csv"
    s.write_csv(out)
    with pl.Config(tbl_rows=200, tbl_cols=20, float_precision=4):
        print(s.select("month", "rate_total", *[c for c in RATE_COLS if s[c].max() > 0],
                       "rate_unidentified"))  # fmt: skip
    return s


if __name__ == "__main__":
    run()

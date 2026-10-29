"""Numbers, tables and figure blocks for the report (P22), read only from data/published/.

The report (report/index.qmd) states no figure of its own: every number in its prose is an
entry of `numbers()` (formatted text) and every table is built here, so a data refresh updates
the report. `build()` writes the one published table derived from reference data (the tariff
timeline summary).

Run: make report  (build, then quarto render)
"""

import json
from datetime import date

import polars as pl

from tpt import config

PUB = config.PUBLISHED_DIR
FIG_DIR = config.FIGURES_DIR
TIMELINE_OUT = PUB / "tariff_timeline_summary.csv"
MINUS = "−"

AUTHORITY_NAMES = {
    "S201": "Section 201 (safeguard)", "S232": "Section 232 (national security)",
    "S301": "Section 301 (unfair trade practices)", "IEEPA_FENTANYL": "IEEPA (fentanyl)",
    "IEEPA_RECIPROCAL": "IEEPA (reciprocal)", "IEEPA_OTHER": "IEEPA (other)",
    "S122": "Section 122 (balance of payments)", "S338": "Section 338",
    "DE_MINIMIS": "End of de minimis",
}  # fmt: skip


# --- formatting --------------------------------------------------------------------


def signed(x: float, d: int = 2) -> str:
    """+0.04 / −0.04 with a true minus sign; a value that rounds to zero has no sign."""
    if round(x, d) == 0:
        return f"{0:.{d}f}"
    return f"{x:+.{d}f}".replace("-", MINUS)


def num(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace("-", MINUS)


def pct(x: float, d: int = 1, sign: bool = False) -> str:
    s = f"{100 * x:+.{d}f}%" if sign else f"{100 * x:.{d}f}%"
    return s.replace("-", MINUS)


def bn(x: float, d: int = 1) -> str:
    return f"${x:,.{d}f}bn".replace("-", MINUS)


def month_name(m: date) -> str:
    return f"{m:%B %Y}"


def day_name(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


# --- published tables ----------------------------------------------------------------


def _csv(name: str) -> pl.DataFrame:
    return pl.read_csv(PUB / name, try_parse_dates=True, infer_schema_length=None)


def timeline_summary() -> pl.DataFrame:
    """One row per tariff action group from data/reference/tariff_actions.csv."""
    t = pl.read_csv(config.REFERENCE_DIR / "tariff_actions.csv", infer_schema=False)
    return (
        t.group_by("action_group", "authority")
        .agg(
            first_effective=pl.col("effective_date").min(),
            last_end=pl.col("end_date").max(),
            components=pl.len(),
            max_rate=pl.col("rate").cast(pl.Float64, strict=False).max(),
            legal_status=pl.col("legal_status").unique().sort().str.join(" / "),
            citation=pl.col("source_citation").first(),
        )
        .sort("first_effective", "action_group")
    )


def build() -> pl.DataFrame:
    s = timeline_summary()
    s.write_csv(TIMELINE_OUT)
    return s


def _row(df: pl.DataFrame, **eq) -> dict:
    hits = df.filter(*[pl.col(k) == v for k, v in eq.items()])
    if hits.height != 1:
        raise KeyError(f"{eq}: {hits.height} rows")
    return hits.row(0, named=True)


# --- numbers -------------------------------------------------------------------------


def numbers() -> dict[str, str]:  # noqa: PLR0915 - one flat list of report numbers
    n: dict[str, str] = {}

    legal = _csv("legal_status.csv")
    ext = {r["key"]: r for r in _csv("external_benchmarks.csv").iter_rows(named=True)}
    n["legal_checked"] = day_name(legal["checked_on"].max())
    for key in ("ruling", "collection_ended", "cit_class", "cape_phase3"):
        n[f"date_{key}"] = day_name(_row(legal, key=key)["date"])
    for key in ("refunds_assessed", "refunds_paid"):
        r = _row(legal, key=key)
        n[key] = bn(r["amount_bn"], 0)
        n[f"{key}_date"] = day_name(r["date"])

    # effective rates
    e = _csv("effective_rates.csv")
    last = e["month"].max()
    n["data_month"] = month_name(last)
    allc = e.filter(pl.col("group") == "All countries").sort("month")
    n["eff_2024"] = pct(allc.filter(pl.col("month").dt.year() == 2024)["effective_rate"].mean())
    pk = allc.row(int(allc["effective_rate"].arg_max()), named=True)
    n["eff_peak"], n["eff_peak_month"] = pct(pk["effective_rate"]), month_name(pk["month"])
    pk = allc.row(int(allc["statutory_rate"].arg_max()), named=True)
    n["stat_peak"], n["stat_peak_month"] = pct(pk["statutory_rate"]), month_name(pk["month"])
    lr = allc.row(-1, named=True)
    n["eff_last"], n["stat_last"] = pct(lr["effective_rate"]), pct(lr["statutory_rate"])
    cn = e.filter(pl.col("group") == "China").sort("month")
    pk = cn.row(int(cn["effective_rate"].arg_max()), named=True)
    n["eff_cn_peak"], n["eff_cn_peak_month"] = pct(pk["effective_rate"]), month_name(pk["month"])
    pk = cn.row(int(cn["statutory_rate"].arg_max()), named=True)
    n["stat_cn_peak"] = pct(pk["statutory_rate"])
    n["eff_cn_last"] = pct(cn["effective_rate"][-1])
    for g, k in (("Canada", "ca"), ("Mexico", "mx")):
        r = e.filter(pl.col("group") == g).sort("month").row(-1, named=True)
        n[f"eff_{k}_last"], n[f"stat_{k}_last"] = pct(r["effective_rate"]), pct(r["statutory_rate"])
    n["pwbm_eff"] = pct(ext["pwbm_effective_2026_08"]["value"])
    n["pwbm_cn_eff"] = pct(ext["pwbm_china_effective_2026_08"]["value"])
    n["yale_stat"] = pct(ext["yale_statutory_2026_07"]["value"])

    # border pass-through
    b = _csv("border_pt.csv")

    def bpt(period: str, spec: str, outcome: str = "uv", group: str = "all") -> dict:
        hits = b.filter(pl.col("period") == period, pl.col("spec") == spec,
                        pl.col("outcome") == outcome, pl.col("group") == group)  # fmt: skip
        if spec == "mxp_locality":
            hits = hits.filter(pl.col("term") == "dln_1p_tau_stat")
        if hits.height != 1:
            raise KeyError((period, spec, outcome, group, hits.height))
        return hits.row(0, named=True)

    for p, k in (("2018_19", "18"), ("2025_26", "25")):
        for spec, s in (("main", ""), ("main_trim3", "_t3")):
            r = bpt(p, spec)
            n[f"b{k}{s}"], n[f"b{k}{s}_se"] = signed(r["coef"]), num(r["se"])
        n[f"dut{k}"] = num(bpt(p, "main", "uv_dut")["coef"])
        n[f"qty{k}"] = signed(bpt(p, "main", "qty")["coef"])
        n[f"iv{k}"] = signed(bpt(p, "implied_iv")["coef"])
        n[f"dut_iv{k}"] = num(bpt(p, "implied_iv", "uv_dut")["coef"])
        n[f"qty_iv{k}"] = signed(bpt(p, "implied_iv", "qty")["coef"])
        r = bpt(p, "mxp_locality", "mxp")
        n[f"mxp{k}"], n[f"mxp{k}_se"] = signed(r["coef"]), num(r["se"])
    n["b25_pre"] = signed(bpt("2025_26", "pre_ruling")["coef"])
    lo = 1 + min(bpt("2025_26", "main")["coef"], bpt("2025_26", "main_trim3")["coef"])
    hi = 1 + max(bpt("2025_26", "main")["coef"], bpt("2025_26", "main_trim3")["coef"])
    # cents of each dollar of duty borne by US buyers: 100 x (1 + beta), capped at 100
    n["buyer_lo"], n["buyer_hi"] = f"{100 * min(lo, 1.0):.0f}", f"{100 * min(hi, 1.0):.0f}"
    for g, k in (("s232", "s232"), ("ieepa", "ieepa")):
        n[f"{k}25"] = signed(bpt("2025_26", "authority", group=g)["coef"])
        n[f"{k}25_t3"] = signed(bpt("2025_26", "authority_trim3", group=g)["coef"])
    n["s232_18"] = signed(bpt("2018_19", "authority", group="s232")["coef"])
    n["cn25_t3"] = signed(bpt("2025_26", "china_trim3", group="china")["coef"])
    rep = _csv("border_pt_replication.csv")
    for spec in ("arw", "fgkk"):
        r = _row(rep, spec=spec, outcome="uv")
        n[f"{spec}_pub"], n[f"{spec}_ours"] = signed(r["published_coef"], 3), signed(r["coef"])
    ev = _csv("border_pt_event_2025_26.csv").filter(pl.col("sample") == "pre_ruling")
    n["ev_dut0"] = pct(_row(ev, outcome="uv_dut", k=0)["coef"], 0)
    # event study reference is month -1 (the stockpiling peak): quantities in months -6..-2 sit
    # below it; month 0 shows the drop on impact
    q = ev.filter(pl.col("outcome") == "qty")
    n["ev_qty_front"] = pct(-q.filter(pl.col("k").is_between(-6, -2))["coef"].mean(), 0)
    n["ev_qty0"] = pct(-_row(q, k=0)["coef"], 0)  # size of the drop

    # robustness
    rb = _csv("robustness.csv").filter(pl.col("period") == "2025_26", pl.col("outcome") == "uv")
    unw = rb.filter(pl.col("variant") != "weighted")
    n["rb_n"] = str(unw.height)
    n["rb_lo"], n["rb_hi"] = signed(unw["coef"].min(), 3), signed(unw["coef"].max(), 3)
    n["rb_ci_lo"] = signed(unw["ci_low"].min())
    n["rb_weighted"] = signed(_row(rb, variant="weighted", cleaning="w1")["coef"])
    n["rb_fits"] = str(_csv("robustness.csv").height)

    # retail
    rd = _csv("retail_did.csv")
    for spec, k in (("main", "main"), ("main_eff", "eff"), ("pre_ruling", "pre"),
                    ("no_trend", "notrend"), ("diff12", "d12")):  # fmt: skip
        r = _row(rd, period="2025_26", spec=spec)
        n[f"th_{k}"], n[f"th_{k}_se"] = signed(r["coef"]), num(r["se"])
        if r["retail_vs_border"] is not None:
            n[f"th_{k}_ratio"] = num(r["retail_vs_border"], 2)
    r = _row(rd, period="2025_26", spec="binary")
    n["th_bin"], n["th_bin_se"] = pct(r["coef"], 1, sign=True), pct(r["se"], 1)
    n["th_items"], n["th_classes"] = (
        str(_row(rd, period="2025_26", spec="main")["n_items"]),
        str(_row(rd, period="2025_26", spec="main")["n_clusters"]),
    )
    r = _row(rd, period="2018_19", spec="main")
    n["th18"], n["th18_se"] = signed(r["coef"]), num(r["se"])
    rev = _csv("retail_event.csv").filter(
        pl.col("period") == "2025_26", pl.col("trend") == "pre", pl.col("design") == "binary"
    )
    for k in (6, 12):
        n[f"rev_{k}"] = pct(_row(rev, k=k)["coef"], 1, sign=True)
    hl = _csv("retail_high_low.csv").filter(pl.col("period") == "2025_26")
    hl_last = hl.filter(pl.col("month") == hl["month"].max())
    n["hl_month"] = month_name(hl["month"].max())
    n["hl_high"] = num(_row(hl_last, group="high")["index_dt"], 1)
    n["hl_low"] = num(_row(hl_last, group="low")["index_dt"], 1)
    pre = hl.filter(pl.col("month").dt.year() == 2023, pl.col("month").dt.month() == 1)
    gap = _row(pre, group="high")["index"] - _row(pre, group="low")["index"]
    n["hl_pre_gap"] = num(gap, 1)
    top = _csv("cpi_exposure_top_bottom.csv").filter(pl.col("rank_group") == "top")
    n["exp_top_name"] = top["item_name"][0].lower()
    n["exp_top"] = pct(top["exposure"][0])
    n["exp_top_eff"] = pct(top["exposure_eff"][0])

    # diversion
    sh = _csv("diversion_shares.csv")
    first, lastm = sh["month"].min(), sh["month"].max()
    n["div_first"], n["div_last"] = month_name(first), month_name(lastm)
    for panel in ("s301", "other"):
        for g, k in (("China", "cn"), ("Taiwan", "tw"), ("Vietnam", "vn"), ("Mexico", "mx"),
                     ("Other Southeast Asia", "sea")):  # fmt: skip
            for m, s in ((first, "0"), (date(2024, 12, 1), "24"), (lastm, "1")):
                v = _row(sh, panel=panel, group=g, month=m)["share"]
                n[f"sh_{panel}_{k}{s}"] = pct(v, 1)
    tot = sh.filter(pl.col("month") == lastm).group_by("panel").agg(pl.col("value_r").sum())
    n["s301_value"] = f"${_row(tot, panel='s301')['value_r'] / 1e12:.2f}tn"
    dv = _csv("diversion.csv")
    for p, k in (("2018_19", "18"), ("2025_26", "25")):
        for spec, term, s in (("ppml", "lntau", "ppml"), ("ppml_cty_quarter", "lntau", "ppml_cq"),
                              ("ld_main", "dtau", "ld"), ("ld_weighted", "dtau", "ldw"),
                              ("ld_base_ge_p90", "dtau", "ld90"),
                              ("ld_china_split", "dtau_china", "ldcn"),
                              ("ld_china_split", "dtau_other", "ldot")):  # fmt: skip
            r = _row(dv, period=p, spec=spec, term=term)
            n[f"dv_{s}{k}"], n[f"dv_{s}{k}_se"] = signed(r["coef"]), num(r["se"])
    fl = _csv("transshipment_flags.csv")
    for ep, k in (("2017_to_2024", "a"), ("2024_to_latest", "b")):
        f = fl.filter(pl.col("episode") == ep)
        n[f"fl_{k}_n"], n[f"fl_{k}_bn"] = str(f.height), bn(f["gain"].sum() / 1e9)
        n[f"fl_{k}_conv"] = str(int(f["uv_converged"].sum()))

    # front-running and de minimis
    fr = _csv("front_running_summary.csv")
    big = fr.filter(pl.col("action").is_in(["cn_fentanyl", "metals", "reciprocal"]))
    n["fr_months_lo"], n["fr_months_hi"] = (str(big["positive_months"].min()),
                                           str(big["positive_months"].max()))  # fmt: skip
    n["fr_excess"] = bn(big["excess_positive_bn"].sum())
    ph = _row(fr, action="pharma")
    n["fr_pharma_peak"] = pct(ph["peak_pct"], 0, sign=True)
    lv = _csv("low_value_imports.csv").sort("month")
    pre = lv.filter(pl.col("month").is_between(date(2025, 1, 1), date(2025, 4, 1)))
    n["lv_cn_pre"] = bn(pre["china_hk_bn"].mean(), 2)
    n["lv_cn_last"], n["lv_rest_last"] = bn(lv["china_hk_bn"][-1], 2), bn(lv["rest_bn"][-1], 1)
    n["lv_rest_pre"] = bn(pre["rest_bn"].mean(), 1)
    n["dm_2023"] = bn(ext["deminimis_2023_bn"]["value"], 1)
    n["dm_month"] = bn(ext["deminimis_2023_bn"]["value"] / 12, 1)
    n["dm_threshold"] = f"${ext['deminimis_threshold_usd']['value']:,.0f}"

    # thresholds and counts stated in the text
    from tpt.models import diversion as dvm

    n["fl_cn_drop"] = f"{-100 * dvm.CHINA_DROP:.0f}"
    n["fl_prior"], n["fl_post"] = pct(dvm.PRIOR_MAX, 0), pct(dvm.POST_MIN, 0)
    n["fl_gain"] = f"${dvm.MIN_GAIN / 1e6:.0f}m"
    hand = pl.read_csv(config.REFERENCE_DIR / "cpi_hs_hand_map.csv", infer_schema=False)
    n["hand_items"] = str(hand["item_code"].n_unique())
    n["rb_rules"] = str(_csv("robustness.csv")["cleaning"].n_unique())

    tl = pl.read_csv(TIMELINE_OUT) if TIMELINE_OUT.exists() else timeline_summary()
    n["tl_groups"], n["tl_rows"] = str(tl.height), str(int(tl["components"].sum()))
    return n


# --- tables and figures --------------------------------------------------------------


def md_table(df: pl.DataFrame, headers: list[str], align: str | None = None) -> str:
    align = align or "l" * len(headers)
    sep = ["---:" if a == "r" else ":---" for a in align]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.iter_rows()]
    return "\n".join(lines)


def table_timeline() -> str:
    tl = pl.read_csv(TIMELINE_OUT) if TIMELINE_OUT.exists() else timeline_summary()
    t = tl.select(
        pl.col("authority").replace_strict(AUTHORITY_NAMES, default=pl.col("authority")),
        "action_group", "first_effective",
        pl.col("last_end").fill_null("in force"),
        pl.when(pl.col("max_rate") > 0).then((pl.col("max_rate") * 100).round(1).cast(pl.String)
                                              + "%").otherwise(pl.lit("—")),
        pl.col("legal_status").str.replace_all("_", " "),
        "citation",
    )  # fmt: skip
    return md_table(t, ["Authority", "Action", "From", "To", "Highest rate", "Status",
                        "Citation"])  # fmt: skip


def table_border() -> str:
    b = _csv("border_pt.csv").filter(pl.col("outcome") == "uv")
    rows = [("All imports, main", "main", "all"), ("All imports, outliers trimmed", "main_trim3",
            "all"), ("Two-way clustered SEs", "twoway", "all"), ("To Jan 2026 (pre-ruling)",
            "pre_ruling", "all"), ("Collected duty, instrumented", "implied_iv", "all"),
            ("China", "china", "china"), ("Other countries", "china", "other"),
            ("Section 232", "authority", "s232"), ("IEEPA", "authority", "ieepa"),
            ("Section 301", "authority", "s301")]  # fmt: skip
    out = []
    for label, spec, g in rows:
        cells = [label]
        for p in ("2018_19", "2025_26"):
            h = b.filter(pl.col("period") == p, pl.col("spec") == spec, pl.col("group") == g)
            cells.append(f"{signed(h['coef'][0])} ({num(h['se'][0])})" if h.height else "—")
        out.append(cells)
    return md_table(pl.DataFrame(out, schema=["s", "a", "b"], orient="row"),
                    ["Specification", "2018–19", "2025–26"], "lrr")  # fmt: skip


def table_retail() -> str:
    rd = _csv("retail_did.csv").filter(pl.col("period") == "2025_26")
    labels = {"main": "Main: own pre-trend, statutory exposure",
              "main_eff": "Main, collected-duty exposure", "pre_ruling": "To Jan 2026",
              "trend_long": "Trend fitted from 2015", "diff12": "12-month differences",
              "sa": "BLS seasonally adjusted series", "all_items": "All items",
              "hand": "Hand-mapped items", "no_trend": "No item trends (biased)"}  # fmt: skip
    out = [[lbl, f"{signed(_row(rd, spec=s)['coef'])} ({num(_row(rd, spec=s)['se'])})"]
           for s, lbl in labels.items()]  # fmt: skip
    return md_table(pl.DataFrame(out, schema=["s", "a"], orient="row"),
                    ["Specification", "θ (SE)"], "lr")  # fmt: skip


def table_exposure(n_rows: int = 10) -> str:
    t = _csv("cpi_exposure_top_bottom.csv").filter(pl.col("rank_group") == "top").head(n_rows)
    t = t.select("item_name", pl.col("goods_import_share").map_elements(pct, pl.String),
                 pl.col("dtau").map_elements(lambda v: pct(v), pl.String),
                 pl.col("exposure").map_elements(lambda v: pct(v, 2), pl.String),
                 pl.col("exposure_eff").map_elements(lambda v: pct(v, 2), pl.String))  # fmt: skip
    return md_table(t, ["CPI item", "Import share", "Tariff change", "Exposure",
                        "Exposure (collected)"], "lrrrr")  # fmt: skip


def table_diversion() -> str:
    dv = _csv("diversion.csv")
    rows = [("Long difference, HS6 FE", "ld_main", "dtau"),
            ("Weighted by import value", "ld_weighted", "dtau"),
            ("Largest tenth of flows", "ld_base_ge_p90", "dtau"),
            ("China's own tariff", "ld_china_split", "dtau_china"),
            ("Other suppliers' tariffs", "ld_china_split", "dtau_other"),
            ("Gravity (PPML)", "ppml", "lntau"),
            ("Gravity, + country × quarter", "ppml_cty_quarter", "lntau")]  # fmt: skip
    out = []
    for label, spec, term in rows:
        cells = [label]
        for p in ("2018_19", "2025_26"):
            r = _row(dv, period=p, spec=spec, term=term)
            cells.append(f"{signed(r['coef'])} ({num(r['se'])})")
        out.append(cells)
    return md_table(pl.DataFrame(out, schema=["s", "a", "b"], orient="row"),
                    ["Specification", "2018–19", "2025–26"], "lrr")  # fmt: skip


def table_flags(n_rows: int = 8) -> str:
    fl = _csv("transshipment_flags.csv").sort("gain", descending=True).head(n_rows)
    t = fl.select(
        pl.col("episode").replace({"2017_to_2024": "2017 → 2024",
                                   "2024_to_latest": "2024 → latest"}),
        pl.col("cty_name").str.to_titlecase(),
        pl.col("hs6").cast(pl.String).str.zfill(6),
        pl.col("desc").str.to_lowercase().str.slice(0, 48),
        pl.col("gain").map_elements(lambda v: bn(v / 1e9), pl.String),
        pl.format("{} → {}", pl.col("china_share_b").map_elements(lambda v: pct(v, 0), pl.String),
                  pl.col("china_share_p").map_elements(lambda v: pct(v, 0), pl.String)),
        pl.when(pl.col("uv_converged")).then(pl.lit("yes")).otherwise(pl.lit("no")),
    )  # fmt: skip
    return md_table(t, ["Episode", "Supplier", "HS6", "Product", "Gain a year",
                        "China's share", "Unit values converge"], "lllllrl")  # fmt: skip


def table_front_running() -> str:
    fr = _csv("front_running_summary.csv")
    t = fr.select(
        "label", pl.col("imports_2024_bn").map_elements(lambda v: bn(v, 0), pl.String),
        pl.format("{} (month {})", pl.col("peak_pct").map_elements(lambda v: pct(v, 0, True),
                  pl.String), pl.col("peak_k")),
        pl.col("positive_months"),
        pl.col("excess_positive_bn").map_elements(bn, pl.String),
        pl.col("shortfall_post_bn").map_elements(bn, pl.String),
    )  # fmt: skip
    return md_table(t, ["Action", "2024 imports", "Peak excess", "Months above trend before",
                        "Excess in those months", "Months 0 to +5 vs trend"], "lrrrrr")  # fmt: skip


def table_legal() -> str:
    lg = _csv("legal_status.csv").sort("date")
    t = lg.select(pl.col("date").cast(pl.String), "event",
                  pl.format("[{}]({})", pl.col("source"), pl.col("url")))  # fmt: skip
    return md_table(t, ["Date", "Event", "Source"])


def fig(name: str, caption: str) -> str:
    """Markdown for a figure in light and dark versions, with its alt text and data table."""
    m = json.loads((FIG_DIR / "alt_text.json").read_text())[name]
    alt = m["alt"].replace('"', "'")
    data = m["data"].removeprefix("data/published/")
    out = []
    for mode, cls in (("light", ".light-content"), ("dark", ".dark-content")):
        out.append(f'![{caption}](figures/{m["files"][mode]}){{{cls} fig-alt="{alt}"}}')
    out.append(f"\n<small>Data: [`{data}`](https://github.com/{config.GITHUB_REPO}/blob/main/"
               f"data/published/{data})</small>")  # fmt: skip
    return "\n\n".join(out)


if __name__ == "__main__":
    s = build()
    print(f"wrote {TIMELINE_OUT.relative_to(config.PROJECT_ROOT)} ({s.height} action groups)")
    print(f"{len(numbers())} report numbers")

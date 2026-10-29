"""Figure builders (P13, P21). Every figure is drawn from data/published/ in both modes.

Run: make figures   (writes report/figures/<name>.svg/.png and <name>_dark.svg/.png)
"""

from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl
from matplotlib.ticker import FuncFormatter, MultipleLocator

from tpt import config
from tpt.build import effective_rates as er
from tpt.viz import theme

EFFECTIVE = config.PUBLISHED_DIR / "effective_rates.csv"
FRONT_RUNNING = config.PUBLISHED_DIR / "front_running.csv"
LOW_VALUE = config.PUBLISHED_DIR / "low_value_imports.csv"
BORDER_EVENT_2018 = config.PUBLISHED_DIR / "border_pt_event_2018_19.csv"
BORDER_PT = config.PUBLISHED_DIR / "border_pt.csv"
ROBUSTNESS = config.PUBLISHED_DIR / "robustness.csv"
RETAIL_HIGH_LOW = config.PUBLISHED_DIR / "retail_high_low.csv"
DIVERSION_SHARES = config.PUBLISHED_DIR / "diversion_shares.csv"
BORDER_EVENT_2025 = config.PUBLISHED_DIR / "border_pt_event_2025_26.csv"
QA_DIR = config.PROJECT_ROOT / "reports" / "qa"
# China last, with its own scale labelled on the right; shared-scale ticks only in column 1
PANELS = ["All countries", "Canada", "Mexico", "EU", "Japan", "Vietnam", "India", "China"]
OWN_SCALE = {"China": (1.1, 0.25)}  # panel -> (y max, tick step); the rest share SHARED
SHARED = (0.35, 0.10)


def _pct(x: float, _pos: int) -> str:
    return f"{x * 100:.0f}%"


def chart2_effective_rates(mode: str = "light", data: Path = EFFECTIVE,
                           out_dir: Path | None = None) -> list[Path]:  # fmt: skip
    """Chart 2: effective (duties collected) vs statutory tariff rate by partner, monthly."""
    df = pl.read_csv(data, try_parse_dates=True)
    last = df["month"].max()
    with theme.style(mode) as t:
        eff_c, stat_c = t["series"][0], t["series"][1]
        fig, axes = plt.subplots(2, 4, figsize=(theme.WIDTH_IN, 6.2), sharex=True)
        fig.subplots_adjust(left=0.05, right=0.95, top=0.80, bottom=0.12, hspace=0.38,
                            wspace=0.26)  # fmt: skip
        for i, (ax, name) in enumerate(zip(axes.flat, PANELS, strict=True)):
            p = df.filter(pl.col("group") == name).sort("month")
            x = p["month"].to_list()
            ax.plot(x, p["statutory_rate"], color=stat_c, zorder=3)
            ax.plot(x, p["effective_rate"], color=eff_c, zorder=4)
            theme.end_dot(ax, x[-1], p["statutory_rate"][-1], stat_c, t)
            theme.end_dot(ax, x[-1], p["effective_rate"][-1], eff_c, t)
            ymax, step = OWN_SCALE.get(name, SHARED)
            ax.set_ylim(0, ymax)
            ax.yaxis.set_major_locator(MultipleLocator(step))
            ax.yaxis.set_major_formatter(FuncFormatter(_pct))
            title = f"{name} (own scale, right)" if name in OWN_SCALE else name
            ax.set_title(title, color=t["text"])
            if name in OWN_SCALE:
                ax.yaxis.tick_right()
            elif i % 4:
                ax.tick_params(axis="y", labelleft=False)
            ax.xaxis.set_major_locator(mdates.YearLocator(2))
            ax.xaxis.set_minor_locator(mdates.YearLocator(1))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
            ax.tick_params(axis="x", which="minor", length=2, color=t["axis"])
            ax.set_xlim(x[0], last)
        # direct labels on the first panel only (legend carries identity everywhere)
        ax0 = axes.flat[0]
        end = df.filter((pl.col("group") == "All countries") & (pl.col("month") == last))
        for col, label, dy in (
            ("statutory_rate", "Statutory", 4),
            ("effective_rate", "Effective", -4),
        ):
            ax0.annotate(label, (last, end[col][0]), xytext=(7, dy), textcoords="offset points",
                         ha="left", va="center", fontsize=8, color=t["text2"],
                         annotation_clip=False)  # fmt: skip
        handles = [plt.Line2D([], [], color=eff_c, lw=theme.LINE_WIDTH),
                   plt.Line2D([], [], color=stat_c, lw=theme.LINE_WIDTH)]  # fmt: skip
        fig.legend(handles, ["Effective rate (duties assessed ÷ imports)",
                             "Statutory rate (tariff orders, incl. MFN)"],
                   loc="upper left", bbox_to_anchor=(0.006, 0.875), ncol=2, fontsize=8.5,
                   handlelength=1.6, columnspacing=1.6, labelcolor=t["text2"])  # fmt: skip
        theme.header(
            fig, "Tariff rates on U.S. imports by trading partner, 2017–2026",
            "Monthly. The statutory rate weights the rates in force by same-month imports; "
            "the effective rate is what was assessed at entry.\nAll panels share the left "
            "scale except China, which is on its own scale (right).", t,
        )  # fmt: skip
        theme.footer(
            fig, theme.SOURCE_CENSUS, t,
            note=f"EU: 27 current members throughout. Latest month: {last:%B %Y}. Effective "
            "rates are as assessed at entry, before the 2026 IEEPA refunds.",
        )  # fmt: skip
        return theme.save(fig, "chart2_effective_rates", mode, out_dir)


def _band(ax: plt.Axes, x, lo, hi, t: dict) -> None:
    ax.fill_between(x, lo, hi, color=t["text2"], alpha=0.10, linewidth=0, zorder=1)


def chart5_front_running(mode: str = "light", data: Path = FRONT_RUNNING,
                         out_dir: Path | None = None) -> list[Path]:  # fmt: skip
    """Chart 5: imports of affected products vs their own seasonal pattern, by event month."""
    df = pl.read_csv(data, try_parse_dates=True)
    actions = df.select("action", "label").unique(maintain_order=True).rows()
    lo = min(df["excess_pct"].min(), df["band_low"].min())
    hi = max(df["excess_pct"].max(), df["band"].max())
    with theme.style(mode) as t:
        c = t["series"][0]
        fig, axes = plt.subplots(2, 3, figsize=(theme.WIDTH_IN, 6.4), sharex=True, sharey=True)
        fig.subplots_adjust(left=0.07, right=0.985, top=0.79, bottom=0.15, hspace=0.42,
                            wspace=0.10)  # fmt: skip
        for i, (ax, (aid, label)) in enumerate(zip(axes.flat, actions, strict=True)):
            p = df.filter(pl.col("action") == aid).sort("k")
            k = p["k"].to_list()
            _band(ax, k, p["band_low"], p["band"], t)
            ax.axhline(0, color=t["axis"], linewidth=0.8, zorder=2)
            ax.axvline(0, color=t["muted"], linewidth=0.8, zorder=2)
            ax.plot(k, p["excess_pct"], color=c, zorder=4)
            ax.plot(k, p["excess_pct"], "o", markersize=3.5, color=c,
                    markeredgecolor=t["surface"], markeredgewidth=1, zorder=5)  # fmt: skip
            pre = p.filter(pl.col("k") < 0).sort("excess_pct", descending=True).row(0, named=True)
            ax.annotate(f"{pre['excess_pct']:+.0%}", (pre["k"], pre["excess_pct"]),
                        xytext=(0, 7), textcoords="offset points", ha="center", fontsize=8,
                        color=t["text2"])  # fmt: skip
            ax.set_title(label, color=t["text"], fontsize=9.5)
            ax.set_ylim(lo - 0.05, hi + 0.12)
            ax.yaxis.set_major_locator(MultipleLocator(0.25))
            ax.yaxis.set_major_formatter(
                FuncFormatter(lambda x, _: f"{x * 100:+.0f}%" if x else "0")
            )
            ax.xaxis.set_major_locator(MultipleLocator(3))
            if i == 0:
                ax.annotate("In force", (0, hi + 0.08), xytext=(4, 0), textcoords="offset points",
                            fontsize=8, color=t["muted"], va="center")  # fmt: skip
        for ax in axes[1]:
            ax.set_xlabel("Months from the month the duty took effect", color=t["muted"],
                          fontsize=8)  # fmt: skip
        theme.header(
            fig, "Imports of affected products around the 2025 tariff actions",
            "Value relative to the same products' own seasonal pattern (last year's same month × "
            "their Oct 2023–Sep 2024 growth). Grey band: ±2 s.d.\nof that growth before the "
            "2024 election. Country-specific rates (Aug 2025) are also measured against products "
            "whose rate stayed at 10%.", t,
        )  # fmt: skip
        theme.footer(
            fig, theme.SOURCE_CENSUS, t,
            note="Products: HS6 × country pairs whose statutory rate for the action rose; "
            "pharmaceuticals: HS chapter 30, month 0 = inquiry opened (duty from Sep 2026). "
            "China after month +2 also reflects the April 2025 increases.",
        )  # fmt: skip
        return theme.save(fig, "chart5_front_running", mode, out_dir)


def chart6_low_value(mode: str = "light", data: Path = LOW_VALUE,
                     out_dir: Path | None = None) -> list[Path]:  # fmt: skip
    """Chart 6: Census low-value import estimates (HTS 9999.95) around the end of de minimis."""
    df = pl.read_csv(data, try_parse_dates=True).sort("month")
    with theme.style(mode) as t:
        c1, c2 = t["series"][0], t["series"][1]
        fig, ax = plt.subplots(figsize=(theme.WIDTH_IN, 5.4))
        fig.subplots_adjust(left=0.07, right=0.79, top=0.74, bottom=0.2)
        x = df["month"].to_list()
        for col, color in (("rest_bn", c2), ("china_hk_bn", c1)):
            ax.plot(x, df[col], color=color, zorder=4)
            theme.end_dot(ax, x[-1], df[col][-1], color, t)
        labels = (("rest_bn", "All other countries"), ("china_hk_bn", "China and Hong Kong"))
        for col, label in labels:
            ax.annotate(f"{label}  ${df[col][-1]:.1f}bn", (x[-1], df[col][-1]), xytext=(8, 0),
                        textcoords="offset points", va="center", fontsize=8.5,
                        color=t["text2"], annotation_clip=False)  # fmt: skip
        top = df["rest_bn"].max() * 1.25
        marks = ((date(2025, 5, 2), "De minimis ends:\nChina, Hong Kong (May 2)", "right", -4),
                 (date(2025, 8, 29), "All countries\n(Aug 29)", "left", 4))  # fmt: skip
        for when, text, ha, dx in marks:
            ax.axvline(when, color=t["muted"], linewidth=0.8, zorder=2)
            ax.annotate(text, (when, top), xytext=(dx, 0), textcoords="offset points",
                        ha=ha, va="top", fontsize=8, color=t["muted"])  # fmt: skip
        ax.set_ylim(0, top)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:.1f}bn" if v else "0"))
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.set_xlim(x[0], x[-1])
        handles = [plt.Line2D([], [], color=c1, lw=theme.LINE_WIDTH),
                   plt.Line2D([], [], color=c2, lw=theme.LINE_WIDTH)]  # fmt: skip
        fig.legend(handles, ["China and Hong Kong", "All other countries"], loc="upper left",
                   bbox_to_anchor=(0.006, 0.815), ncol=2, fontsize=8.5,
                   labelcolor=t["text2"])  # fmt: skip
        theme.header(
            fig, "Recorded low-value imports before and after the end of de minimis",
            "Monthly Census estimates of import shipments under $2,000 (HTS 9999.95), imports "
            "for consumption.\nMeasurement change: de minimis shipments (under $800) were not "
            "recorded before; part of the rise is newly recorded trade, not new imports.", t,
        )  # fmt: skip
        theme.footer(
            fig, "Source: U.S. Census Bureau, international trade (HTS 9999.95.0000 low-value "
            "estimates; Guide to Foreign Trade Statistics, sec. 2); EO 14256, EO 14324.", t,
            note="For scale: de minimis imports were $54.5bn in 2023, about $4.5bn a month "
            "(Fajgelbaum and Khandelwal, 2025), none of it in Census data.",
        )  # fmt: skip
        return theme.save(fig, "chart6_low_value", mode, out_dir)


EVENT_PANELS = [("uv", "Pre-duty unit value"), ("uv_dut", "Duty-inclusive unit value"),
                ("qty", "Quantity"), ("val", "Import value")]  # fmt: skip


def _qa_event(mode: str, data: Path, samples: tuple, title: str, name: str,
              out_dir: Path | None) -> list[Path]:  # fmt: skip
    """Event study of targeted vs untargeted varieties, two samples (first one with its CI)."""
    df = pl.read_csv(data)
    with theme.style(mode) as t:
        colors = dict(zip([s for s, _ in samples], t["series"][:2], strict=True))
        fig, axes = plt.subplots(1, 4, figsize=(theme.WIDTH_IN, 4.4), sharex=True)
        fig.subplots_adjust(left=0.06, right=0.985, top=0.66, bottom=0.2, wspace=0.32)
        for ax, (o, panel) in zip(axes, EVENT_PANELS, strict=True):
            ax.axhline(0, color=t["axis"], linewidth=0.8, zorder=2)
            ax.axvline(-0.5, color=t["muted"], linewidth=0.8, zorder=2)
            for s, _ in reversed(samples):
                p = df.filter(pl.col("sample") == s, pl.col("outcome") == o).sort("k")
                k = p["k"].to_list()
                if s == samples[0][0]:
                    _band(ax, k, p["ci_low"], p["ci_high"], t)
                ax.plot(k, p["coef"], color=colors[s], zorder=4)
                ax.plot(k, p["coef"], "o", markersize=3.5, color=colors[s],
                        markeredgecolor=t["surface"], markeredgewidth=1, zorder=5)  # fmt: skip
            ax.set_title(panel, color=t["text"], fontsize=9.5)
            ax.yaxis.set_major_formatter(
                FuncFormatter(lambda x, _: f"{x * 100:+.0f}%" if x else "0")
            )
            ax.xaxis.set_major_locator(MultipleLocator(3))
            ax.set_xlabel("Months from first tariff increase", color=t["muted"], fontsize=8)
        handles = [plt.Line2D([], [], color=colors[s], lw=theme.LINE_WIDTH) for s, _ in samples]
        fig.legend(handles, [label for _, label in samples], loc="upper left",
                   bbox_to_anchor=(0.006, 0.79), ncol=2, fontsize=8.5,
                   labelcolor=t["text2"])  # fmt: skip
        theme.header(
            fig, title,
            "Log difference from untargeted varieties of the same HS6 product in the same month, "
            "relative to month −1 (Fajgelbaum et al. 2020, eq. 1).\nVariety, HS6 × month and "
            "country × month fixed effects; SEs clustered by HS8. Month 6 includes later "
            "months.", t,
        )  # fmt: skip
        theme.footer(fig, theme.SOURCE_CENSUS, t)
        return theme.save(fig, name, mode, out_dir or QA_DIR)


def qa_border_event_2018(mode: str = "light", data: Path = BORDER_EVENT_2018,
                         out_dir: Path | None = None) -> list[Path]:  # fmt: skip
    """QA (P15): 2018-19 event study, FGKK sample and through 2019."""
    samples = (("fgkk", "To Apr 2019 (Fajgelbaum et al. sample), 95% CI"),
               ("full", "Through Dec 2019 (adds the Sep 2019 actions)"))  # fmt: skip
    title = "2018–19 tariffs: targeted vs untargeted imports (replication check)"
    return _qa_event(mode, data, samples, title, "border_pt_event_2018_19", out_dir)


def qa_border_event_2025(mode: str = "light", data: Path = BORDER_EVENT_2025,
                         out_dir: Path | None = None) -> list[Path]:  # fmt: skip
    """QA (P16): 2025-26 event study, to Jan 2026 and through the latest month."""
    samples = (("pre_ruling", "To Jan 2026 (before IEEPA duties ended), 95% CI"),
               ("full", "Through the latest month"))  # fmt: skip
    title = "2025–26 tariffs: imports hit by a new tariff vs those not hit"
    return _qa_event(mode, data, samples, title, "border_pt_event_2025_26", out_dir)


# label -> (spec, group) in border_pt.csv; ARW-trim twin via trim_spec
HERO_ROWS = {
    "All imports": ("main", "all"),
    "China": ("china", "china"),
    "Other countries": ("china", "other"),
    "Section 232 duties": ("authority", "s232"),
    "IEEPA duties": ("authority", "ieepa"),
    "Section 301 duties": ("authority", "s301"),
    "Differentiated goods": ("rauch", "differentiated"),
    "Homogeneous goods": ("rauch", "homogeneous"),
}  # fmt: skip
HERO_PERIODS = (("2018_19", "2018–19"), ("2025_26", "2025–26"))


def trim_spec(spec: str) -> str:
    return f"{spec}_trim3"


def hero_border_pt(mode: str = "light", data: Path = BORDER_PT,
                   out_dir: Path | None = None) -> list[Path]:  # fmt: skip
    """Hero (P16 draft, final in P21): pass-through of tariffs to pre-duty import prices."""
    df = pl.read_csv(data).filter(pl.col("outcome") == "uv")
    est = {(r["period"], r["spec"], r["group"]): r for r in df.iter_rows(named=True)}
    labels = list(HERO_ROWS)
    with theme.style(mode) as t:
        colors = dict(zip([p for p, _ in HERO_PERIODS], t["series"][:2], strict=True))
        fig, ax = plt.subplots(figsize=(theme.WIDTH_IN, 6.4))
        fig.subplots_adjust(left=0.2, right=0.97, top=0.74, bottom=0.14)
        for x, label in ((-1.0, "Foreign exporters pay"), (0.0, "US buyers pay")):
            ax.axvline(x, color=t["axis"], linewidth=1, zorder=1)
            ax.text(x, -0.75, label, ha="center", va="bottom", fontsize=8.5,
                    color=t["text2"])  # fmt: skip
        for i, label in enumerate(labels):
            spec, group = HERO_ROWS[label]
            for j, (p, _) in enumerate(HERO_PERIODS):
                for dy, sp, filled in ((-0.18, spec, True), (-0.06, trim_spec(spec), False)):
                    r = est.get((p, sp, group))
                    if r is None:
                        continue
                    y = i + dy + 0.24 * j
                    ax.plot([r["ci_low"], r["ci_high"]], [y, y], color=colors[p],
                            linewidth=theme.LINE_WIDTH, zorder=3)  # fmt: skip
                    ax.plot([r["coef"]], [y], "o", markersize=6,
                            color=colors[p] if filled else t["surface"],
                            markeredgecolor=colors[p], markeredgewidth=1.5, zorder=4)  # fmt: skip
        ax.set_yticks(range(len(labels)), labels, color=t["text"], fontsize=9.5)
        ax.set_ylim(len(labels) - 0.4, -0.8)
        ax.set_xlim(-1.25, 0.55)
        ax.xaxis.set_major_locator(MultipleLocator(0.25))
        ax.grid(axis="y", visible=False)
        ax.set_xlabel("Change in pre-duty import price per unit change in ln(1 + tariff) (β)",
                      color=t["muted"], fontsize=8.5)  # fmt: skip
        handles = [plt.Line2D([], [], color=colors[p], marker="o", lw=theme.LINE_WIDTH)
                   for p, _ in HERO_PERIODS]  # fmt: skip
        handles += [
            plt.Line2D([], [], color=t["muted"], marker="o", lw=0, markersize=6),
            plt.Line2D([], [], color=t["muted"], marker="o", lw=0, markersize=6,
                       markerfacecolor=t["surface"], markeredgewidth=1.5),
        ]  # fmt: skip
        names = [lbl for _, lbl in HERO_PERIODS]
        names += ["Winsorised 1/99 (main)", "Unit-value ratio > 3 dropped (ARW)"]
        fig.legend(handles, names, loc="upper left", bbox_to_anchor=(0.006, 0.83), ncol=4,
                   fontsize=8.5, labelcolor=t["text2"])  # fmt: skip
        theme.header(
            fig, "Who pays the tariffs at the border: 2018–19 and 2025–26 (draft)",
            "Estimated response of pre-duty import unit values to tariff changes, 95% CIs. "
            "β = 0: the duty is added in full to what US buyers pay;\nβ = −1: foreign exporters "
            "cut prices by the full duty. 12-month changes, HS6 × month and country × month "
            "fixed effects, SEs clustered by HS8.", t,
        )  # fmt: skip
        theme.footer(fig, theme.SOURCE_CENSUS, t,
                     note="Section 232 and IEEPA terms come from one regression with duties "
                     "split by authority; IEEPA duties began in 2025.")  # fmt: skip
        return theme.save(fig, "hero_border_pt", mode, out_dir)


def _beta_tick(v: float, _pos: int) -> str:
    return "US buyers pay  0" if abs(v) < 1e-9 else f"{v:+.1f}".replace("-", "−")


def chart_spec_curve(mode: str = "light", data: Path = ROBUSTNESS,
                     out_dir: Path | None = None) -> list[Path]:  # fmt: skip
    """P17: specification curve of beta on pre-duty unit values, 2018-19 and 2025-26."""
    from tpt.models import robustness as rb

    df = pl.read_csv(data).filter(pl.col("outcome") == "uv")
    rows = [(c, lbl) for c, lbl in rb.CLEANING.items()]
    rows += [(v.name, v.label) for v in rb.VARIANTS if v.name != "baseline"]
    with theme.style(mode) as t:
        color, main_c = t["series"][0], t["series"][1]
        fig, axes = plt.subplots(2, 2, figsize=(theme.WIDTH_IN, 7.6), sharex="col",
                                 gridspec_kw={"height_ratios": [1.15, 1]})  # fmt: skip
        fig.subplots_adjust(left=0.22, right=0.985, top=0.83, bottom=0.08, hspace=0.06,
                            wspace=0.06)  # fmt: skip
        for j, (period, title) in enumerate(HERO_PERIODS):
            p = df.filter(pl.col("period") == period).sort("coef")
            top, bot = axes[0, j], axes[1, j]
            x = list(range(p.height))
            top.axhline(0, color=t["axis"], linewidth=1, zorder=1)
            is_main = [(c == "w1" and v == "baseline")
                       for c, v in zip(p["cleaning"], p["variant"], strict=True)]  # fmt: skip
            cols = [main_c if m else color for m in is_main]
            top.vlines(x, p["ci_low"], p["ci_high"], colors=cols, linewidth=1.2, zorder=2)
            top.scatter(x, p["coef"], s=16, c=cols, edgecolors=t["surface"], linewidths=0.8,
                        zorder=3)  # fmt: skip
            top.set_ylim(-0.3, 0.45)
            top.yaxis.set_major_locator(MultipleLocator(0.1))
            top.yaxis.set_major_formatter(FuncFormatter(_beta_tick))
            top.set_title(title, color=t["text"])
            for i, (key, _) in enumerate(rows):
                on = [(c == key or v == key)
                      for c, v in zip(p["cleaning"], p["variant"], strict=True)]  # fmt: skip
                xs = [xi for xi, o in zip(x, on, strict=True) if o]
                bot.scatter(xs, [i] * len(xs), s=10, marker="s", color=t["text2"], zorder=3)
                bot.axhline(i, color=t["grid"], linewidth=0.6, zorder=1)
            bot.set_ylim(len(rows) - 0.5, -0.5)
            bot.set_yticks(range(len(rows)), [lbl for _, lbl in rows] if j == 0 else [],
                           fontsize=8, color=t["text"])  # fmt: skip
            bot.axhline(len(CLEAN_ROWS) - 0.5, color=t["axis"], linewidth=0.8)
            bot.set_xticks([])
            bot.grid(False)
            if j:
                top.tick_params(axis="y", labelleft=False)
        axes[0, 0].set_ylabel("β, pre-duty unit value", color=t["muted"], fontsize=8.5)
        theme.header(
            fig, "Pass-through estimates under alternative specifications",
            "Each column is one specification, sorted by its estimate (95% CI); the main "
            "specification is highlighted. Rows below mark its choices:\ncleaning rule (top "
            "four) and one change to the main specification. 12-month changes, HS6 × month and "
            "country × month FE unless marked.", t,
        )  # fmt: skip
        theme.footer(fig, theme.SOURCE_CENSUS, t,
                     note="Confidence intervals beyond the axis are clipped (value-weighted "
                     "specifications). Data: data/published/robustness.csv.")  # fmt: skip
        return theme.save(fig, "robustness_spec_curve", mode, out_dir)


def mask_sparse(df: pl.DataFrame, cols: list[str], share: float = 0.5) -> pl.DataFrame:
    """Null cols in months where a group has under `share` of its usual item count (Oct 2025:
    most CPI items not collected)."""
    full = pl.col("n_items").max().over("group")
    return df.with_columns(
        [pl.when(pl.col("n_items") >= share * full).then(pl.col(c)).alias(c) for c in cols]
    )


RETAIL_GROUPS = (("high", "Highest-exposure third"), ("low", "Lowest-exposure third"))


def chart3_retail(mode: str = "light", data: Path = RETAIL_HIGH_LOW,
                  out_dir: Path | None = None, period: str = "2025_26") -> list[Path]:  # fmt: skip
    """Chart 3: CPI of high- vs low-exposure goods, indexed to Jan 2025; raw (deseasonalised)
    and relative to each item's own 2023-24 trend."""
    df = mask_sparse(
        pl.read_csv(data, try_parse_dates=True).filter(pl.col("period") == period),
        ["index", "index_dt"],
    ).sort("month")
    panels = (("index", "Deseasonalised index"),
              ("index_dt", "Relative to each item's own 2023–24 trend"))  # fmt: skip
    vals = df.filter(pl.col("group").is_in(["high", "low"]))
    lo = min(vals["index"].min(), vals["index_dt"].min())
    hi = max(vals["index"].max(), vals["index_dt"].max())
    with theme.style(mode) as t:
        colors = {"high": t["series"][1], "low": t["series"][0]}
        fig, axes = plt.subplots(1, 2, figsize=(theme.WIDTH_IN, 5.4), sharey=True)
        fig.subplots_adjust(left=0.06, right=0.86, top=0.72, bottom=0.2, wspace=0.08)
        for ax, (col, title) in zip(axes, panels, strict=True):
            ax.axhline(100, color=t["axis"], linewidth=0.8, zorder=2)
            for when in (date(2025, 2, 1), date(2026, 2, 20)):
                ax.axvline(when, color=t["muted"], linewidth=0.8, zorder=2)
            for g, _ in RETAIL_GROUPS:
                p = df.filter(pl.col("group") == g)
                x = p["month"].to_list()
                ax.plot(x, p[col], color=colors[g], zorder=4)
                last = p.drop_nulls(col).row(-1, named=True)
                theme.end_dot(ax, last["month"], last[col], colors[g], t)
                if col == "index_dt":
                    ax.annotate(f"{last[col]:.1f}", (last["month"], last[col]), xytext=(7, 0),
                                textcoords="offset points", va="center", fontsize=8.5,
                                color=t["text2"], annotation_clip=False)  # fmt: skip
            ax.set_title(title, color=t["text"], fontsize=9.5)
            ax.set_ylim(lo - 0.6, hi + 1.2)
            ax.xaxis.set_major_locator(mdates.YearLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
            ax.set_xlim(df["month"].min(), df["month"].max())
        axes[0].annotate("First 2025 tariffs (Feb)", (date(2025, 2, 1), hi + 1.0), xytext=(-4, 0),
                         textcoords="offset points", ha="right", va="top", fontsize=8,
                         color=t["muted"])  # fmt: skip
        axes[0].annotate("IEEPA ruling", (date(2026, 2, 20), hi + 1.0), xytext=(-4, 0),
                         textcoords="offset points", ha="right", va="top", fontsize=8,
                         color=t["muted"])  # fmt: skip
        handles = [plt.Line2D([], [], color=colors[g], lw=theme.LINE_WIDTH)
                   for g, _ in RETAIL_GROUPS]  # fmt: skip
        fig.legend(handles, [label for _, label in RETAIL_GROUPS], loc="upper left",
                   bbox_to_anchor=(0.006, 0.80), ncol=2, fontsize=8.5,
                   labelcolor=t["text2"])  # fmt: skip
        n = {g: int(df.filter(pl.col("group") == g)["n_items"].max()) for g, _ in RETAIL_GROUPS}
        theme.header(
            fig, "Consumer prices of goods by tariff exposure",
            f"CPI goods items in the highest ({n['high']}) and lowest ({n['low']}) thirds of "
            "2025–26 tariff exposure (import share × tariff change), mean log index,\n"
            "Jan 2025 = 100. Item seasonal factors estimated on 2015–24.", t,
        )  # fmt: skip
        theme.footer(
            fig, "Source: BLS CPI-U (U.S. city average, not seasonally adjusted); exposure from "
            "Census imports, BEA 2017 supply and PCE bridge tables, tariff_actions.csv.", t,
            note="October 2025 not shown: BLS collected no prices for most items (federal "
            "shutdown). Exposure: data/processed/cpi_exposure.parquet (P18).",
        )  # fmt: skip
        return theme.save(fig, "chart3_retail", mode, out_dir)


DIVERSION_PANELS = (("s301", "Products on the 2018–19 Section 301 lists (China)"),
                    ("other", "All other products"))  # fmt: skip


def chart4_diversion(mode: str = "light", data: Path = DIVERSION_SHARES,
                     out_dir: Path | None = None) -> list[Path]:  # fmt: skip
    """Chart 4: supplier shares of US imports (12-month rolling), Section 301 products vs the
    rest, stacked in a fixed group order."""
    from tpt.models.diversion import GROUPS

    df = pl.read_csv(data, try_parse_dates=True)
    order = list(GROUPS)
    with theme.style(mode) as t:
        colors = dict(zip(order, t["series"], strict=True))
        fig, axes = plt.subplots(1, 2, figsize=(theme.WIDTH_IN, 5.8), sharey=True)
        fig.subplots_adjust(left=0.06, right=0.87, top=0.70, bottom=0.17, wspace=0.36)
        for ax, (panel, title) in zip(axes, DIVERSION_PANELS, strict=True):
            p = (
                df.filter(pl.col("panel") == panel)
                .pivot(on="group", index="month", values="share")
                .sort("month")
            )
            x = p["month"].to_list()
            ys = [p[g].fill_null(0).to_numpy() for g in order]
            ax.stackplot(x, ys, colors=[colors[g] for g in order], edgecolor=t["surface"],
                         linewidth=1.0, zorder=3)  # fmt: skip
            cum = 0.0
            for g, y in zip(order, ys, strict=True):
                if y[-1] >= 0.04:
                    short = g.replace("Southeast", "SE")
                    ax.annotate(f"{short} {y[-1]:.0%}", (x[-1], cum + y[-1] / 2), xytext=(5, 0),
                                textcoords="offset points", va="center", fontsize=7.5,
                                color=t["text2"], annotation_clip=False)  # fmt: skip
                cum += y[-1]
            ax.set_title(title, color=t["text"], fontsize=9.5)
            ax.set_ylim(0, 1)
            ax.set_xlim(x[0], x[-1])
            ax.grid(False)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
            ax.xaxis.set_major_locator(mdates.YearLocator(2))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
            for when in (date(2018, 7, 6), date(2025, 2, 4)):
                ax.axvline(when, color=t["surface"], linewidth=1.2, linestyle=(0, (2, 2)),
                           zorder=4)  # fmt: skip
        axes[1].tick_params(axis="y", labelleft=False)
        handles = [plt.Rectangle((0, 0), 1, 1, color=colors[g]) for g in order]
        fig.legend(handles, order, loc="upper left", bbox_to_anchor=(0.006, 0.80), ncol=8,
                   fontsize=8, labelcolor=t["text2"], handlelength=1.0,
                   columnspacing=1.2)  # fmt: skip
        theme.header(
            fig, "Where US imports come from: products tariffed on China in 2018–19 and the rest",
            "Share of US imports for consumption by supplier, 12-month rolling sums. Dotted "
            "lines: first Section 301 tariffs (Jul 2018), first 2025 tariffs (Feb 2025).\n"
            "Section 301 products: HS10 families with a China Section 301 rate in Dec 2019.", t,
        )  # fmt: skip
        theme.footer(
            fig, theme.SOURCE_CENSUS, t,
            note="Other Southeast Asia: Thailand, Malaysia, Indonesia, Cambodia, Philippines, "
            "Singapore, Laos, Burma. EU: 27 members. Chapters 98–99 excluded.",
        )  # fmt: skip
        return theme.save(fig, "chart4_diversion", mode, out_dir)


CLEAN_ROWS = ("w1", "w5", "trim1", "trim3")
FIGURES = [
    chart2_effective_rates,
    chart3_retail,
    chart4_diversion,
    chart5_front_running,
    chart6_low_value,
    hero_border_pt,
    chart_spec_curve,
]
QA_FIGURES = [qa_border_event_2018, qa_border_event_2025]  # light only, to reports/qa


def run() -> None:
    for fn in FIGURES:
        for mode in theme.MODES:
            for path in fn(mode):
                print(path.relative_to(config.PROJECT_ROOT))
    for fn in QA_FIGURES:
        for path in fn("light"):
            print(path.relative_to(config.PROJECT_ROOT))


if __name__ == "__main__":
    assert er.OUT == EFFECTIVE
    run()

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


FIGURES = [chart2_effective_rates, chart5_front_running, chart6_low_value]


def run() -> None:
    for fn in FIGURES:
        for mode in theme.MODES:
            for path in fn(mode):
                print(path.relative_to(config.PROJECT_ROOT))


if __name__ == "__main__":
    assert er.OUT == EFFECTIVE
    run()

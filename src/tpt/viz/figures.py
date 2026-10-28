"""Figure builders (P13, P21). Every figure is drawn from data/published/ in both modes.

Run: make figures   (writes report/figures/<name>.svg/.png and <name>_dark.svg/.png)
"""

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl
from matplotlib.ticker import FuncFormatter, MultipleLocator

from tpt import config
from tpt.build import effective_rates as er
from tpt.viz import theme

EFFECTIVE = config.PUBLISHED_DIR / "effective_rates.csv"
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


FIGURES = [chart2_effective_rates]


def run() -> None:
    for fn in FIGURES:
        for mode in theme.MODES:
            for path in fn(mode):
                print(path.relative_to(config.PROJECT_ROOT))


if __name__ == "__main__":
    assert er.OUT == EFFECTIVE
    run()

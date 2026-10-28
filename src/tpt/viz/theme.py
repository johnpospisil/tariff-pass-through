"""Shared chart theme (P13): one palette, neutral framing, consistent type, source footers.

Colors are the dataviz skill's validated reference palette (categorical slots in fixed order,
checked with its validate_palette.js in both modes: slots 1-2 pass every check, worst CVD
Delta E 24.7 light / 26.8 dark). Dark mode is its own set of steps, not an inversion.

Use: `with theme.style(mode): fig = ...; theme.save(fig, "chart2_effective_rates", mode)`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

from tpt import config

MODES = ("light", "dark")
TOKENS = {
    "light": {
        "surface": "#fcfcfb", "text": "#0b0b0b", "text2": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300",
                   "#6250d6", "#e34948"],
    },
    "dark": {
        "surface": "#1a1a19", "text": "#f0efec", "text2": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300",
                   "#9085e9", "#e66767"],
    },
}  # fmt: skip
FONT = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
LINE_WIDTH = 1.5  # points; ~2px at screen size
WIDTH_IN = 10.0
SOURCE_CENSUS = (
    "Source: U.S. Census Bureau, international trade (imports for consumption, calculated "
    "duties); tariff orders compiled from the Federal Register and HTSUS (tariff_actions.csv)."
)


def tokens(mode: str) -> dict:
    if mode not in TOKENS:
        raise ValueError(f"mode must be one of {MODES}")
    return TOKENS[mode]


@contextmanager
def style(mode: str = "light") -> Iterator[dict]:
    t = tokens(mode)
    rc = {
        "font.family": "sans-serif", "font.sans-serif": FONT, "font.size": 9,
        "figure.facecolor": t["surface"], "axes.facecolor": "none",  # figure paints the surface
        "savefig.facecolor": t["surface"], "text.color": t["text"],
        "axes.labelcolor": t["text2"], "axes.edgecolor": t["axis"], "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": t["grid"],
        "grid.linewidth": 0.7, "grid.linestyle": "-", "axes.axisbelow": True,
        "xtick.color": t["muted"], "ytick.color": t["muted"], "xtick.labelcolor": t["muted"],
        "ytick.labelcolor": t["muted"], "ytick.left": False, "xtick.major.size": 3,
        "xtick.major.width": 0.8, "axes.titlesize": 10, "axes.titleweight": "bold",
        "axes.titlecolor": t["text"], "axes.titlelocation": "left", "axes.titlepad": 6,
        "lines.linewidth": LINE_WIDTH, "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round", "legend.frameon": False,
        "svg.fonttype": "none",  # keep text as text in SVG (selectable, accessible)
    }  # fmt: skip
    with mpl.rc_context(rc):
        yield t


def header(fig: plt.Figure, title: str, subtitle: str, t: dict, top: float = 0.97) -> None:
    fig.text(0.012, top, title, ha="left", va="top", fontsize=13, weight="bold",
             color=t["text"])  # fmt: skip
    fig.text(0.012, top - 0.045, subtitle, ha="left", va="top", fontsize=9, color=t["text2"],
             linespacing=1.4)  # fmt: skip


def footer(fig: plt.Figure, source: str, t: dict, note: str = "") -> None:
    text = source if not note else f"{note}\n{source}"
    fig.text(0.012, 0.012, text, ha="left", va="bottom", fontsize=7.5, color=t["muted"],
             linespacing=1.4)  # fmt: skip


def end_dot(ax: plt.Axes, x, y, color: str, t: dict) -> None:
    """End marker >= 8px with a 2px surface ring."""
    ax.plot([x], [y], marker="o", markersize=6, color=color, markeredgecolor=t["surface"],
            markeredgewidth=1.5, zorder=5, clip_on=False)  # fmt: skip


def save(
    fig: plt.Figure, name: str, mode: str = "light", out_dir: Path | None = None
) -> list[Path]:
    """Write <name>.svg/.png (light) or <name>_dark.svg/.png to report/figures."""
    out_dir = out_dir or config.FIGURES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = name if mode == "light" else f"{name}_{mode}"
    paths = [out_dir / f"{stem}.svg", out_dir / f"{stem}.png"]
    fig.savefig(paths[0], metadata={"Date": None})  # no timestamp: stable diffs
    fig.savefig(paths[1], dpi=200)
    plt.close(fig)
    return paths

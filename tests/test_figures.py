"""Chart theme and figure builders render from published data (P13)."""

from datetime import date

import polars as pl
import pytest

from tpt.viz import figures, theme


@pytest.fixture
def effective_csv(tmp_path):
    months = [date(2024, m, 1) for m in range(1, 13)] + [date(2025, m, 1) for m in range(1, 9)]
    rows = [{"month": m, "group": g, "imports_bn": 10.0, "effective_rate": 0.02 + 0.001 * i,
             "statutory_rate": 0.03 + 0.002 * i, "effective_additional": 0.01,
             "statutory_additional": 0.02}
            for g in figures.PANELS for i, m in enumerate(months)]  # fmt: skip
    path = tmp_path / "effective_rates.csv"
    pl.DataFrame(rows).write_csv(path)
    return path


@pytest.mark.parametrize("mode", theme.MODES)
def test_chart2_writes_svg_and_png(effective_csv, tmp_path, mode):
    paths = figures.chart2_effective_rates(mode, data=effective_csv, out_dir=tmp_path)
    assert [p.suffix for p in paths] == [".svg", ".png"]
    assert all(p.stat().st_size > 10_000 for p in paths)
    svg = paths[0].read_text()
    assert "Tariff rates on U.S. imports by trading partner" in svg  # text kept as text
    assert theme.tokens(mode)["series"][0] in svg.lower()


def test_tokens_reject_unknown_mode():
    with pytest.raises(ValueError, match="mode"):
        theme.tokens("sepia")

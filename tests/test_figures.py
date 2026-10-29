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
    assert "Tariff rates on US imports by trading partner" in svg  # text kept as text
    assert theme.tokens(mode)["series"][0] in svg.lower()


def test_tokens_reject_unknown_mode():
    with pytest.raises(ValueError, match="mode"):
        theme.tokens("sepia")


@pytest.mark.parametrize("mode", theme.MODES)
def test_chart5_and_chart6_render(tmp_path, mode):
    ks = list(range(-9, 10))
    fr = pl.DataFrame([
        {"action": a, "label": a.title(), "k": k, "month": date(2025, 1, 1), "value": 1.0,
         "counterfactual": 1.0, "excess_pct": 0.01 * k, "band": 0.1, "band_low": -0.1}
        for a in ("a", "b", "c", "d", "e", "f") for k in ks
    ])  # fmt: skip
    fr.write_csv(tmp_path / "fr.csv")
    months = [date(2024, m, 1) for m in range(1, 13)] + [date(2025, m, 1) for m in range(1, 13)]
    lv = pl.DataFrame({"month": months, "china_hk_bn": [0.4] * 24, "rest_bn": [1.6] * 24,
                       "total_bn": [2.0] * 24, "imports_bn": [270.0] * 24,
                       "share_of_imports": [0.007] * 24})  # fmt: skip
    lv.write_csv(tmp_path / "lv.csv")
    p5 = figures.chart5_front_running(mode, data=tmp_path / "fr.csv", out_dir=tmp_path)
    p6 = figures.chart6_low_value(mode, data=tmp_path / "lv.csv", out_dir=tmp_path)
    assert all(p.exists() for p in p5 + p6)
    assert "$54.5bn" in p6[0].read_text()  # currency, not math text


def test_qa_border_event_renders(tmp_path):
    rows = [{"sample": s, "outcome": o, "k": k, "coef": 0.01 * k, "se": 0.01,
             "ci_low": 0.01 * k - 0.02,
             "ci_high": 0.01 * k + 0.02, "n": 100, "varieties_targeted": 10}
            for s in ("fgkk", "full") for o, _ in figures.EVENT_PANELS
            for k in range(-6, 7)]  # fmt: skip
    path = tmp_path / "event.csv"
    pl.DataFrame(rows).write_csv(path)
    paths = figures.qa_border_event_2018("light", data=path, out_dir=tmp_path)
    assert paths[1].stat().st_size > 10_000
    assert "replication check" in paths[0].read_text()


@pytest.mark.parametrize("mode", theme.MODES)
def test_hero_border_pt_renders(tmp_path, mode):
    rows = [
        {"period": p, "spec": spec, "outcome": "uv", "group": g, "coef": c, "ci_low": c - 0.05,
         "ci_high": c + 0.05}
        for p in ("2018_19", "2025_26")
        for (spec, g) in figures.HERO_ROWS.values()
        for spec, c in ((spec, 0.05), (figures.trim_spec(spec), -0.04))
        if not (p == "2018_19" and g == "ieepa")
    ]  # fmt: skip
    path = tmp_path / "border_pt.csv"
    pl.DataFrame(rows).write_csv(path)
    paths = figures.hero_border_pt(mode, data=path, out_dir=tmp_path)
    svg = paths[0].read_text()
    assert "Foreign exporters pay" in svg and "US buyers pay" in svg
    assert paths[1].stat().st_size > 10_000


@pytest.mark.parametrize("mode", theme.MODES)
def test_spec_curve_renders(tmp_path, mode):
    from tpt.models import robustness as rb

    rows = [
        {"period": p, "outcome": "uv", "cleaning": c, "variant": v.name, "coef": 0.01 * i,
         "ci_low": 0.01 * i - 0.05, "ci_high": 0.01 * i + 0.05}
        for p in ("2018_19", "2025_26")
        for i, s in enumerate(rb.grid(p))
        for c, v in [(s.cleaning, s.variant)]
    ]  # fmt: skip
    path = tmp_path / "robustness.csv"
    pl.DataFrame(rows).write_csv(path)
    paths = figures.chart_spec_curve(mode, data=path, out_dir=tmp_path)
    svg = paths[0].read_text()
    assert "Drop China" in svg and "Trim ratio" in svg
    assert paths[1].stat().st_size > 10_000


def _high_low_csv(tmp_path):
    months = [date(2023 + m // 12, m % 12 + 1, 1) for m in range(44)]
    rows = [{"group": g, "month": mo, "rel": 0.0, "n_items": 3 if mo == date(2025, 10, 1) else 40,
             "index": 100 + (i - 24) * (0.1 if g == "high" else 0.05),
             "index_dt": 100 + max(i - 24, 0) * (0.1 if g == "high" else 0.0),
             "period": "2025_26"}
            for g in ("high", "mid", "low") for i, mo in enumerate(months)]  # fmt: skip
    path = tmp_path / "retail_high_low.csv"
    pl.DataFrame(rows).write_csv(path)
    return path


def test_sparse_months_masked():
    df = pl.DataFrame({"group": ["high"] * 3, "n_items": [40, 3, 40], "index": [1.0, 2.0, 3.0]})
    assert figures.mask_sparse(df, ["index"])["index"].to_list() == [1.0, None, 3.0]


@pytest.mark.parametrize("mode", theme.MODES)
def test_chart3_retail_renders(tmp_path, mode):
    paths = figures.chart3_retail(mode, data=_high_low_csv(tmp_path), out_dir=tmp_path)
    svg = paths[0].read_text()
    assert "Consumer prices of goods by tariff exposure" in svg
    assert theme.tokens(mode)["series"][0] in svg.lower()


@pytest.mark.parametrize("mode", theme.MODES)
def test_chart4_diversion_renders(tmp_path, mode):
    from tpt.models import diversion as dv

    months = [date(2018 + m // 12, m % 12 + 1, 1) for m in range(36)]
    rows = [{"panel": p, "month": mo, "group": g, "value": 1.0, "value_r": 12.0,
             "share": 1 / len(dv.GROUPS)}
            for p in ("s301", "other") for mo in months for g in dv.GROUPS]  # fmt: skip
    path = tmp_path / "diversion_shares.csv"
    pl.DataFrame(rows).write_csv(path)
    paths = figures.chart4_diversion(mode, data=path, out_dir=tmp_path)
    svg = paths[0].read_text()
    assert "Where US imports come from" in svg


def test_every_figure_has_alt_text_and_a_data_table():
    names = {fn.__name__ for fn in figures.FIGURES}
    assert names == set(figures.ALT_TEXT)
    for name, entry in figures.ALT_TEXT.items():
        assert len(entry["alt"]) > 80, name
        assert entry["data"].startswith("data/published/"), name


def test_manifest_written(tmp_path):
    path = figures.write_manifest(tmp_path / "alt_text.json")
    import json

    m = json.loads(path.read_text())
    assert m["hero_border_pt"]["files"]["light"] == "hero_border_pt.png"
    assert m["hero_border_pt"]["files"]["dark"] == "hero_border_pt_dark.png"

"""Product explorer bundle (P23): encoding, aggregation of minor sources, file layout,
reconciliation of the bundle with the import panel."""

import json
from datetime import date

import duckdb
import polars as pl
import pytest

from tpt import config
from tpt.report import explorer as ex


def test_rle_keeps_change_points_only():
    assert ex.rle([0.1, 0.1, None, None, 0.25, 0.25]) == [[0, 0.1], [2, None], [4, 0.25]]
    assert ex.rle([]) == []


def test_sig_rounding():
    assert ex.sig(123456.0, 4) == 123500.0
    assert ex.sig(0.0012345, 3) == 0.00123
    assert ex.sig(None) is None and ex.sig(0.0) == 0.0


def _rows() -> pl.DataFrame:
    """One HS10 with seven sources over two months; sources F and G are the smallest."""
    rows = []
    for m in (date(2025, 1, 1), date(2025, 2, 1)):
        for i, c in enumerate("ABCDEFG"):
            v = 1000.0 * (10 - i)
            rows.append({"hs10": "8450110010", "cty_code": c, "month": m, "v": v,
                         "d": 0.1 * v, "q": v / 2, "unit": "NO", "r": 0.1 * i})  # fmt: skip
    df = pl.DataFrame(rows)
    # a shipment of G in a different unit: counts in value, not in unit values
    odd = {"hs10": "8450110010", "cty_code": "G", "month": date(2025, 2, 1), "v": 500.0,
           "d": 0.0, "q": 7.0, "unit": "KG", "r": 0.6}  # fmt: skip
    return pl.concat([df, pl.DataFrame([odd])])


def test_product_top_sources_and_other():
    p = ex.product(_rows(), months=[date(2025, 1, 1), date(2025, 2, 1)], k=5)
    assert p["u"] == "NO" and p["s"][0]["m0"] == 0
    codes = [s["c"] for s in p["s"]]
    assert codes == ["A", "B", "C", "D", "E", "other"]
    other = p["s"][-1]
    # Jan: F (5000) + G (4000) = $9.0k; Feb adds G's 500 KG shipment
    assert other["v"] == [9.0, 9.5]
    # unit value uses only same-unit rows: (5000+4000) / (2500+2000) = 2
    assert other["uv"] == [2.0, 2.0]
    assert other["e"] == [[0, 0.1], [1, 0.09]]  # Feb: duty-free KG shipment, 900 / 9,500
    # value-weighted statutory rate of F (0.5) and G (0.6)
    assert other["r"][0] == [0, pytest.approx((5000 * 0.5 + 4000 * 0.6) / 9000, abs=1e-3)]
    a = p["s"][0]
    assert a["v"] == [10.0, 10.0] and a["uv"] == [2.0, 2.0] and a["r"] == [[0, 0.0]]


def test_product_trims_to_traded_months():
    df = _rows().filter(pl.col("month") == date(2025, 2, 1))
    p = ex.product(df, months=[date(2025, 1, 1), date(2025, 2, 1)], k=5)
    assert p["s"][0]["m0"] == 1 and len(p["s"][0]["v"]) == 1


def test_series_trimmed_and_rates_carried_through_gaps():
    df = _rows().filter(pl.col("cty_code") != "B")
    gap = df.filter((pl.col("cty_code") == "A") & (pl.col("month") == date(2025, 1, 1)))
    gap = gap.with_columns(month=pl.lit(date(2025, 3, 1)))
    p = ex.product(pl.concat([df.filter(pl.col("cty_code") != "A"), gap,
                              df.filter((pl.col("cty_code") == "A")
                                        & (pl.col("month") == date(2025, 1, 1)))]),
                   months=[date(2025, m, 1) for m in (1, 2, 3)], k=5)  # fmt: skip
    a = p["s"][0]
    assert a["c"] == "A" and a["v"] == [10, 0, 10] and a["uv"] == [2, 0, 2]
    assert a["r"] == [[0, 0.0]] and a["e"] == [[0, 0.1]]
    assert max(s["m0"] + len(s["v"]) for s in p["s"][1:]) == 2  # others stop in February


def test_aliases_resolve_to_descriptions():
    """Every alias expands to words that all appear in at least one HS10 description."""
    attrs = config.PROCESSED_DIR / "hs10_attributes.parquet"
    if not attrs.exists():
        pytest.skip("attributes not built")
    descs = [ex.words(d) for d in pl.read_parquet(attrs, columns=["desc_long"])
             .get_column("desc_long").drop_nulls().unique()]  # fmt: skip
    for term, expansion in ex.aliases().items():
        want = ex.words(expansion)
        assert any(all(any(w.startswith(t) for w in d) for t in want) for d in descs), term


def test_words_stems_plurals():
    assert ex.words("Washing machines, household-type") == ["washing", "machine", "household",
                                                           "type"]  # fmt: skip
    assert ex.words("TOYS; glasses") == ["toy", "glass"]


# --- built bundle -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bundle():
    if not (ex.OUT_DIR / "index.json").exists():
        pytest.skip("explorer bundle not built")
    return json.loads((ex.OUT_DIR / "meta.json").read_text()), json.loads(
        (ex.OUT_DIR / "index.json").read_text()
    )


def test_index_points_at_files_with_every_product(bundle):
    meta, index = bundle
    assert meta["months"][0] == "2017-01" and meta["data_month"] == meta["months"][-1]
    rows = index["rows"]
    assert len(rows) > 15_000
    by_file: dict[str, set] = {}
    for hs10, _desc, _val in rows:
        by_file.setdefault(ex.file_for(hs10), set()).add(hs10)
    for rel, codes in list(by_file.items())[::50]:
        assert codes <= set(json.loads((ex.OUT_DIR / rel).read_text())), rel


def test_files_stay_small(bundle):
    """A page view loads the index plus one heading file; the bundle is not committed."""
    sizes = [f.stat().st_size for f in ex.OUT_DIR.glob("[0-9]*/*.json")]
    assert (ex.OUT_DIR / "index.json").stat().st_size < 3e6
    assert max(sizes) < 2e6, max(sizes)
    assert sum(sizes) < 150e6


def test_bundle_reconciles_with_panel(bundle):
    """Import value by month in the bundle matches the HS10 panel within rounding."""
    meta, _ = bundle
    got = [0.0] * len(meta["months"])
    for f in ex.OUT_DIR.glob("[0-9]*/*.json"):
        for p in json.loads(f.read_text()).values():
            for s in p["s"]:
                for i, v in enumerate(s["v"]):
                    got[s["m0"] + i] += v
    want = duckdb.sql(f"""
        select strftime(month, '%Y-%m') m, sum(con_val) / 1e3 v
        from '{config.PROCESSED_DIR / "import_panel.parquet"}'
        where level = 'hs10' and substr(prod_id, 1, 2) not in ('98', '99')
        group by 1 order by 1""").fetchall()
    assert [m for m, _ in want] == meta["months"]
    for (m, v), g in zip(want, got, strict=True):
        assert g == pytest.approx(v, rel=1e-3), m

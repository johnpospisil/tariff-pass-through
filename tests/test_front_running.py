"""Front-running event studies (P14): counterfactuals, bands, stockpiling windows."""

import math
from datetime import date

import polars as pl
import pytest

from tpt.build import front_running as fr


def monthly(values: dict[str, float]) -> pl.DataFrame:
    return pl.DataFrame({"month": [date.fromisoformat(m + "-01") for m in values],
                         "value": list(values.values())})  # fmt: skip


def series(growth: float = 0.05, bumps: dict[str, float] | None = None) -> pl.DataFrame:
    """2022-01..2025-12 with seasonality, steady growth, optional multiplicative bumps."""
    bumps = bumps or {}
    out = {}
    for y in range(2022, 2026):
        for m in range(1, 13):
            key = f"{y}-{m:02d}"
            base = 100 * (1 + growth) ** (y - 2022) * (1.3 if m == 12 else 1.0)
            out[key] = base * bumps.get(key, 1.0)
    return monthly(out)


def test_counterfactual_is_last_year_times_pre_growth():
    es = fr.event_study(series(0.05, {"2025-03": 1.4, "2025-05": 0.8}), date(2025, 4, 1))
    row = es.filter(pl.col("month") == date(2025, 3, 1)).row(0, named=True)
    assert row["k"] == -1
    assert row["counterfactual"] == pytest.approx(100 * 1.05**2 * 1.05)  # 2024-03 x growth
    assert row["excess_pct"] == pytest.approx(0.4)
    assert es.filter(pl.col("month") == date(2025, 5, 1))["excess_pct"][0] == pytest.approx(-0.2)
    assert es.filter(pl.col("month") == date(2025, 1, 1))["excess_pct"][0] == pytest.approx(0)
    assert es["band"].max() == pytest.approx(0, abs=1e-12)  # no noise in the pre period


def test_control_adjusts_for_common_shocks():
    # treated and control both +20% in 2025-09 (common shock); treated alone +30% in 2025-07
    treated = series(0.0, {"2025-09": 1.2, "2025-07": 1.3})
    control = series(0.0, {"2025-09": 1.2})
    es = fr.event_study(treated, date(2025, 8, 1), control=control)
    get = dict(zip(es["month"], es["excess_pct"], strict=True))
    assert get[date(2025, 9, 1)] == pytest.approx(0.0)
    assert get[date(2025, 7, 1)] == pytest.approx(0.3)


def test_summary_counts_consecutive_significant_pre_months():
    es = pl.DataFrame({
        "k": [-4, -3, -2, -1, 0, 1, 2],
        "value": [100.0, 130, 140, 150, 90, 80, 95],
        "counterfactual": [100.0] * 7,
        "excess_pct": [0.0, 0.30, 0.40, 0.50, -0.10, -0.20, -0.05],
        "band": [0.1] * 7,
    })  # fmt: skip
    s = fr.summarize(es)
    assert s["stockpile_months"] == 3  # k = -3..-1 above the band
    assert s["excess_pre"] == pytest.approx(120.0)  # 30 + 40 + 50
    assert s["positive_months"] == 3 and s["excess_positive"] == pytest.approx(120.0)
    assert s["shortfall_post"] == pytest.approx(-35.0)  # k = 0..2: -10 - 20 - 5
    assert s["peak_k"] == -1 and s["peak_pct"] == pytest.approx(0.5)


def test_band_is_two_sd_of_log_growth_in_pre_period():
    vals = {f"{y}-{m:02d}": 100.0 for y in (2022, 2023, 2025) for m in range(1, 13)}
    vals |= {f"2024-{m:02d}": (110.0 if m % 2 else 90.0) for m in range(1, 13)}
    es = fr.event_study(monthly(dict(sorted(vals.items()))), date(2025, 4, 1))
    # pre window 2023-10..2024-09: three months of log(1) then 2024-01..09 alternating
    logs = [0.0] * 3 + [math.log(1.1) if m % 2 else math.log(0.9) for m in range(1, 10)]
    mean = sum(logs) / 12
    sd = (sum((x - mean) ** 2 for x in logs) / 11) ** 0.5
    assert es["band"][0] == pytest.approx(math.exp(2 * sd) - 1, rel=1e-6)

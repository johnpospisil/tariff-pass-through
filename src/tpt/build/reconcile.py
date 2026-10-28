"""Reconciliation gates for the Census HS10 pull (P04).

Gate 1 (hard): monthly general imports summed over HS10 x individual countries vs the FT-900
  total ("World, NSA", Census basis). Tolerance 0.5% per month. Also a per-partner check for
  the largest partners (informational).
Gate 2: monthly calculated duties vs Treasury customs-duty gross receipts (MTS table 4). Duties
  are assessed at entry and paid on a monthly statement, so receipts lag by one month (lag 1
  correlates 0.85 in changes vs 0.61 at lag 0). Census duties run ~12% below Treasury gross in
  every year (a stable coverage difference, see DATA.md), so the gate tests that the 3-month
  rolling ratio (duties in t-2..t vs receipts in t-1..t+1) stays within 10% of its 2017-2024
  median. Deviations must be listed in TREASURY_EXPLAINED_MONTHS with a reason in DATA.md.
  Refunds (net receipts) are reported, not gated: IEEPA refunds from 2026-05 make net
  receipts negative.

Run:  make reconcile   (after `make ingest`)
Outputs: reports/qa/reconcile_ft900.csv, reconcile_partners.csv, reconcile_treasury.csv,
         reconcile.png
"""

from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402

from tpt import config  # noqa: E402
from tpt.ingest import census_trade, ft900, treasury_mts  # noqa: E402

QA_DIR = config.PROJECT_ROOT / "reports" / "qa"
FT900_REPORT = QA_DIR / "reconcile_ft900.csv"
PARTNER_REPORT = QA_DIR / "reconcile_partners.csv"
TREASURY_REPORT = QA_DIR / "reconcile_treasury.csv"
CHART = QA_DIR / "reconcile.png"

FT900_TOLERANCE = 0.005
TREASURY_TOLERANCE = 0.10
TREASURY_LAG = 1  # months from duty assessment to cash receipt
TREASURY_BASELINE = (date(2017, 1, 1), date(2024, 12, 1))
TOP_PARTNERS = 15

# Months whose ratio deviation exceeds the tolerance for a documented reason
# (see DATA.md, "Treasury reconciliation"). Empty until a gap is investigated.
TREASURY_EXPLAINED_MONTHS: list[date] = []


def census_monthly(by_country: bool = False) -> pl.DataFrame:
    """Sum the HS10 panel over individual countries (and HS10) by month."""
    keys = ["month", "cty_code"] if by_country else ["month"]
    return (
        pl.scan_parquet(census_trade.INTERIM_IMPORTS / "*" / "data.parquet")
        .group_by(keys)
        .agg(pl.col("gen_val_mo", "con_val_mo", "cal_dut_mo").sum().cast(pl.Float64))
        .sort(keys)
        .collect()
    )


def ft900_gate(
    census: pl.DataFrame, ft: pl.DataFrame, tolerance: float = FT900_TOLERANCE
) -> pl.DataFrame:
    return (
        census.select("month", "gen_val_mo")
        .join(ft.select("month", "ft900_imports_usd"), on="month", how="left")
        .with_columns(
            ((pl.col("gen_val_mo") / pl.col("ft900_imports_usd") - 1) * 100).alias("gap_pct")
        )
        .with_columns((pl.col("gap_pct").abs() <= tolerance * 100).fill_null(False).alias("pass"))
        .sort("month")
    )


def partner_check(census_cty: pl.DataFrame, ft_long: pl.DataFrame) -> pl.DataFrame:
    """Gap by month for the largest partners (by import value over the sample)."""
    top = (
        census_cty.group_by("cty_code")
        .agg(pl.col("gen_val_mo").sum())
        .sort("gen_val_mo", descending=True)
        .head(TOP_PARTNERS)["cty_code"]
    )
    joined = census_cty.filter(pl.col("cty_code").is_in(top.to_list())).join(
        ft_long.select("cty_code", "cty_name", "month", "imports_usd"),
        on=["cty_code", "month"],
        how="left",
    )
    return (
        joined.with_columns(
            ((pl.col("gen_val_mo") / pl.col("imports_usd") - 1) * 100).alias("gap_pct")
        )
        .group_by("cty_code", "cty_name")
        .agg(
            (pl.col("gen_val_mo").sum() / 1e9).alias("imports_bn"),
            pl.col("gap_pct").abs().max().alias("max_abs_gap_pct"),
            pl.col("gap_pct").abs().mean().alias("mean_abs_gap_pct"),
            pl.col("imports_usd").is_null().sum().alias("months_missing_in_ft900"),
        )
        .sort("imports_bn", descending=True)
    )


def treasury_comparison(
    census: pl.DataFrame, mts: pl.DataFrame, lag: int = TREASURY_LAG
) -> pl.DataFrame:
    """Duties assessed in month t vs receipts in month t+lag, levels and 3-month rolling."""
    receipts = mts.with_columns(pl.col("month").dt.offset_by(f"-{lag}mo"))
    df = (
        census.select("month", "cal_dut_mo")
        .join(receipts, on="month", how="left")
        .sort("month")
        .with_columns(
            (pl.col("cal_dut_mo").rolling_sum(3) / pl.col("mts_gross_usd").rolling_sum(3)).alias(
                "ratio_3m"
            ),
            ((pl.col("cal_dut_mo") / pl.col("mts_gross_usd") - 1) * 100).alias("gap_gross_pct"),
        )
    )
    lo, hi = TREASURY_BASELINE
    baseline = df.filter(pl.col("month").is_between(lo, hi))["ratio_3m"].median()
    return df.with_columns(
        pl.lit(baseline).alias("baseline_ratio"),
        ((pl.col("ratio_3m") / baseline - 1) * 100).alias("ratio_dev_pct"),
    )


def chart(ft_report: pl.DataFrame, tr_report: pl.DataFrame) -> None:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    ax1.plot(ft_report["month"], ft_report["gap_pct"], color="#2a6f97", lw=1.5)
    for y in (-FT900_TOLERANCE * 100, FT900_TOLERANCE * 100):
        ax1.axhline(y, color="#c0392b", ls="--", lw=0.8)
    ax1.axhline(0, color="#888", lw=0.5)
    ax1.set_ylabel("HS10 sum vs FT-900 (%)")
    ax1.set_title("Gate 1: general imports, HS10 x country sum vs FT-900 total (±0.5% dashed)")

    ax2.plot(tr_report["month"], tr_report["cal_dut_mo"] / 1e9, label="Census calculated duties")
    ax2.plot(tr_report["month"], tr_report["mts_gross_usd"] / 1e9, label="Treasury gross receipts")
    ax2.plot(tr_report["month"], tr_report["mts_net_usd"] / 1e9, label="Treasury net receipts",
             ls=":")  # fmt: skip
    ax2.set_ylabel("$ billion per month")
    ax2.set_title("Gate 2: calculated duties (month t) vs Treasury receipts (month t+1)")
    ax2.legend(frameon=False)
    for ax in (ax1, ax2):
        ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.01, 0.005, "Sources: Census International Trade API; Census FT-900 country file; "
             "Treasury Monthly Treasury Statement.", fontsize=8, color="#555")  # fmt: skip
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(CHART, dpi=150)
    plt.close(fig)


def run(refresh_sources: bool = True) -> None:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    ft_long = ft900.run() if refresh_sources else pl.read_parquet(ft900.INTERIM_PATH)
    mts = treasury_mts.run() if refresh_sources else pl.read_parquet(treasury_mts.INTERIM_PATH)
    ft_totals = ft_long.filter(pl.col("cty_code") == ft900.WORLD_NSA).select(
        "month", pl.col("imports_usd").alias("ft900_imports_usd")
    )

    census = census_monthly()
    g1 = ft900_gate(census, ft_totals)
    g1.write_csv(FT900_REPORT)
    partners = partner_check(census_monthly(by_country=True), ft_long)
    partners.write_csv(PARTNER_REPORT)
    g2 = treasury_comparison(census, mts)
    g2.write_csv(TREASURY_REPORT)
    chart(g1, g2)

    print(f"\nGate 1 (FT-900, ±{FT900_TOLERANCE:.1%}): {g1['pass'].sum()}/{g1.height} months pass; "
          f"max |gap| {g1['gap_pct'].abs().max():.4f}%")  # fmt: skip
    print(partners.with_columns(pl.col(pl.Float64).round(4)))
    over = g2.filter(pl.col("ratio_dev_pct").abs() > TREASURY_TOLERANCE * 100)
    dev = g2["ratio_dev_pct"].drop_nulls()
    print(f"\nGate 2 (Treasury, lag {TREASURY_LAG}, 3-month ratio within ±{TREASURY_TOLERANCE:.0%} "
          f"of baseline {g2['baseline_ratio'][0]:.3f}): {over.height} months over; "
          f"deviation range {dev.min():.1f}% to {dev.max():.1f}%")  # fmt: skip
    print(f"Reports in {QA_DIR.relative_to(config.PROJECT_ROOT)}/")


if __name__ == "__main__":
    run()

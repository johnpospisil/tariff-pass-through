"""Monthly effective and statutory tariff rates, overall and by partner (P13).

effective_rate = Census calculated duties / imports for consumption (all duties, incl. MFN;
the definition Penn Wharton and others use). statutory_rate = the P10 statutory additional rate
plus the MFN duty term from P11 (MFN rate x dutiable value capped at the reference-year share),
so the two are on the same basis; statutory_additional and effective_additional leave MFN out.
Weights are same-month imports; all imports for consumption of individual countries.
The EU is the 27 current members for the whole period.

Run: make effective-rates   (writes data/published/effective_rates.csv)
"""

import polars as pl

from tpt import config
from tpt.build import validate_rates as vr

OUT = config.PUBLISHED_DIR / "effective_rates.csv"
GROUPS_CSV = config.REFERENCE_DIR / "country_groups.csv"
PARTNERS = {"China": "5700", "Canada": "1220", "Mexico": "2010", "EU": "EU27",
            "Japan": "5880", "Vietnam": "5520", "India": "5330"}  # fmt: skip


def groups() -> dict[str, set[str] | None]:
    """Partner name -> Census country codes (None = all individual countries)."""
    g = pl.read_csv(GROUPS_CSV, schema_overrides={"cty_code": pl.String})
    out: dict[str, set[str] | None] = {"All countries": None}
    for name, code in PARTNERS.items():
        members = set(g.filter(pl.col("group") == code)["cty_code"])
        out[name] = members or {code}
    return out


def series(df: pl.DataFrame, groups: dict[str, set[str] | None]) -> pl.DataFrame:
    """df: cty_code, month, con_val, cal_dut, mfn_dut, rate_total (pair-months)."""
    frames = []
    for name, codes in groups.items():
        sub = df if codes is None else df.filter(pl.col("cty_code").is_in(list(codes)))
        frames.append(
            sub.group_by("month")
            .agg(
                v=pl.col("con_val").sum(),
                d=pl.col("cal_dut").sum(),
                m=pl.col("mfn_dut").sum(),
                s=(pl.col("rate_total") * pl.col("con_val")).sum(),
            )
            .select(
                "month",
                group=pl.lit(name),
                imports_bn=pl.col("v") / 1e9,
                effective_rate=pl.col("d") / pl.col("v"),
                statutory_rate=(pl.col("s") + pl.col("m")) / pl.col("v"),
                effective_additional=(pl.col("d") - pl.col("m")) / pl.col("v"),
                statutory_additional=pl.col("s") / pl.col("v"),
            )
        )
    return pl.concat(frames).sort("group", "month")


def run() -> pl.DataFrame:
    df = vr.load()
    df = vr.implied(df, vr.ref_shares(df)).select(
        "cty_code", "month", "con_val", "cal_dut", "mfn_dut", "rate_total"
    )
    out = series(df, groups())
    order = {g: i for i, g in enumerate(["All countries", *PARTNERS])}
    out = out.sort(pl.col("group").replace_strict(order), "month")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.write_csv(OUT, float_precision=5)
    latest = out.filter(pl.col("month") == out["month"].max())
    print(f"{OUT.name}: {out.height} rows")
    print(latest)
    return out


if __name__ == "__main__":
    run()

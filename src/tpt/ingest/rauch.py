"""Rauch (1999) goods classification, mapped to HS6 (P06).

Rauch classifies SITC Rev. 2 4-digit goods as w (traded on an organized exchange),
r (reference priced) or n (differentiated), under a conservative (con) and liberal (lib)
rule. HS6 -> SITC Rev. 2 correspondences come from the R `concordance` package
(Liao, Kim, Miyano & Zhang; MIT licence), built from UN/WITS tables:
  hs5 = HS 2017 (used for 2017-2021), hs6 = HS 2022 (used for 2022+).

Output: data/interim/rauch_hs6.parquet (hs_revision, hs6, rauch_con, rauch_lib, rauch_mixed).
"""

import polars as pl
import pyreadr

from tpt import config
from tpt.ingest._http import CachedClient

REPO = "https://raw.githubusercontent.com/insongkim/concordance/master/"
RAUCH_URL = REPO + "data-raw/rauch_classification_rev2.xlsx"
HS_SITC2 = {"HS2017": REPO + "data/hs5_sitc2.RData", "HS2022": REPO + "data/hs6_sitc2.RData"}
REVISION_START = {"HS2017": 2017, "HS2022": 2022}

INTERIM_PATH = config.INTERIM_DIR / "rauch_hs6.parquet"


def hs_revision(year: int) -> str:
    return max((start, rev) for rev, start in REVISION_START.items() if start <= year)[1]


def hs6_classification(hs_sitc: pl.DataFrame, classes: pl.DataFrame) -> pl.DataFrame:
    """Modal Rauch class across an HS6's SITC2 matches; rauch_mixed if they disagree (con)."""
    joined = hs_sitc.join(classes, on="sitc2_4d", how="inner")

    def modal(col: str) -> pl.DataFrame:
        return (
            joined.group_by("hs6", col)
            .len()
            .sort(["hs6", "len", col], descending=[False, True, False])
            .group_by("hs6", maintain_order=True)
            .first()
            .select("hs6", pl.col(col).alias(f"rauch_{col}"))
        )

    mixed = joined.group_by("hs6").agg((pl.col("con").n_unique() > 1).alias("rauch_mixed"))
    return modal("con").join(modal("lib"), on="hs6").join(mixed, on="hs6")


def run() -> pl.DataFrame:
    client = CachedClient("download")
    classes = pl.read_excel(client.get(RAUCH_URL).content, sheet_id=1, infer_schema_length=0)
    classes = classes.rename({"sitc4": "sitc2_4d"}).with_columns(
        pl.col("con", "lib").str.strip_chars()
    )
    frames = []
    for rev, url in HS_SITC2.items():
        resp = client.get(url)
        table = next(iter(pyreadr.read_r(str(resp.path)).values()))
        hs_sitc = pl.from_pandas(table).select(
            pl.col(table.columns[0]).alias("hs6"), pl.col("SITC2_4d").alias("sitc2_4d")
        )
        frames.append(hs6_classification(hs_sitc, classes).with_columns(hs_revision=pl.lit(rev)))
    out = pl.concat(frames).select("hs_revision", "hs6", "rauch_con", "rauch_lib", "rauch_mixed")
    out.write_parquet(INTERIM_PATH)
    print(
        "Rauch HS6:",
        out.group_by("hs_revision", "rauch_con").len().sort("hs_revision", "rauch_con").rows(),
    )
    return out


if __name__ == "__main__":
    run()

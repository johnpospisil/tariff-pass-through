"""BLS mapping of CPI entry level items (ELIs) to BEA PCE series (P06).

Source: bls.gov/cpi/additional-resources/pce-cpi-code-mapping.htm (built for a 2011 BEA/BLS
reconciliation project; ELI codes are of that vintage). Fetched with the contact User-Agent
bls.gov requires.

Output: data/interim/cpi_pce_map.parquet (eli, eli_desc, pce_code, pce_desc).
"""

import html
import re

import polars as pl

from tpt import config
from tpt.ingest._http import CachedClient

URL = "https://www.bls.gov/cpi/additional-resources/pce-cpi-code-mapping.htm"
INTERIM_PATH = config.INTERIM_DIR / "cpi_pce_map.parquet"


def _cell(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<.*?>", " ", raw))).strip()


def parse_mapping(page: str) -> pl.DataFrame:
    rows = []
    for table in re.findall(r"<table.*?</table>", page, flags=re.S):
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, flags=re.S):
            cells = [_cell(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.S)]
            if len(cells) == 4 and cells[0] != "ELI":
                rows.append(cells)
    return pl.DataFrame(rows, schema=["eli", "eli_desc", "pce_code", "pce_desc"], orient="row")


def run() -> pl.DataFrame:
    client = CachedClient("blsdownload")
    resp = client.get(URL)
    df = parse_mapping(resp.content.decode("utf-8", errors="replace")).unique(maintain_order=True)
    client.record_rows(resp, df.height)
    df.write_parquet(INTERIM_PATH)
    print(f"CPI-PCE map: {df.height} rows, {df['eli'].n_unique()} ELIs, "
          f"{df['pce_code'].n_unique()} PCE series")  # fmt: skip
    return df


if __name__ == "__main__":
    run()

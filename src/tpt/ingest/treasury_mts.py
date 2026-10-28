"""Monthly Treasury Statement, table 4 (receipts by source): customs duties.

Source: Fiscal Data API, `v1/accounting/mts/mts_table_4`, line "Customs Duties". Gross receipts,
refunds and net receipts for the month, in dollars, on a cash basis (so they lag duties assessed
at entry). Used for P04 gate 2.
"""

from datetime import date

import polars as pl

from tpt import config
from tpt.ingest._http import CachedClient

URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts/mts_table_4"
)
LINE = "Customs Duties"
START = "2016-10-01"  # start of FY2017, before our sample window

INTERIM_PATH = config.INTERIM_DIR / "treasury_customs.parquet"


def parse_customs(payload: dict) -> pl.DataFrame:
    rows = [r for r in payload["data"] if r["classification_desc"] == LINE]
    return pl.DataFrame(
        {
            "month": [date.fromisoformat(r["record_date"]).replace(day=1) for r in rows],
            "mts_gross_usd": [float(r["current_month_gross_rcpt_amt"]) for r in rows],
            "mts_refund_usd": [float(r["current_month_refund_amt"]) for r in rows],
            "mts_net_usd": [float(r["current_month_net_rcpt_amt"]) for r in rows],
        },
        schema={
            "month": pl.Date,
            "mts_gross_usd": pl.Float64,
            "mts_refund_usd": pl.Float64,
            "mts_net_usd": pl.Float64,
        },
    )


def fetch(client: CachedClient | None = None) -> pl.DataFrame:
    """All months since START. Always fresh: the latest page changes every release."""
    client = client or CachedClient("fiscaldata")
    frames, page = [], 1
    while True:
        params = {
            "filter": f"classification_desc:eq:{LINE},record_date:gte:{START}",
            "sort": "record_date",
            "page[size]": "1000",
            "page[number]": str(page),
        }
        resp = client.get(URL, params, refresh=True)
        payload = resp.json()
        df = parse_customs(payload)
        client.record_rows(resp, df.height)
        frames.append(df)
        if page >= int(payload["meta"]["total-pages"]):
            break
        page += 1
    return pl.concat(frames).unique("month").sort("month")


def run() -> pl.DataFrame:
    df = fetch()
    INTERIM_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(INTERIM_PATH)
    print(f"Treasury MTS customs duties: {df.height} months, "
          f"{df['month'].min()} to {df['month'].max()}")  # fmt: skip
    return df


if __name__ == "__main__":
    run()

# Who Pays the Tariffs?

*At the Border and at the Store: Tariff Pass-Through in 2025–26*

This project uses monthly product-level US import data, BLS import price indexes and CPI to measure how
much of the 2025–26 tariffs were paid by US importers and consumers and how much was absorbed by foreign
exporters. It also tracks how quickly imports shifted between countries.

> Status: in development. Findings, the report link and the product explorer will be added here.

## Quick start

```bash
uv sync                    # install dependencies (Python 3.12)
cp .env.example .env       # optional: add free Census and BLS API keys
make test                  # run tests
make all                   # ingest -> build -> models -> figures -> report
```

API keys (free, optional; they raise rate limits):
- Census: https://api.census.gov/data/key_signup.html
- BLS v2: https://data.bls.gov/registrationEngine/

## Layout

```
src/tpt/ingest/    download and parse sources (Census trade, BLS, BEA)
src/tpt/build/     tariff timeline, import panel, concordances, exposure
src/tpt/models/    border pass-through, retail DiD, trade diversion
src/tpt/viz/       chart theme and figures
data/reference/    hand-built, cited tables (committed)
data/published/    aggregates used by the report and explorer
report/            Quarto article
app/               product explorer
tests/             reconciliation gates and pinned estimates
```

Data sources and known issues are documented in [DATA.md](DATA.md).

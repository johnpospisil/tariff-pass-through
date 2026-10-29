# Who Pays the Tariffs?

*At the Border and at the Store: Tariff Pass-Through in 2025–26*

How much of the 2025–26 US tariffs did US importers and consumers pay, and how much did foreign
exporters absorb? This project measures it with monthly product-level import data (HS10 × country),
BLS import price indexes and the CPI, using a cited timeline of every major tariff action since 2018.
The same method is run on the 2018–19 trade war as a check against published studies.

- **Report:** <https://johnpospisil.github.io/tariff-pass-through/>
- **Product explorer** (search a product, see its tariffs, prices and suppliers):
  <https://johnpospisil.github.io/tariff-pass-through/explore.html>
- **Review packet** for economists: [reports/review/](reports/review/)

The site is rebuilt monthly after each Census trade release. Numbers below are for data through
August 2026; the report always shows the current "data as of" month.

## Findings

- **At the border, US buyers paid nearly all of the 2025–26 tariffs.** Pre-duty import prices
  barely moved when tariffs rose: β = +0.04 (SE 0.03), or −0.04 (0.01) with outliers trimmed, where
  0 means the duty was added in full to what importers paid and −1 means exporters cut prices by the
  full duty. That is the same result as 2018–19.
- **Section 232 metals and autos are the one place exporters gave a little** (β = −0.09).
- **In stores, prices of exposed goods rose by part of the duty cost, gradually:** about 0.3–0.65
  of it, measured against each item's own trend. These estimates are imprecise.
- **Tariffs collected were well below the rates on paper:** a 10.8% effective rate at the October
  2025 peak against 16.8% statutory, mainly because of USMCA claims, in-transit exemptions and
  metal-content bases.
- **Trade moved away from China:** its share of imports of the products tariffed in 2018–19 fell
  from 25.5% (2017) to 7.4% in the year to August 2026.
- **Importers stockpiled before each 2025 action**, about $71bn above trend, then cut back.

What we don't claim: no welfare conclusions, no verdict on the policy, no findings of evasion.

## Quick start

```bash
uv sync                    # Python 3.12 dependencies
make setup                 # also installs the headless browser for the explorer tests
cp .env.example .env       # optional: free Census and BLS API keys (raise rate limits)
make test                  # unit tests; data-dependent tests skip until data are built
make all                   # ingest -> build -> models -> figures -> report (several hours first time)
```

API keys (free, optional): Census <https://api.census.gov/data/key_signup.html>, BLS v2
<https://data.bls.gov/registrationEngine/>. Rendering the report needs
[Quarto](https://quarto.org) 1.10 or later.

Useful targets: `make ingest` (raw pulls, cached under `data/raw/`), `make reconcile` (FT-900 and
Treasury gates), `make build`, `make models`, `make figures`, `make report`, `make explorer`,
`make review`, `make refresh` (the monthly update: re-pull the last 24 months and rebuild).

## How it is kept current

[`.github/workflows/monthly_refresh.yml`](.github/workflows/monthly_refresh.yml) checks for a new
Census month four times a month. When one appears it restores a data snapshot, re-pulls the trailing
24 months (to pick up revisions), rebuilds everything, runs all tests (reconciliation gates and
pinned estimates), deploys the site and opens an issue if anything fails. A second workflow opens a
monthly checklist issue to re-verify the tariff actions. Details in [DATA.md](DATA.md), "Monthly
refresh and deploy".

## Layout

```
src/tpt/ingest/    download and parse sources (Census trade, BLS, BEA, Treasury)
src/tpt/build/     tariff timeline, rate panel, import panel, concordances, CPI exposure
src/tpt/models/    border pass-through, robustness, retail DiD, trade diversion
src/tpt/viz/       chart theme and figures
src/tpt/report/    report numbers, explorer bundle, review packet tables
src/tpt/ci/        monthly refresh helpers
data/reference/    hand-built, cited tables (committed), incl. tariff_actions.csv
data/published/    aggregates used by the report and explorer (committed)
report/            Quarto site: article (index.qmd) and product explorer (explore.qmd)
reports/           QA outputs and the review packet
tests/             unit tests, reconciliation gates, pinned estimates, browser tests
```

## Data and citations

All data are public US government sources (public domain), plus the Rauch classification via the
`concordance` R package (MIT). Every tariff rate, date and HS scope cites a Federal Register notice,
proclamation, executive order, USTR notice or CBP message. Sources, vintages, licences and known
issues: [DATA.md](DATA.md).

Please cite as: Pospisil, J. (2026). *At the Border and at the Store: Tariff Pass-Through in
2025–26.* <https://johnpospisil.github.io/tariff-pass-through/>

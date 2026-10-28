# Data

Every source, vintage, licence and known issue used in this project. Updated as each source is added.

## Sources

| Source | Used for | Access | Vintage / retrieved | Licence |
|---|---|---|---|---|
| Census International Trade API | HS10 × country × month imports, duties | api.census.gov | 2017-01 to 2026-08, retrieved 2026-10-27 (P03) | Public domain (US Gov) |
| FT-900 country file | Reconciliation of monthly totals | census.gov/foreign-trade/balance/country.xlsx | through 2026-08, retrieved 2026-10-27 (P04) | Public domain |
| Monthly Treasury Statement, table 4 | Reconciliation of customs duties | api.fiscaldata.treasury.gov | FY2017 to 2026-09, retrieved 2026-10-27 (P04) | Public domain |
| BLS Import Price Indexes (MXP) | Pre-duty import prices | api.bls.gov (data), download.bls.gov (catalog) | 2015-01 to 2026-09, retrieved 2026-10-28 (P05) | Public domain |
| BLS CPI / PPI | Consumer and producer prices | api.bls.gov (data), download.bls.gov (catalog) | 2015-01 to 2026-09, retrieved 2026-10-28 (P05) | Public domain |
| BEA input-output tables, PCE bridge | HS → CPI concordance | bea.gov | — (P06) | Public domain |
| Tariff actions | Tariff timeline | Federal Register, USTR, CBP CSMS | — (P08, P09) | Public domain |

## Tariff timeline

Built in `data/reference/tariff_actions.csv`. Every row cites an official source and the date it was
verified. Legal status (including the Supreme Court IEEPA case) is recorded here with the date checked.

## Census International Trade API (P03)

- Endpoint: `api.census.gov/data/timeseries/intltrade/imports/hs`, `COMM_LVL=HS10`.
- Variables: `GEN_VAL_MO` (general imports), `CON_VAL_MO` (imports for consumption, the base for
  duties), `DUT_VAL_MO` (dutiable value), `CAL_DUT_MO` (calculated duty), `CON_CHA_MO` (import charges),
  `GEN_QY1_MO`, `CON_QY1_MO`, `UNIT_QY1`, `CON_QY2_MO`, `UNIT_QY2`. Values in US dollars, customs basis.
- Requests: one per individual country × calendar year; a failed year is retried month by month.
  Commodity wildcards (`I_COMMODITY=85*`) were tested and are too slow or fail with HTTP 500.
- Country codes: `SUMMARY_LVL=DET` marks individual countries and `CGP` marks groupings (EU, OECD,
  USMCA, ...). The all-countries total, code `-`, is also `DET`; individual countries are `DET` and not
  `-`. See `data/reference/census_countries.csv`.
- Outputs: `data/interim/census_imports/year=YYYY/data.parquet`, `data/interim/census_totals.parquet`.

## BLS prices (P05)

Run `make ingest-bls` (about 45 API requests, under a minute). Catalogs are in
`data/reference/bls_{mxp,cpi,ppi}_series.csv`; data are long tables (series_id, month, value,
footnotes) in `data/interim/bls/`. All series start 2015-01, so 12-month changes exist from 2016.

- **Import price indexes (MXP)**, 998 series, not seasonally adjusted, measured before duties.
  Families: CO (by locality of origin: China, Canada, Mexico, EU, Japan, ASEAN, Taiwan, UK, ...; NAICS
  detail), IR (BEA end use), IP (HS), IZ (NAICS). Base periods differ by series; many detailed
  series were rebased or introduced in 2025.
- **CPI-U**, U.S. city average, monthly, 721 series: 386 NSA and 335 SA, display levels 0 (All
  items) to 8 (most detailed). Many detailed items are NSA only.
- **PPI commodity indexes**, 415 NSA series: goods groups 00–15 down to two digits, plus the
  final-demand tree (FD4...).
- Catalog files come from `download.bls.gov`, which returns 403 unless the User-Agent carries a
  contact email; it is read from `BLS_CONTACT_EMAIL` in `.env` and sent to bls.gov only.

## Reconciliation (P04)

Run `make reconcile`; reports and a chart are in `reports/qa/`.

**Gate 1: HS10 sums vs the FT-900 total** (`country.xlsx`, code 0015 "World, Not Seasonally
Adjusted", Census basis, $ millions). All 116 months within ±0.5%; exact to the dollar through
2025-12, and within ±0.07% for 2026 months. The 2026 differences are small and likely reflect a
different vintage of the preliminary 2026 data in the country file. The 15 largest partners also match
the file's country rows.

**Gate 2: calculated duties vs Treasury customs-duty receipts** (MTS table 4, "Customs Duties").
- Timing: duties are assessed at entry and paid on a monthly statement, so receipts lag one month.
  Month-to-month changes correlate 0.85 at lag 1 vs 0.61 at lag 0.
- Level: Census calculated duties are a stable ~87.5% of Treasury gross receipts (3-month ratio,
  2017–2024 median 0.875). The ~12% wedge is a coverage difference, not a data error; likely sources
  (not yet verified) are antidumping/countervailing duty deposits, informal and postal entries, and
  interest and penalties, which Treasury collects but Census does not count as calculated duty.
- The gate tests that the 3-month ratio stays within ±10% of the baseline. Result: all months pass;
  range -7.9% to +4.1%. The largest deviation is spring 2025, when assessed duties jumped ahead of
  receipts during the tariff increases.
- Net receipts are reported but not gated: refunds jump to $22bn (2026-05), $49bn (2026-06),
  $33bn (2026-07) and $10.5bn (2026-08), making net receipts negative. These are IEEPA tariff refunds
  (below).

## IEEPA ruling and refunds (status as of 2026-10-27; verify in P09)

From secondary sources (law-firm and trade-policy summaries; official CBP/Federal Register notices
to be checked in P09):
- The Supreme Court ruled on 2026-02-20 (6–3) that IEEPA does not authorize tariffs.
- The Court of International Trade ordered CBP on 2026-03-04 to liquidate unliquidated entries without
  IEEPA duties. CBP refunds run through its CAPE process in phases from 2026-04-20; about $166bn of
  IEEPA duties were collected or estimated on about 53 million entries.
- A replacement 10% surcharge under Section 122 was imposed, struck down by the Court of International
  Trade on 2026-05-07 (stayed on appeal), and expired on 2026-07-24.
- **Implication:** Census calculated duties record IEEPA duties as assessed at entry. Whether Census
  revises them after refunds is unknown (check in P09). Effective-rate and pass-through work must state
  whether it uses duties as assessed or net of refunds.

## Known issues

- **October 2025 (federal shutdown)**: BLS did not collect most October 2025 prices ("Data unavailable
  due to the 2025 lapse in appropriations"). CPI: only 21 of ~700 series have an October 2025 value;
  import prices: about 450 of ~980. PPI is complete. Month-to-month changes across October 2025
  need interpolation or exclusion; 12-month changes for October 2025 and October 2026 are affected.

- **All-zero rows**: about 40% of HS10 × country × month rows (2025) have zero value and quantity; the
  API returns rows for months without trade. Dropped when the import panel is built (P12).
- **Revisions**: data are as retrieved on the date above; Census revises prior months (annual revision
  each June). Re-pull with `--refresh` to update.

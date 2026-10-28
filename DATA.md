# Data

Every source, vintage, licence and known issue used in this project. Updated as each source is added.

## Sources

| Source | Used for | Access | Vintage / retrieved | Licence |
|---|---|---|---|---|
| Census International Trade API | HS10 × country × month imports, duties | api.census.gov | 2017-01 to 2026-08, retrieved 2026-10-27 (P03) | Public domain (US Gov) |
| FT-900 | Reconciliation of monthly totals | census.gov | — (P04) | Public domain |
| Monthly Treasury Statement | Reconciliation of customs duties | api.fiscaldata.treasury.gov | — (P04) | Public domain |
| BLS Import Price Indexes (MXP) | Pre-duty import prices | api.bls.gov | — (P05) | Public domain |
| BLS CPI / PPI | Consumer and producer prices | api.bls.gov | — (P05) | Public domain |
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

## Known issues

- **All-zero rows**: about 40% of HS10 × country × month rows (2025) have zero value and quantity; the
  API returns rows for months without trade. Dropped when the import panel is built (P12).
- **Revisions**: data are as retrieved on the date above; Census revises prior months (annual revision
  each June). Re-pull with `--refresh` to update.

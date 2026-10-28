# Data

Every source, vintage, licence and known issue used in this project. Updated as each source is added.

## Sources

| Source | Used for | Access | Vintage / retrieved | Licence |
|---|---|---|---|---|
| Census International Trade API | HS10 × country × month imports, duties | api.census.gov | — (P03) | Public domain (US Gov) |
| FT-900 | Reconciliation of monthly totals | census.gov | — (P04) | Public domain |
| Monthly Treasury Statement | Reconciliation of customs duties | api.fiscaldata.treasury.gov | — (P04) | Public domain |
| BLS Import Price Indexes (MXP) | Pre-duty import prices | api.bls.gov | — (P05) | Public domain |
| BLS CPI / PPI | Consumer and producer prices | api.bls.gov | — (P05) | Public domain |
| BEA input-output tables, PCE bridge | HS → CPI concordance | bea.gov | — (P06) | Public domain |
| Tariff actions | Tariff timeline | Federal Register, USTR, CBP CSMS | — (P08, P09) | Public domain |

## Tariff timeline

Built in `data/reference/tariff_actions.csv`. Every row cites an official source and the date it was
verified. Legal status (including the Supreme Court IEEPA case) is recorded here with the date checked.

## Known issues

To be filled in as found.

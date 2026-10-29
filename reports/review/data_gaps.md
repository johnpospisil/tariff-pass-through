# Known data gaps and limitations

Each item says what is affected and what we did about it. Details are in `DATA.md` (section
named in brackets).

## Prices

- **Unit values are not prices** [Import panel; Robustness grid]. Customs value ÷ quantity
  changes when the mix within an HS10 code changes. We compare within HS6 × month, winsorise at
  1/99, report the ARW ratio-3 trim alongside, and cross-check against BLS import price indexes by
  locality. 1/99 winsorising keeps composition jumps up to ±4.2 log points, which moves β by about
  0.2 in 2018–19 (+0.17 winsorised vs −0.06 trimmed).
- **Quantity units in the Census API are the current unit for every month** [Import panel].
  We take units from the annual HS10 lists instead. In 2018–19, 13.9% of import value had no
  quantity unit, so the price sample covers 77% of value then (91% in 2025–26).
- **October 2025 BLS gap** [Known issues]. The federal shutdown left 21 of about 700 CPI series
  and about 450 of 980 import price series without an October 2025 value. These are left missing;
  12-month changes for October 2025 and October 2026 are affected.

## Tariff rates

- **Statutory vs assessed** [Statutory vs collected duties]. Census records no duty on low-value
  estimate lines (9999.95), Chapter 98 provisions or USMCA-claimed entries. Section 232
  derivative duties fell on metal content only until 2026-04-06. In-transit exemptions delay each
  2025 increase by 1–2 months. At the variety level collected duties rise about 0.5 per unit of
  statutory change (Section 232: 0.38).
- **Scope we cannot identify in trade data** [Tariff timeline]. Section 232 duties on patented
  pharmaceuticals, advanced semiconductors and some drone classes apply to a subset of their HS
  codes; these rows (`value_basis = unidentified_subset`) are not applied to the whole code.
- **USMCA qualification** [Tariff rate panel]. Approximated with the share of each HS10 ×
  country's imports entered under the USMCA rate provision.
- **HS10 code changes** [Concordances]. Linked across years with Pierce–Schott families; changes
  across a split or merge use the family aggregate (1.1% of the price sample).

## Retail

- **Concordance** [CPI item tariff exposure]. Import shares come from the 2017 benchmark
  input-output tables; many CPI strata share one PCE bridge line and so get identical exposure
  (footwear, apparel by gender, cereals, bakery).
- **Pre-trends** [Retail pass-through]. High-exposure CPI goods were already falling relative to
  low-exposure goods before 2018 and before 2025. Estimates rely on item trends fitted on
  2023–24; without them the 2025–26 estimate is −0.76 (0.24).

## Trade flows

- **De minimis** [Front-running and de minimis]. Shipments under $800 were mostly absent from
  Census data before duty-free entry ended (May 2025 for China and Hong Kong, August 2025 for all
  countries). Part of the recorded rise in low-value imports is a measurement change.
- **Revisions** [Monthly refresh]. Census revises recent months (annual revision each June).
  Each refresh re-pulls a trailing 24-month window, so published numbers can move slightly.
- **Imports rose after the IEEPA ruling.** Monthly imports were about $250–260bn in early 2026 and
  $299–331bn from March to August 2026, matching the published FT-900 totals. The 2025–26 window
  includes these months; an estimate ending in February 2026 gives −0.001 (0.032).

## Money

- **Duties ≠ receipts** [Reconciliation]. Calculated duties are assessed at entry; Treasury
  customs receipts lag and are net of refunds. The 3-month ratio of gross receipts to
  calculated duties stays within 8% of its baseline in every month (largest gaps when rates jump:
  April–June 2018 and March–April 2025) and within 3% from May 2025 on.
- **Refunds** [Legal status]. IEEPA refunds ($126bn paid by 2026-10-02) are not netted out of
  duties. The Section 122 ruling is stayed on appeal; no Section 122 refunds have been paid.

## Not in scope

Welfare, wages, profits, exchange-rate effects, retaliation and US exports.

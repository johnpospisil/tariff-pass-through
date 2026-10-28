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
| BEA input-output tables (2017 detail), PCE bridge 2017 | HS → CPI concordance, import shares | apps.bea.gov | 2017 benchmark, retrieved 2026-10-28 (P06) | Public domain |
| Census HS10 import code lists | HS10 → NAICS, SITC, end use; code families | census.gov (impconcordYY, sbsdf.zip) | 2017–2026, retrieved 2026-10-28 (P06) | Public domain |
| Census NAICS concordances 2012→2017, 2022→2017 | NAICS → BEA commodity | census.gov/naics/concordances | retrieved 2026-10-28 (P06) | Public domain |
| Rauch (1999) classification; HS→SITC2 tables | Differentiated vs homogeneous goods | R `concordance` package (GitHub insongkim/concordance) | v2.1.0, retrieved 2026-10-28 (P06) | MIT |
| BLS CPI ELI → PCE mapping | CPI ↔ PCE crosswalk | bls.gov/cpi/additional-resources/pce-cpi-code-mapping.htm | 2011 vintage, retrieved 2026-10-28 (P06) | Public domain |
| Tariff actions | Tariff timeline | Federal Register API; HTSUS Chapter 99 (hts.usitc.gov, 2020/2021/2025 Basic Editions) | 2018–2024 actions verified 2026-10-28 (P08); 2025–26 in P09 | Public domain |

## Tariff timeline

Built in `data/reference/tariff_actions.csv` (schema and validator in
`src/tpt/build/tariff_timeline.py`; check with `make timeline-validate`). Every row cites an official
source and the date it was verified. Legal status (including the Supreme Court IEEPA case) is
recorded here with the date checked.

- **One row per action component**: an authority applying a rate to a set of HS codes from a set of
  countries over a date range. `effective_date` is the first day goods entered for consumption are
  subject; `end_date` is the first day they are not (exclusive; empty = in effect).
- **Products**: `hs_scope` lists product HS prefixes (2–10 digits) or `file:hs_lists/<name>.csv`
  for annexes; `hs_exclude` carves out exemptions. The HTSUS Chapter 99 heading that carries the
  duty (e.g. 9903.88.03) goes in `ch99_heading`; it never appears in import statistics.
- **Countries**: Census `cty_code` and ISO `country_iso`, `ALL` (with `exclude_cty_codes`), or a
  group defined in `data/reference/country_groups.csv`.
- **Stacking**: `cumulative`, or `not_with:<authorities or action groups>` when the rate does not
  apply to goods subject to them (e.g. reciprocal tariffs not on Section 232 goods; metals duties not
  on goods under the autos duty), optionally `;also_with:<groups>` for two action groups of the same
  authority that knowingly stack (steel and aluminum derivative duties on one product).
- **Rate types** (P09): `ad_valorem`, `specific`, and `all_in_floor`, where the additional duty
  tops the MFN rate up to `rate` (max(0, rate − MFN); the EU, Japan, Korea and Switzerland "15%
  all-in" deals). **`value_basis`**: full value (default), `metal_content` (Section 232 metals
  before 2026-04-06, copper), or `unidentified_subset` (duty applies to a subset of the HS scope
  that trade data cannot identify: patented drugs, advanced chips, drone classes; P10 reports
  these separately). **`usmca`**: `exempt` or `non_us_content` for USMCA-qualifying goods.
- **Citations**: `source_type`, `source_citation`, an https `source_url` on an official domain
  (federalregister.gov, whitehouse.gov, ustr.gov, cbp.gov, usitc.gov, courts, ...), `verified_on`.
- **Validation**: required fields and enums, dates, decimals (no % signs), official URLs,
  Census country codes, every HS token (including list files) matching at least one HS10 code in the
  2017–present Census lists, unique ids, and no overlapping rows (same authority, countries, HS
  scope and dates) unless linked by `supersedes`.

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

## Concordances (P06)

Run `make ingest-reference concordance`. Outputs in `data/processed/`: `hs10_families.parquet`,
`hs10_attributes.parquet` (year × HS10: descriptions, units, SITC, end use, NAICS, BEA commodity,
Rauch class, family), `cpi_pce_crosswalk.parquet`; coverage in `reports/qa/concordance_coverage.csv`.

**HS10 families.** Pierce & Schott's published concordance ends in 2007, and Census publishes no
machine-readable code-change list for 2017+, so codes are linked by prefix in the same spirit (details
in `src/tpt/build/concordance.py`): a dropped code links to added codes in the same HS8, else HS6,
else HS4; merges and carve-outs link to continuing codes in the same HS8. Result: 22,040 codes →
17,879 families; 507 multi-code families hold 27.7% of import value (largest: 155 codes in HS 4403,
wood, restructured in HS 2022; apparel in chapters 61–62 and medicaments in 3004 are similar). 9.7%
of value sits in families spanning more than one HS6. **Recommendation for P12:** compute 12-month
changes at the HS10 level when the code exists in both months and fall back to the family only when
the code changed, so families do not blur detail they do not need to.

**HS10 → NAICS → BEA commodity.** NAICS from Census's annual lists (latest available year as fallback).
BEA's 2017 detail tables cite 2017 NAICS, while Census lists carry 2022 NAICS from 2022 (e.g. cars,
336110) and some 2012 codes before; these go through Census's 2022→2017 and 2012→2017 concordances.
Census special codes are hand-mapped in `data/reference/census_special_naics_to_bea.csv`: 910000
(waste and scrap) → BEA S00401 Scrap; 930000 (used, rebuilt and antique goods) → S00402 Used and
secondhand goods. 980000 (US goods returned) and 990000 (special provisions) have no BEA commodity.

**Rauch.** HS6 → SITC Rev. 2 (HS 2017 tables for 2017–2021, HS 2022 tables from 2022) → Rauch
conservative and liberal classes (w organized exchange, r reference priced, n differentiated);
modal class when an HS6 maps to several SITC codes, flagged `rauch_mixed`. Fallbacks, recorded in
`rauch_source`: the other HS revision's table, then the modal class of the HS4 (3.5% of value).

**Coverage by import value, 2017–2026** (regular goods, excluding HS chapters 98–99 / all goods):
family 100% / 100%; NAICS 99.99% / 99.99%; BEA commodity 99.88% / 95.8%; Rauch 96.2% / 93.0%.

**CPI ↔ PCE.** The BLS mapping lists 2011-vintage ELIs. ELI → current CPI series code is "SE" + its
first four characters (e.g. AA011 → SEAA01, Men's suits, sport coats, and outerwear); where that
strata no longer exists, its expenditure class ("SE" + first two, e.g. SEAB Boys' apparel). 309 of
315 ELIs map. PCE series → BEA bridge line by normalised description; nine renamed goods lines are
hand-mapped in `data/reference/pce_series_to_bridge_line.csv` (e.g. personal computers → line 49,
prescription and nonprescription drugs → line 122 Pharmaceutical products). 156 of 167 PCE series map;
the 11 unmapped are services (hospitals, higher education, owner-occupied housing, ...).

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

## 2018–19 tariff actions (P08)

47 rows in `tariff_actions.csv`, every one checked against the Federal Register (API at
federalregister.gov) for citation, publication and effective date. Products come from the HTSUS
Chapter 99 notes that implement each action (see `data/reference/hs_lists/README.md`); the Federal
Register annexes are images. Country groups (EU28, EU27, Section 201 exempt lists) are in
`data/reference/country_groups.csv`.

| Action | Rows | Key dates and rates |
|---|---|---|
| Section 301 China List 1 / 2 | 2 | 25% from 2018-07-06 / 2018-08-23 |
| List 3 | 2 | 10% from 2018-09-24; 25% from 2019-05-10 |
| List 4A | 2 | 15% from 2019-09-01; 7.5% from 2020-02-14 (List 4B never took effect) |
| Section 232 steel (25%) | 7 | 2018-03-23; country exemptions change 2018-06-01, 2019-05-20, 2022-01-01 (EU), 2022-04-01 (JP), 2022-06-01 (UK, UA); Turkey 50% 2018-08-13 to 2019-05-21 |
| Section 232 aluminum (10%) | 8 | 2018-03-23; 2018-05-01, 2018-06-01, 2019-05-20, 2022-01-01, 2022-06-01; Canada unwrought 2020-08-16 to 09-01; Russia 200% from 2023-03-10 |
| Section 232 derivatives | 8 | 25% steel / 10% aluminum derivatives from 2020-02-08, exemptions following the base articles; Russia 200% |
| Section 201 washers and parts | 10 | 2018-02-07 to 2023-02-08, yearly steps |
| Section 201 solar modules | 8 | 30% (2018) stepping down to 14% (2025-02-07 to 2026-02-07) |

**Modelling choices** (all also in row notes):
- Quota and tariff-rate-quota countries under Section 232 (AR, BR, KR quotas; EU, JP, UK TRQs) are
  treated as exempt; over-quota trade is not modelled.
- Product exclusions (Section 301 and 232) are not modelled.
- Washers use the in-quota rate (20% → 14%) as a lower bound; over-quota rates (50% → 30%) are in
  the notes. Washer parts use the over-quota rate. Solar cells (large duty-free TRQ) are not modelled;
  bifacial-panel exclusions (2019–2024) are noted but not observable. P11 checks all of this
  against duties collected.
- Origin rules that trade data cannot observe (Mexico melt-and-pour, Russian smelt/cast) are noted only.
- The 2024 Section 301 four-year-review increases and all 2025 changes are added in P09.

**Cross-check against Fajgelbaum et al. (2020, QJE).** Actions in force on 2018-12-31 cover 11,860
HS10 lines of the 2017 schedule (paper: 12,043 products, 98.5%). Covered 2017 import value is
$258bn, 11.0% of imports (paper: $303bn, 12.7%). By list, at 2017 values: List 1 $32bn (USTR $34bn),
List 2 $14bn ($16bn), List 3 $166bn ($200bn), List 4A $103bn (~$112bn); at 2018 values List 3 is
$187bn. Product scope matches; the value gap reflects the base period and valuation of the
published figures, and is revisited in P11 against duties actually collected. The replication package
itself was not openly downloadable.

## Legal status of the 2025–26 tariffs (P09; checked 2026-10-28)

Rows are built from the orders in the Federal Register (FR API, document numbers in
`source_url`). Court and refund facts are from the sources named; re-check before publication
(P25).

- **IEEPA tariffs struck down.** *Learning Resources, Inc. v. Trump* (S. Ct., decided
  2026-02-20) held that IEEPA does not authorize tariffs. EO 14389 (91 FR 9437) ended the IEEPA
  duties (fentanyl: Canada, Mexico, China; reciprocal; Brazil); CBP stopped collecting them at
  12:00 a.m. ET on **2026-02-24**. The India Russian-oil duty had already ended 2026-02-07
  (EO 14384, 91 FR 6501). All IEEPA rows have `legal_status = struck_down` and end 2026-02-24 or
  earlier.
- **Refunds.** The Court of International Trade (*Atmus Filtration*) ordered refunds to all
  importers of record of IEEPA duties (about $165bn); CBP pays them through its CAPE process
  (phased from 2026-04). Refunds show in Treasury customs receipts from 2026-05 (P04). Litigation
  over interest and liquidated entries (*Nintendo of America v. Treasury*, CIT) is pending. Sources:
  [CRS LSB11398](https://www.congress.gov/crs-product/LSB11398),
  [Skadden 2026-03](https://www.skadden.com/insights/publications/2026/03/tariff-refund-mechanism-takes-shape).
- **Census calculated duties are as assessed, not net of refunds.** Checked in the 2026-10 pull:
  the implied duty rate on imports from China is 38–48% in 2025-04 to 2025-10 and 30–32% in
  2025-11 to 2026-01, and falls to about 22% after 2026-02-24. Pass-through work uses the duty as
  assessed (the price buyers faced at entry); refunds are a later transfer to importers.
- **Section 122 bridge, expired.** Proclamation 11012 (91 FR 9339) imposed a 10% surcharge
  (announced increase to 15% never implemented) from 2026-02-24 for 150 days; it expired at the
  close of 2026-07-23. The CIT held it unlawful in 2026-05; the ruling is stayed on appeal and no
  refunds have been made.
- **Replacement authorities in force.** Section 301 forced-labor actions on 60 economies (10% or
  12.5%, some net of MFN) from 2026-07-24 (USTR, 91 FR 47318); Section 301 Brazil 25% from
  2026-07-22 (91 FR 45619); Section 338 duties of 50% on listed Canadian products from 2026-08-22
  (Proclamations 11046–11048, 11056, 11064–11065); Section 232 actions throughout (below).
  Open Section 301 investigations (structural excess capacity, Vietnam IP, Germany pharmaceuticals,
  China Phase One) have no tariffs yet.
- **De minimis.** Duty-free de minimis ended for China/Hong Kong on 2025-05-02 (EO 14256), for all
  countries on 2025-08-29 (EO 14324), and was continued after the ruling by EO 14388 (91 FR 9433;
  corrected 91 FR 17839). Recorded as rate-0 `DE_MINIMIS` event rows.

## 2025–26 tariff actions (P09)

`tariff_actions.csv` has 300 rows: 47 for 2018–19 (P08, four of them now closed on 2025-03-12)
and 253 for 2024–26, written by `make timeline-2025` (`src/tpt/build/actions_2025.py`). Product
lists come from the HTSUS Chapter 99 notes (`make hs-lists`, `hs_lists_2025.py`): the IEEPA notes
as they stood just before the ruling (2026 HTS Revision 3), the pre-2025-11-13 Annex II and Brazil
lists (2025 Revision 28), and the current Section 232/301/338 notes (2026 Revision 21). Country
rate schedules are parsed from the HTSUS heading tables (9903.02.02–.71 reciprocal,
9903.05.21–.84 forced labor). Import value in scope is for 2024 imports for consumption (scope
only, before rates, exclusions within a scope file and USMCA).

| Action | Authority | Countries | Rate | In force | Products (2024 imports in scope) |
|---|---|---|---|---|---|
| Section 301 four-year review (89 FR 76581) | S301 | China | 25/50/100% | 2024-09-27, 2025-01-01, 2026-01-01 steps | EVs, batteries, semis, solar, minerals, medical ($20bn) |
| Fentanyl, China & HK (EO 14195, 14228, 14357) | IEEPA | CN, HK | 10% → 20% → 10% | 2025-02-04 / 03-04 / 11-10 → 2026-02-24 | all ($431bn) |
| Fentanyl, Canada (EO 14193, 14197, 14231, 14325) | IEEPA | CA | 25% → 35%; energy, potash 10% | 2025-03-04 / 08-01 → 2026-02-24 | all; USMCA goods exempt from 2025-03-07 |
| Fentanyl, Mexico (EO 14194, 14198, 14232) | IEEPA | MX | 25%; potash 10% | 2025-03-04 → 2026-02-24 | all; USMCA goods exempt from 2025-03-07 |
| Reciprocal baseline (EO 14257, 14266) | IEEPA | all but CA, MX | 10% | 2025-04-05 → 2026-02-24 | all less Annex II and S232 goods ($1,595bn) |
| China reciprocal escalation (EO 14259, 14266, 14298) | IEEPA | CN, HK, MO | 84%, 125%, then 10% | 2025-04-09, 04-10, 05-14 | all less Annex II |
| Country rates (EO 14326) | IEEPA | 66 partners | 10–41% | 2025-08-07 → 2026-02-24 | e.g. Vietnam 20% ($97bn), India 25%, Switzerland 39% |
| 15% all-in deals (EO 14345; 90 FR 44638, 46136, 55964, 59281) | IEEPA | EU, JP, KR, CH, LI | max(0, 15% − MFN) | EU, JP 2025-08-07; KR, CH, LI 2025-11-14 | EU ($331bn), Japan ($112bn) |
| Agricultural exemptions (EO 14360, 14361) | IEEPA | all; Brazil | 0% | 2025-11-13 | beef, coffee, fruit and others ($69bn) |
| Brazil (EO 14323, 14361) | IEEPA | BR | 40% | 2025-08-06 → 2026-02-24 | all less 129 exempt lines (367 from 2025-11-13) |
| India Russian oil (EO 14329, 14384) | IEEPA | IN | 25% | 2025-08-27 → 2026-02-07 | all less Annex II |
| Steel, aluminum (Procl. 10895, 10896, 10947) | S232 | all; UK 25% | 25% → 50% | 2025-03-12 / 06-04 → 2026-04-06 | steel $31bn, aluminum $18bn |
| Metal derivatives incl. inclusions (90 FR 40326) | S232 | all; UK 25% | 25% → 50% on metal content | 2025-03-12 / 06-23 / 08-18 → 2026-04-06 | steel $230bn, aluminum $155bn (overlapping) |
| Copper (Procl. 10962) | S232 | all | 50% on copper content | 2025-08-01 → 2026-04-06 | $15bn |
| Metals regime on full value (Procl. 11021, 11032) | S232 | all; UK, deal partners lower | 50% / 25% / 15% all-in | 2026-04-06 (deal floors 2026-06-08) | $93bn / $171bn / $61bn |
| Autos and parts (Procl. 10908; EO 14309; deal notices) | S232 | all; UK 10%, EU/JP/KR 15% all-in, TW parts 15% | 25% | vehicles 2025-04-03, parts 2025-05-03 | vehicles $116bn + deals; parts $288bn |
| Medium/heavy trucks, buses (Procl. 10984) | S232 | all | 25%; buses 10% | 2025-11-01 | trucks $23bn, parts $143bn |
| Timber, lumber, furniture (Procl. 10976, 11000) | S232 | all; UK 10%, EU/JP 15% all-in | 10% / 25% (30%, 50% from 2027-01-01) | 2025-10-14 | $17bn |
| Semiconductors (Procl. 11002) | S232 | all | 25% (subset) | 2026-01-15 | advanced chips only; HS scope $124bn |
| Pharmaceuticals (Procl. 11020) | S232 | all; deal partners 15%, UK 0 | 100% (patented subset) | 2026-09-29 | HS scope $27bn |
| Drones (Procl. 11055) | S232 | all | 25–100% (subset) | 2026-09-03 | small |
| Section 122 surcharge (Procl. 11012) | S122 | all | 10% | 2026-02-24 → 2026-07-24 | all less Annex, S232, USMCA ($1,856bn) |
| Brazil (91 FR 45619) | S301 | BR | 25% | 2026-07-22 | all less Annex I/II ($19bn) |
| Forced labor, 60 economies (91 FR 47318) | S301 | 60 | 10% or 12.5% (EU, TW, JP, KR, CH net of MFN) | 2026-07-24 | all less exemptions (China $254bn, EU $323bn) |
| Canada discrimination (Procl. 11046–48, 11064–65) | S338 | CA | 50% | 2026-08-22 | three lists ($21bn) |
| De minimis suspension (EO 14256, 14324, 14388) | DE_MINIMIS | CN/HK, then all | event | 2025-05-02, 2025-08-29, 2026-02-24 | low-value shipments |

Not encoded (no ad valorem duty, company-specific, or not yet in force): Section 232 critical
minerals (Procl. 11001), commercial aircraft (11040) and wind turbines (11074) are negotiations;
polysilicon minimum import prices from 2026-12-04 (11052); half-rate aluminum for approved onshoring
plans (11045); Canadian import bans (11061–11063); the 2026-10-30 Section 338 list change (not yet
in the HTSUS); the Section 301 ships and cranes fees and Nicaragua action; the one-day
2025-04-09 country rates (suspended 2025-04-10); transshipment penalty rates (40%).

**Stacking (as stated in the orders and HTSUS notes).** Reciprocal, Brazil, India, Section 122,
Section 301 Brazil and forced-labor duties do not apply to goods under Section 232 duties. Canada
and Mexico fentanyl duties do not apply to Section 232 goods (EO 14289; note 2 and the 232
notes). Metals duties do not apply to goods under the autos, trucks or semiconductor duties; auto
parts duties not to semiconductors or drones. Steel, aluminum and copper derivative duties stack
on each other (2025, metal content); from 2026-04-06 the metals headings are mutually exclusive.
China's Section 301 duties stack with IEEPA, Section 122 and forced-labor duties; the four-year
review rates are modelled as replacing the 2018–19 list rates where products overlap (to check
in P11). Section 338 list 2 is not applied to Section 232 goods; lists 1 and 3 are.

**Approximations to check in P11.** Canada "energy" = HS chapter 27; potash = 3104.20/.30/.90.
Annex II changes in 2025-09 (EO 14346) are not dated separately. Product exclusions, quotas (UK
autos, Section 201), the 20% US-content reciprocal exemption, import adjustment offsets, the 15%
metal-weight threshold after 2026-04-06, and country-specific Section 301 exemptions for framework
partners are not modelled. The Section 338 lists are as of 2026-09-15 for the whole period.
Brazil's 9903.01.81 list before 2025-11-13 is from 2025 HTS Rev 28 and may include additions made
between 2025-08-06 and 2025-11-10.

## Tariff rate panel (P10)

`make rates` → `data/processed/tariff_rates.parquet` (18,440,016 rows: every HS10 × individual
country × month with imports, 2017-01 to 2026-08). Columns: `rate_<authority>` (S232, S301,
S201, S122, S338, IEEPA fentanyl, reciprocal, other), `rate_total` (their sum), `rate_metal_content`
(part of `rate_s232` that legally applies to metal content only), `rate_unidentified` (duties on
subsets trade data cannot identify; **not** in `rate_total`), `mfn_rate`, `usmca_share`.
Monthly rates are day-weighted averages of daily rates (`src/tpt/build/tariff_rates.py`).

Rules (hand-worked cases in `tests/test_tariff_rates.py`):
- **Coverage**: hs_scope less hs_exclude on HS prefixes; list files extended to HS10 codes that
  replaced listed codes (P06 families: a code absent from the list's vintage year is added when
  every vintage-year member of its family is listed; adds 584 codes to List 3, 185 to List 1,
  144 to List 4A).
- **Supersedes** (transitive) removes the replaced row while both are in force; **not_with**
  removes a row when another in-force row has the named authority or action group
  (`unidentified_subset` rows never trigger exclusions). DE_MINIMIS rows carry no rate.
- **All-in floors**: max(0, floor − MFN). **MFN** (`make mfn`, `data/processed/mfn_rates.parquet`):
  general rate from the current HTSUS export (hts.usitc.gov `reststop/exportList`), ad valorem
  equivalents for specific/compound rates from 2024 duties on EU27/UK/Swiss/Norwegian imports;
  1.2% of 2025 import value has no MFN source (set to 0).
- **USMCA** (Canada, Mexico): `exempt` and `non_us_content` rows scale by (1 − s); s = share of the HS10 × month import value under Census rate provisions 18
  (free, special program) and 19 (free, Chapter 99 USMCA exemption), from `make usmca-share`
  (`data/processed/usmca_share.parquet`, Census API `RP`, 2025-01 to 2026-08). Aggregate s: Canada
  34% (2025-01/02) → 72% (2025-03) → 76–78%; Mexico 73–78%. Contemporaneous (after importers
  responded by claiming USMCA). For vehicles, the US content is entered as a separate duty-free
  line (code 19), so s already measures it; P10's extra 30% US-content assumption was dropped
  in P11 (see "Statutory vs collected duties").
- **Use-restricted lists** (found in P10): the auto and truck parts lists name general headings
  (e.g. all of 8471, computers, $139bn in 2024) but the duty applies to parts *of vehicles*; lines
  whose HTSUS description does not tie them to vehicles are separate `-GEN` rows with
  `unidentified_subset`. Civil aircraft exemptions name ~540 provisions (batteries, fasteners,
  electronics) but exempt only goods certified for civil aircraft; only ~120 lines identifiable as
  aircraft goods are treated as exempt. See `hs_lists/README.md`.

**Import-weighted statutory additional duty** (weights: same-month imports for consumption;
`reports/qa/statutory_rate_by_month.csv`), with the Census implied total duty rate
(calculated duties ÷ imports for consumption, which includes MFN):

| Month | Statutory additional | of which S232 (metal-content part) | S301 | IEEPA (fent./recip./other) | S122 | Unidentified (not in total) | Implied total |
|---|---|---|---|---|---|---|---|
| 2018-12 | 1.53% | 0.27% | 1.22% | — | — | — | 2.62% |
| 2019-07 | 1.80% | 0.15% | 1.58% | — | — | — | 2.84% |
| 2024-07 | 1.45% | 0.07% | 1.33% | — | — | — | 2.48% |
| 2025-04 | 15.31% | 1.75% (0.39%) | 1.10% | 2.70 / 9.73 / 0 | — | 0 | 7.18% |
| 2025-09 | 15.74% | 7.43% (5.47%) | 0.80% | 2.38 / 4.67 / 0.45 | — | 1.20% | 10.53% |
| 2026-01 | 14.61% | 7.53% (5.52%) | 0.96% | 1.53 / 4.25 / 0.35 | — | 3.48% | 9.87% |
| 2026-03 | 11.22% | 7.58% (5.49%) | 0.81% | — | 2.83% | 5.13% | 6.85% |
| 2026-05 | 7.48% | 3.71% | 0.85% | — | 2.92% | 4.86% | 6.89% |
| 2026-08 | 7.75% | 3.57% | 4.08% | — | — | 5.07% | 6.87% |

(Updated in P11 after the timeline fixes below.) The comparison with duties actually assessed is
in the next section.

## Statutory vs collected duties (P11)

`make validate-rates` (`src/tpt/build/validate_rates.py`) → `reports/qa/rate_validation_*.csv`;
gate in `tests/test_rate_validation_gate.py`. For each HS10 × country × month the **implied
additional rate** is (Census calculated duties − MFN rate × MFN base) ÷ consumption value. The MFN
base is dutiable value, capped at the pair's dutiable share in a reference year (2017 for
2018–24, 2024 for 2025–26) because a Chapter 99 duty makes FTA/USMCA goods "dutiable" without
MFN being paid (USMCA pickups: 25% MFN, not paid). Check: in 2017, MFN × dutiable value is 1.38%
of value against 1.40% calculated duties. Census calculated duties are as assessed at entry:
no refunds or drawback (those are in Treasury receipts, P04).

**Fit, pair-month level** (comparable pairs; `rate_validation_metrics.csv`):

| Period | Pair-months | Import value | Correlation (unweighted / value-weighted) | Value with \|stat − implied\| > 5 pp | Statutory | Implied |
|---|---|---|---|---|---|---|
| 2018-07 to 2019-12 | 2.71m | $3.63tn | 0.84 / 0.90 | 2.9% | 1.58% | 1.21% |
| 2020–24 | 9.38m | $14.04tn | 0.85 / 0.92 | 2.5% | 1.77% | 1.49% |
| 2025-02 to 2026-08 | 3.21m | $5.19tn | 0.75 / 0.78 | 16.3% | 10.49% | 7.13% |

**Bridge** (`rate_validation_bridge.csv`): every pair-month is assigned one line (first match);
lines sum to the gap. Percentage points of import value:

| Month | Statutory | Implied | Gap | Not compar. | Metal content | In transit | USMCA | S301 China excl. | Medical | Aircraft | Precious metals | S201 | Residual |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2019-07 | 1.80 | 1.41 | 0.38 | 0 | — | — | — | 0.33 | — | — | — | 0.04 | 0.02 |
| 2024-07 | 1.45 | 1.29 | 0.16 | 0 | — | — | — | 0.16 | — | — | — | 0.04 | −0.04 |
| 2025-02 | 2.26 | 1.30 | 0.96 | 0.03 | 0 | 0.92 | −0.01 | 0 | 0 | 0 | 0 | 0.02 | 0 |
| 2025-04 | 15.32 | 6.01 | 9.30 | 1.02 | 0.10 | 8.22 | 0 | 0 | 0 | 0 | 0 | 0 | −0.03 |
| 2025-07 | 10.67 | 8.38 | 2.29 | 0.70 | 0.51 | 0 | 0.27 | 0.22 | 0.08 | 0.04 | 0.02 | 0.01 | 0.42 |
| 2025-09 | 15.74 | 9.52 | 6.22 | 1.05 | 3.72 | 1.07 | 0.13 | 0.12 | 0.02 | 0.02 | 0 | 0 | 0.09 |
| 2026-01 | 14.61 | 8.84 | 5.77 | 1.07 | 3.86 | 0 | 0.26 | 0.12 | 0.12 | 0.09 | 0.01 | 0 | 0.24 |
| 2026-03 | 11.22 | 5.84 | 5.38 | 0.46 | 4.21 | 0 | 0.17 | 0.09 | 0.08 | 0 | 0.02 | 0 | 0.36 |
| 2026-08 | 7.75 | 5.88 | 1.87 | 0.46 | 0 | 0 | 0.65 | 0.21 | 0.08 | 0 | 0.13 | 0 | 0.36 |

The lines, and the evidence for each:
- **Not comparable** (excluded from the fit metrics): Census estimates of low-value shipments
  (9999.95, no duty recorded), Chapter 98 lines (US goods returned 9801, agricultural machinery
  9817; Census records no duty on them), and Canadian/Mexican pipeline gas (2711.21) and
  electricity (2716), entered under rate provision 10 (free) with no duty even in 2025-04, when
  the 10% energy duty applied.
- **Metal content**: Section 232 steel/aluminum/copper derivative duties apply to the metal
  content only; the panel applies them to full value (`rate_metal_content`). Ends with the
  2026-04-06 full-value regime. Includes USMCA-claimed derivatives (code 19), which carry no duty.
- **In transit**: goods loaded before the effective date entered at the old rate: EO 14195
  §2 (China fentanyl, loaded before 2025-02-01; 90 FR 9121), EO 14257 §2–3 (reciprocal, loaded
  before 2025-04-05 / 04-09; 90 FR 15041), EO 14326 (country rates, loaded before 2025-08-07 and
  entered before 2025-10-05; 90 FR 37963, HTSUS 9903.02.01). Assigned to pair-months in
  2025-02/03, 04/05 and 08/09 whose rate rose that month or the month before.
- **USMCA**: Census rate-provision detail shows code-19 (USMCA-claimed) entries carry no duty,
  including Section 232 metals duties after 2026-04-06, while the panel applies those to
  non-auto goods at full rate; code-69 USMCA vehicles pay on non-US content (e.g. Mexican cars
  8703.23.0140, 2025-09: 14% of value under code 19 at 0, 86% under code 69 at 25.1%).
- **S301 China exclusions**: USTR product exclusions (2018–20, and the 178/164 extended into
  2025–26) are described by product, not HS10, and are not modelled. Largest: computer parts
  8473.30.1180, vacuums 8508.11, vinyl tile 3918.10, motorcycles 8711.60.
- **S201**: solar-cell tariff-rate quota (2.5–5 GW duty-free) and the bifacial-module exclusion.
- **Medical, aircraft, precious metals** (2025–26 only): implied ≈ 0 against 11–13% (medical
  devices 9018–9022: Nairobi Protocol 9817.00.92–.96, use-based), 5.7% (civil aircraft and
  engines; deal exemptions and certification-based exemptions beyond the ~120 lines treated as
  exempt) and 3.1% (gold, platinum; bullion added to Annex II by EO 14346 in 2025-09 and
  exempt from Section 122/forced-labor duties), none identifiable by HS10.
- **Residual** (gate: ≤ 0.6 pp of value every month; max 0.56 pp, 2025-07 to 2026-08):
  Section 232 product exclusions and temporary imports under bond (steel lines with statutory 50%
  and implied 0), undated Annex II changes, classification, undervaluation.

**Top 30 discrepancies** (2025-01 to 2026-08, by absolute duty gap: `rate_validation_top30_2025.csv`;
2018–24: `rate_validation_top30_2018.csv`): 15 metal content (Mexican/Canadian auto body parts
8708.29.5160 and 8708.99.8180, beer 2203 in aluminum cans, cables 8544.42, refrigerators 8418.10,
European perfume 3303), 13 not comparable (low-value estimates, Ch. 98, Canadian natural gas),
1 in transit (Chinese lithium-ion batteries 8507.60.0020, 2025-04/05) and 1 USMCA (Mexican pickups
8704.31.0140). None is an unexplained timeline error.

**Timeline errors found and fixed in P11** (implied > statutory or statutory ≫ implied with a
legal cause):
1. Section 301 List 3 / 4A partial products dropped by the parser where the PDF text breaks
   "provided\nfor in": 8517.62.00 (routers, modems; $10–20bn/yr from China) is List 3 except
   .0090 (note 20(g)) and List 4A except .0010/.0020 (note 20(s)(ii)). After the fix, 2023
   statutory 25.0% vs implied 24.9% (.0020) and 7.5% vs 7.3% (.0090).
2. HS2022 renumbering: codes created after 2020 (e.g. 8543.40 e-cigarettes, List 2) were missing
   from the 2020-edition lists; added from note 20 of 2026 HTS Rev 21 (679 codes), only where no
   line of the code existed by 2020.
3. 50 U.S.C. 1702(b) informational materials (publications 4901–4905, artworks 9701–9703)
   excluded from all IEEPA rows (EO 14193 §2(j), EO 14194 §2(i), EO 14195 §2(i), EO 14257
   §3(b)(i)).
4. USMCA vehicles: the 30% US-content assumption double-counted; US content is in the code-19
   share (above).

**Cross-check with published estimates** (checked 2026-10-28):
- Penn Wharton Budget Model, [Effective Tariff Rates and Revenues, 2026-10-14](https://budgetmodel.wharton.upenn.edu/p/2026-10-14-effective-tariff-rates-and-revenues-updated-october-14-2026/)
  (customs duties ÷ import value, USITC DataWeb): 2.3% (2025-01), 6.7% (2026-07), 7.1% (2026-08).
  Ours (Census calculated duties ÷ consumption value): 2.22%, 6.45%, 6.87%, about 0.25 pp lower
  throughout (denominator: consumption value includes low-value estimates with no duty). PWBM's
  China rate, 24.3% (2026-08), and the USMCA-claimed share, 81.4% (2026-08), compare with our China
  implied additional rate of about 20% plus MFN (about 3%), and our 76–81% USMCA shares.
- Yale Budget Lab, [The State of U.S. Tariffs, 2026-07-24](https://budgetlab.yale.edu/research/state-us-tariffs):
  average statutory rate 11.1% (including MFN, pre-substitution weights). Ours on 2024 import
  weights for 2026-08: 10.3% additional + 2.4% (2024 duty rate) = 12.7%. The 1.6 pp difference is
  close to our documented statutory overstatement for 2026-08 (not comparable 0.46, USMCA 0.65,
  S301 exclusions 0.21, medical 0.08, residual 0.36 = 1.8 pp on current weights).

**For the models**: use `rate_total` as the statutory measure, but drop not-comparable lines
(9999, Ch. 98) from product panels, treat 2025-02 to 2025-05 and 2025-08/09 as in-transit months,
and use the implied rate as the alternative measure (P16).

## Known issues

- **October 2025 (federal shutdown)**: BLS did not collect most October 2025 prices ("Data unavailable
  due to the 2025 lapse in appropriations"). CPI: only 21 of ~700 series have an October 2025 value;
  import prices: about 450 of ~980. PPI is complete. Month-to-month changes across October 2025
  need interpolation or exclusion; 12-month changes for October 2025 and October 2026 are affected.

- **All-zero rows**: about 40% of HS10 × country × month rows (2025) have zero value and quantity; the
  API returns rows for months without trade. Dropped when the import panel is built (P12).
- **Revisions**: data are as retrieved on the date above; Census revises prior months (annual revision
  each June). Re-pull with `--refresh` to update.

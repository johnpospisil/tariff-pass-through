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

## Known issues

- **October 2025 (federal shutdown)**: BLS did not collect most October 2025 prices ("Data unavailable
  due to the 2025 lapse in appropriations"). CPI: only 21 of ~700 series have an October 2025 value;
  import prices: about 450 of ~980. PPI is complete. Month-to-month changes across October 2025
  need interpolation or exclusion; 12-month changes for October 2025 and October 2026 are affected.

- **All-zero rows**: about 40% of HS10 × country × month rows (2025) have zero value and quantity; the
  API returns rows for months without trade. Dropped when the import panel is built (P12).
- **Revisions**: data are as retrieved on the date above; Census revises prior months (annual revision
  each June). Re-pull with `--refresh` to update.

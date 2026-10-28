# HS lists for tariff actions

One CSV per product list referenced from `tariff_actions.csv` as `file:hs_lists/<name>.csv`
(for example a Section 301 annex or the reciprocal-tariff Annex II exemptions).

- One column, `hs`: HS prefixes of 2, 4, 6, 8 or 10 digits (annexes are usually HTS8).
- Name files after the action, e.g. `s301_cn_list3.csv`, `ieepa_reciprocal_annex2.csv`.
- Put the source (Federal Register citation and URL of the annex) in the `source_citation` and
  `source_url` of every row that uses the file, and note the annex in `notes`.
- `make timeline-validate` checks that every code matches at least one HS10 code in the Census
  code lists (2017–present).

## Files (built by `make hs-lists` from HTSUS Chapter 99, hts.usitc.gov)

| File | Contents | Source |
|---|---|---|
| `s301_cn_list1.csv` | 818 HTS8, Section 301 List 1 (heading 9903.88.01) | note 20(b), 2020 Basic Edition |
| `s301_cn_list2.csv` | 279 HTS8, List 2 (9903.88.02) | note 20(d), 2020 Basic |
| `s301_cn_list3.csv` | 5,769 HTS8, List 3 (9903.88.03 table + 9903.88.04 partial products) | notes 20(f), 20(g), 2020 Basic |
| `s301_cn_list3_exclude.csv` | 16 HTS10 lines excluded from the 9903.88.04 partial products | note 20(g) |
| `s301_cn_list3_unmatched.csv` | 7108.20.00 (monetary gold): legally on List 3, outside trade statistics | note 20(f) |
| `s301_cn_list4a.csv` | 3,232 HTS8, List 4A (9903.88.15) | note 20(s)(i) table + 20(s)(ii) |
| `s301_cn_list4a_exclude.csv` | 9 HTS10 lines excluded from 20(s)(ii) partial products | note 20(s)(ii) |
| `s232_steel.csv`, `s232_steel_exclude.csv` | steel scope (headings 7206–7229 except 7216.61/.69/.91; 7301.10, 7302.10/.40/.90, 7304–7306) | note 16(b), 2020 Basic |
| `s232_aluminum.csv` | aluminum scope (7601, 7604–7609, 7616.99.51) | note 19(b), 2020 Basic |
| `s232_steel_derivatives.csv`, `s232_aluminum_derivatives.csv` | Proclamation 9980 derivatives (nails, stranded wire, bumper/body stampings) | headings 9903.80.03 / 9903.85.03, 2021 Basic |

The Federal Register annexes for these actions are published as images, so the HTSUS notes that
implement them are the machine-readable official source.

## 2025–26 files (P09, `hs_lists_2025.py`)

| File | Codes | Contents | HTS release |
|---|---|---|---|
| `ieepa_recip_annex2_pre_2025_11.csv` | 842 | Reciprocal Annex II exemptions (9903.01.32) before 2025-11-13 | 2025 Rev 28 |
| `ieepa_brazil_exempt_pre_2025_11.csv` | 129 | Brazil IEEPA exemptions (9903.01.81) before 2025-11-13 | 2025 Rev 28 |
| `ieepa_recip_annex2.csv` | 1,079 | Reciprocal Annex II exemptions incl. 2025-11-13 agricultural additions | 2026 Rev 3 |
| `ieepa_recip_ag_2025_11.csv` | 11 | Particular articles exempt from 2025-11-13 (9903.02.78) | 2026 Rev 3 |
| `ieepa_recip_eu_natres.csv` | 219 | EU deal: unavailable natural resources (9903.02.74) | 2026 Rev 3 |
| `ieepa_recip_eu_aircraft.csv` | 544 | EU deal: civil aircraft and parts (9903.02.76) | 2026 Rev 3 |
| `ieepa_recip_eu_pharma.csv` | 807 | EU deal: non-patented pharmaceuticals (9903.02.77) | 2026 Rev 3 |
| `ieepa_recip_kr_aircraft.csv` | 548 | Korea deal: civil aircraft (9903.02.81) | 2026 Rev 3 |
| `ieepa_recip_ch_natres.csv` | 321 | Switzerland/Liechtenstein: natural resources (9903.02.84/89) | 2026 Rev 3 |
| `ieepa_recip_ch_aircraft.csv` | 544 | Switzerland/Liechtenstein: civil aircraft (9903.02.85/90) | 2026 Rev 3 |
| `ieepa_recip_ch_pharma.csv` | 807 | Switzerland/Liechtenstein: non-patented pharmaceuticals (9903.02.86/91) | 2026 Rev 3 |
| `ieepa_recip_jp_aircraft.csv` | 548 | Japan: civil aircraft (9903.96.02) | 2026 Rev 3 |
| `ieepa_brazil_exempt.csv` | 367 | Brazil IEEPA exemptions (9903.01.81), from 2025-11-13 | 2026 Rev 3 |
| `ieepa_brazil_ag_2025_11.csv` | 11 | Brazil particular articles exempt from 2025-11-13 (9903.01.90) | 2026 Rev 3 |
| `ieepa_brazil_aircraft.csv` | 555 | Brazil civil aircraft (9903.01.82) | 2026 Rev 3 |
| `s232_steel_deriv_2025_03.csv` | 158 | Steel derivatives from 2025-03-12 (9903.81.90) | 2026 Rev 3 |
| `s232_steel_deriv_2025_03b.csv` | 12 | Steel derivatives from 2025-03-12 (9903.81.91 part 1) | 2026 Rev 3 |
| `s232_steel_deriv_2025_06.csv` | 11 | Steel derivatives from 2025-06-23 (appliances; 9903.81.91 part 2) | 2026 Rev 3 |
| `s232_steel_deriv_2025_08.csv` | 388 | Steel derivatives from 2025-08-18 (inclusions; 9903.81.91 part 3) | 2026 Rev 3 |
| `s232_alum_deriv_2025_03.csv` | 24 | Aluminum derivatives from 2025-03-12 (9903.85.07) | 2026 Rev 3 |
| `s232_alum_deriv_2025_06.csv` | 4 | Aluminum derivatives from 2025-06-23 (9903.85.08, appliance codes) | 2026 Rev 3 |
| `s232_alum_deriv_2025_08.csv` | 220 | Aluminum derivatives from 2025-08-18 (9903.85.08, rest) | 2026 Rev 3 |
| `s232_copper_2025.csv` | 80 | Semi-finished copper and derivatives (9903.78.01) | 2026 Rev 3 |
| `s232_metals26_50.csv` | 279 | Metals regime from 2026-04-06, 50% lists 16(c)(i)-(v) | 2026 Rev 21 |
| `s232_metals26_50_alst.csv` | 203 | Same, aluminum and steel only, (i)-(iv) (UK 25%) | 2026 Rev 21 |
| `s232_metals26_25.csv` | 326 | 25% lists 16(c)(vi)-(viii) | 2026 Rev 21 |
| `s232_metals26_25_xi.csv` | 28 | 25% list 16(c)(xi) (15% all-in for deal partners from 2026-06-08) | 2026 Rev 21 |
| `s232_metals26_floor15.csv` | 86 | 15% all-in lists 16(c)(ix)-(x) | 2026 Rev 21 |
| `s232_autos_vehicles.csv` | 17 | Passenger vehicles and light trucks (note 33(b)) | 2026 Rev 21 |
| `s232_autos_parts.csv` | 130 | Automobile parts (note 33(g)) | 2026 Rev 21 |
| `s232_trucks_vehicles.csv` | 25 | Medium and heavy-duty vehicles (note 38(b)) | 2026 Rev 21 |
| `s232_trucks_buses.csv` | 10 | Buses (note 38(c)) | 2026 Rev 21 |
| `s232_trucks_parts.csv` | 182 | Medium and heavy-duty vehicle parts (note 38(i)) | 2026 Rev 21 |
| `s232_lumber_softwood.csv` | 15 | Softwood timber and lumber (note 37(b)) | 2026 Rev 21 |
| `s232_lumber_upholstered.csv` | 4 | Upholstered wooden furniture (note 37(d)) | 2026 Rev 21 |
| `s232_lumber_cabinets.csv` | 3 | Kitchen cabinets and vanities (note 37(f)) | 2026 Rev 21 |
| `s232_pharma.csv` | 149 | Pharmaceutical provisions (note 40(c)) | 2026 Rev 21 |
| `s232_drones.csv` | 16 | Unmanned aircraft and parts (note 43(c)) | 2026 Rev 21 |
| `s232_uk_aircraft.csv` | 559 | UK civil aircraft (9903.96.01) | 2026 Rev 21 |
| `s122_exempt_annex.csv` | 1,093 | Section 122 Annex exemptions (9903.03.03) | 2026 Rev 21 |
| `s122_exempt_particular.csv` | 11 | Section 122 particular articles (9903.03.04) | 2026 Rev 21 |
| `s122_exempt_aircraft.csv` | 540 | Section 122 civil aircraft (9903.03.05) | 2026 Rev 21 |
| `s301_cn_4yr_25_2024.csv` | 348 | Four-year review 25% from 2024-09-27 (9903.91.01) | 2026 Rev 21 |
| `s301_cn_4yr_50_2024.csv` | 2 | 50% from 2024-09-27 (9903.91.02, solar cells) | 2026 Rev 21 |
| `s301_cn_4yr_100_2024.csv` | 10 | 100% from 2024-09-27 (9903.91.03, EVs, syringes) | 2026 Rev 21 |
| `s301_cn_4yr_25_2024_masks.csv` | 1 | 25% from 2024-09-27 (9903.91.04, facemasks) | 2026 Rev 21 |
| `s301_cn_4yr_50_2025.csv` | 18 | 50% from 2025-01-01 (9903.91.05, semis, polysilicon, wafers) | 2026 Rev 21 |
| `s301_cn_4yr_25_2025.csv` | 3 | 25% from 2025-01-01 (9903.91.11, tungsten) | 2026 Rev 21 |
| `s301_cn_4yr_25_2026.csv` | 5 | 25% from 2026-01-01 (9903.91.06, batteries, graphite, magnets) | 2026 Rev 21 |
| `s301_cn_4yr_50_2026.csv` | 5 | 50% from 2026-01-01 (9903.91.07, medical gloves, respirators) | 2026 Rev 21 |
| `s301_cn_4yr_100_2026.csv` | 1 | 100% from 2026-01-01 (9903.91.08, rubber medical gloves) | 2026 Rev 21 |
| `s301_brazil_exempt.csv` | 870 | Section 301 Brazil exemptions (9903.05.03-.04) | 2026 Rev 21 |
| `s301_fl_exempt.csv` | 874 | Forced-labor exemptions: annex products and particular articles (note 52(b)-(c)) | 2026 Rev 21 |
| `s301_fl_aircraft.csv` | 124 | Forced-labor civil aircraft exemption (52(d)), aircraft lines only | 2026 Rev 21 |
| `s301_fl_pharma.csv` | 700 | Forced-labor pharmaceutical-use exemption (52(e)) | 2026 Rev 21 |
| `s301_brazil_aircraft.csv` | 124 | Section 301 Brazil civil aircraft (9903.05.05), aircraft lines only | 2026 Rev 21 |
| `s301_brazil_pharma.csv` | 705 | Section 301 Brazil pharmaceuticals (9903.05.06) | 2026 Rev 21 |
| `s338_ca_list1.csv` | 101 | Section 338 Canada list (b)(1) (9903.03.12) | 2026 Rev 21 |
| `s338_ca_list2.csv` | 52 | Section 338 Canada list (b)(2) (9903.03.13; not on S232 goods) | 2026 Rev 21 |
| `s338_ca_list3.csv` | 513 | Section 338 Canada list (b)(3) (9903.03.14) | 2026 Rev 21 |

Lists run together in the PDF text are split by `hs_lists_2025.note_codes`, which keeps a reading only if every piece is a real HS prefix in the 2017+ import statistics.

### Derived splits (P10)

| File | Lines | Contents |
|---|---|---|
| `s232_autos_parts_vehicle.csv` / `_general.csv` | 241 / 96 | Auto parts list expanded to current HTS10 lines and split by description: lines that name motor vehicles, engines, tractors, buses or trucks (or chapter 87) vs general-purpose lines (computers, bearings, motors, batteries). The duty applies to parts *of vehicles*, so general lines are `unidentified_subset` rows. |
| `s232_trucks_parts_vehicle.csv` / `_general.csv` | 194 / 48 | Same for medium/heavy-duty vehicle parts. |
| `*_aircraft.csv` (with `*_aircraft_full.csv`) | ~113–124 | Civil aircraft exemptions restricted to lines identifiable as aircraft goods (chapter 88 or "aircraft" in the description); the `_full` files are the official lists (~540 provisions, many general such as batteries and fasteners, exempt only when certified for civil aircraft). |

The description test is `hs_lists_2025.VEHICLE` / `AIRCRAFT` against the current HTSUS export (article description plus superior texts).

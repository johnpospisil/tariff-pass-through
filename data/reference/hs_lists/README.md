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

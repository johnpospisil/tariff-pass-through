# HS lists for tariff actions

One CSV per product list referenced from `tariff_actions.csv` as `file:hs_lists/<name>.csv`
(for example a Section 301 annex or the reciprocal-tariff Annex II exemptions).

- One column, `hs`: HS prefixes of 2, 4, 6, 8 or 10 digits (annexes are usually HTS8).
- Name files after the action, e.g. `s301_cn_list3.csv`, `ieepa_reciprocal_annex2.csv`.
- Put the source (Federal Register citation and URL of the annex) in the `source_citation` and
  `source_url` of every row that uses the file, and note the annex in `notes`.
- `make timeline-validate` checks that every code matches at least one HS10 code in the Census
  code lists (2017–present).

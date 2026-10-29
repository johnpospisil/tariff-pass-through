# Validation report (pre-publication QA, 2026-10-29)

Run with the data:validate-data checklist over the report, `data/published/` and the models, on
the data through August 2026 (refresh run 6, 427 tests passing).

## Overall assessment: share with the caveats below

The method matches the published designs, and the main numbers recompute independently from raw
Census data. The reconciliation gates pass and caveats are stated in the report. Two hard-coded
dates in the report were replaced with computed values, and a duplicated figure caption was
fixed. Nothing blocks publication.

## Methodology review

- **Question and framing.** The report asks about the incidence of pre-duty prices at the border
  and about CPI goods prices, and says what it does not claim (welfare, policy verdict, evasion,
  forecasts). Framing is neutral; reference lines are labelled by outcome ("Foreign exporters
  pay" / "US buyers pay").
- **Population.** Imports for consumption from individual countries; grouping codes are excluded
  (`census_countries.csv`, `is_individual`). HS 98–99 lines are dropped from product panels
  (4.5% of 2025–26 value).
- **Comparison.** The same design and data are run for 2018–19 as a benchmark against ARW (2019)
  and FGKK (2020).

## Calculation spot-checks

| Check | Result |
|---|---|
| Gate 1: HS10 × individual-country general imports vs FT-900, 116 months | All pass; largest gap 0.067% (tolerance 0.5%) |
| Gate 2: calculated duties vs Treasury customs receipts (3-month ratio vs baseline) | Within 8% in every month; within 3% since May 2025 |
| Effective rate recomputed from interim Census data (2024-06, 2025-05, 2025-10, 2026-08, all countries and China) | Matches `effective_rates.csv` to 5 decimals |
| Supplier shares in `diversion_shares.csv` sum to 1 per month and panel | Yes (both panels) |
| Report numbers vs `border_pt.csv` (main β, SE) | Match (tested in `tests/test_review.py`) |
| Buyer share "96–100 cents" | 100 × (1 + β) over main and trimmed β, capped at 100 (main implies 104) |
| Report prose scanned for hard-coded figures | Two dates were typed in: China statutory peak month and pharmaceutical surge month; now computed |

## Reasonableness

- **Imports up about 20% after the IEEPA ruling** (March–August 2026, $299–331bn a month against
  $250–260bn in January–February). This matches the published FT-900 totals, so it is real.
  Robustness: β to February 2026 is −0.001 (0.032).
- **Effective vs statutory.** The gap is explained line by line (USMCA claims, in-transit
  exemptions, Section 232 metal content, low-value lines) in DATA.md, "Statutory vs collected
  duties". External benchmark: Penn Wharton Budget Model 7.1% vs ours 6.9% (different import base).

## Visualization review

- One chart per question, light and dark versions, alt text and a data link under each.
- The hero chart uses a common axis with both reference lines; CIs shown; no dual axes.
- Fixed: each chart showed its caption twice (the hidden dark copy's caption was visible).

## Issues found

1. **Medium: the headline depends on the outlier rule** (+0.04 winsorised vs −0.04 trimmed;
   2018–19 +0.17 vs −0.06). The report gives both and the buyer share as a range. Keep.
2. **Medium: value weighting gives −0.29 (0.14)**, from HS 84 composition. Stated in Robustness;
   not in Findings. Acceptable, since the unweighted variety-level design is the standard one.
3. **Medium: 2018–19 ARW-design replication is 3.3 combined SEs below ARW.** Stated in the
   report and DATA.md; reviewer question 2.
4. **Medium: retail sign depends on item trends.** The Findings say the estimates are measured
   against each item's own trend and are not significant; Limitations states the dependence.
5. **Low, fixed: hard-coded dates** in report prose (2 instances).
6. **Low, fixed: duplicate figure captions.**

## Required caveats for readers

- Border estimates measure pre-duty prices; who ultimately bears the cost (importers, retailers,
  consumers) is only partly addressed by the retail section, which is imprecise.
- Unit values are not transaction prices.
- Statutory rates overstate collected duties; per-dollar magnitudes use the instrumented
  collected rate.
- Census duties are as assessed; IEEPA refunds are not netted out.
- Data are revised monthly; figures carry a "data as of" month.

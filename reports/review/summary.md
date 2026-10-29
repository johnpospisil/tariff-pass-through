# Who Pays the Tariffs? One-page summary for review

**Data through August 2026** (Census imports for consumption, HS10 × country × month, 2017-01 to
2026-08; BLS import prices and CPI to the same month). Legal status checked 2026-10-29.
Report: <https://johnpospisil.github.io/tariff-pass-through/> · Code and data:
<https://github.com/johnpospisil/tariff-pass-through>

## Question

How much of the 2025–26 US tariffs showed up in the prices US importers paid, and how much did
foreign exporters absorb by cutting pre-duty prices? Secondary questions: how much reached CPI
goods prices, how trade shifted between suppliers, and whether importers stockpiled ahead of each
action.

## Design

- **Tariff measure.** A cited timeline of 311 action components in 34 groups (Sections 201, 232,
  301, 122, 338, IEEPA fentanyl and reciprocal, de minimis), expanded to a daily and then monthly
  HS10 × country statutory additional rate with the stacking, exclusion and USMCA rules stated in
  the orders. Regressor: 12-month Δln(1 + τ) on the statutory rate. The collected rate (calculated
  duties ÷ customs value), instrumented by the statutory rate, gives magnitudes per unit of duty
  actually assessed.
- **Border.** Amiti–Redding–Weinstein design on 12-month log changes of unit values (customs
  value ÷ quantity) for HS10 × country varieties, HS6 × month and country × month FE, HS8
  clusters; 1/99 winsorising, with the ARW ratio-3 trim always reported alongside. β = 0: the
  duty is added in full to what importers pay; β = −1: exporters absorb it fully.
- **Retail.** CPI item indexes on tariff exposure (import share of supply × duty change, via
  HS10 → NAICS → BEA commodity → PCE → CPI), item and month FE, item-specific pre-trends, 118
  items in 47 exposure clusters; a hand-mapped concordance for 46 major goods as a check.
- **Diversion.** PPML gravity and long differences of HS6 × country import values on tariff
  changes; transshipment proxies flagged as patterns only.

## Main results (2025–26 window: 2024-01 to 2026-08)

| Quantity | Estimate (SE) | 2018–19 for comparison |
|---|---|---|
| Pre-duty unit value, main | +0.041 (0.029) | +0.167 (0.047) |
| Pre-duty unit value, ratio-3 trim | −0.039 (0.011) | −0.058 (0.020) |
| Duty-inclusive unit value (statutory τ) | +0.508 (0.034) | +0.942 (0.047) |
| Duty-inclusive, collected τ instrumented | +1.061 (0.060) | +1.202 (0.060) |
| Quantity, collected τ instrumented | −1.476 (0.096) | −2.495 (0.113) |
| BLS import price indexes by locality | +0.011 (0.016) | +0.096 (0.078) |
| Section 232 only, pre-duty | −0.086 (0.039) | −0.084 (0.056) |
| Retail θ, statutory exposure, item trends | +0.29 (0.23) | +0.96 (1.12) |
| PPML import elasticity to ln(1 + τ) | −1.47 (0.33) | −2.27 (0.29) |

**Reading.** Pre-duty import prices barely moved: of each dollar of duty, roughly 96–100 cents
(capped at 100) was added to what US importers paid at the border, as in 2018–19. Section 232
metals and autos are the only group with a significant exporter price cut, of about 9% of the
duty. Retail estimates are positive but imprecise: CPI prices of exposed goods rose by roughly
0.3–0.65 of the duty cost of their imports, and no specification is significant at 5%. Collected
duties ran well below the rates on paper (10.8% effective against 16.8% statutory at the October
2025 peak), so statutory-τ coefficients on duty-inclusive prices and quantities are attenuated;
the instrumented versions are the per-dollar magnitudes.

## Main caveats

1. Unit values mix price and composition. The 1/99 winsorised and ratio-3 trimmed estimates
   bracket the main result (+0.04 vs −0.04); value weighting gives −0.29 (0.14), driven by a shift
   in the product mix of computers and servers (HS 84).
2. Our 2018–19 ARW-design replication gives −0.107 (0.021) against ARW's −0.003 (0.024), a gap of
   3.3 combined SEs that is partly but not fully explained.
3. Retail estimates depend on extrapolating each item's 2023–24 trend; without trends the sign
   flips (−0.76) because high-exposure goods were already falling relative to others.
4. Census duties are as assessed at entry. IEEPA refunds ($126bn paid by 2026-10-02, of about
   $166bn owed) are a later transfer to importers and are not netted out.

See `key_estimates.md` (all specifications), `tariff_timeline.md` (citations), `data_gaps.md`
and `questions.md`.

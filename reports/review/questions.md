# Questions for the reviewer

Ordered by how much the answer could change the headline. Short answers are welcome.

1. **Winsorised vs trimmed unit values.** Our main estimate winsorises 12-month unit-value
   changes at 1/99 (+0.041, SE 0.029); the ARW ratio-3 trim gives −0.039 (0.011). In 2018–19 the
   gap is larger (+0.167 vs −0.058). Which would you treat as the headline, or should we lead with
   the range, as we do now?

2. **The 2018–19 replication gap.** In ARW's own design (2018, HS10 FE + country × year FE,
   ratio-3 trim) we get −0.107 (0.021) against their −0.003 (0.024). Part of the gap comes from
   within-2018 currency moves (−0.058 with country × month FE) and a smaller sample (55% of
   theirs; 13.9% of 2018–19 import value has no quantity unit in our data). Is that an acceptable
   replication, and is there a sample difference we are missing?

3. **Statutory or collected rate as the regressor.** We use statutory Δln(1 + τ) as the main
   regressor and the collected rate instrumented by statutory as the per-dollar magnitude.
   Collected duties rise only about 0.5 per unit of statutory change at the variety level (USMCA
   claims, metal-content bases, in-transit exemptions). Is the IV's exclusion restriction
   credible, given that statutory rates could affect prices through channels other than collected
   duties, such as anticipation or exemption claims?

4. **Post-ruling months.** The 2025–26 window runs to August 2026 and includes six months after
   IEEPA duties ended, when imports rose about 20%. Ending in February 2026 gives −0.001 (0.032).
   Should the falls in tariffs after the ruling identify β symmetrically with the increases, or
   should we report increases and decreases separately?

5. **Value weighting.** Weighting by import value gives −0.29 (0.14), entirely from HS 84
   (computers and servers), where the product mix shifted toward Taiwan and Mexico as tariffs
   diverged. We report unweighted as main. Do you agree, or would you report a weighted estimate
   excluding HS 84 as well?

6. **Retail trends.** The retail DiD fits item-specific linear trends on the pre-period (2023–24 for
   2025–26). Without trends the estimate is −0.76 (0.24). Is a linear trend the right
   control, or would you prefer a synthetic control or matching on pre-period trends?

7. **Retail concordance.** HS10 → NAICS → BEA commodity → PCE bridge → CPI item uses the 2017
   benchmark tables. Is there a better public source of import shares by CPI item, for example
   the BEA import matrix or the Boehm–Flaaen–Pandalai-Nayar approach?

8. **Section 232 attenuation.** Section 232 rows show the only significant exporter price cut
   (−0.086, SE 0.039). Collected duties on them rise only 0.38 per unit of statutory change. Should
   that estimate be rescaled, and if so, is a −0.2 per-collected-dollar reading plausible for
   metals and autos?

9. **Transshipment proxies.** We flag HS6 × country pairs with a surge from a small prior share
   while China's share fell, and unit values converging to China's. Is there a better public
   check, such as mirror statistics from partner exports to the US or rules-of-origin rulings?

10. **Anything missing** from the tariff timeline (`tariff_timeline.md`) that you would expect
    to matter for 2025–26 price changes?

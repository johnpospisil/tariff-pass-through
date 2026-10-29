# Other audiences (spec §9)

Numbers are for data through August 2026. Check the report's "data as of" month before posting.

## Hacker News (Show HN)

Audience: engineers and data people; they care about method, data plumbing and reproducibility.

**Title:** Show HN: Who paid the 2025–26 US tariffs? Product-level pass-through, rebuilt monthly

**Text:**

I built an open pipeline that estimates how much of the 2025–26 US tariffs showed up in the prices
US importers paid. It uses Census import data at the HS10 product × country × month level (18m
rows since 2017), a hand-built timeline of 311 tariff action components (each cited to the
Federal Register or a proclamation), and the standard research design from the 2018–19 trade war
literature.

Result: pre-duty import prices barely moved. Of each dollar of duty, roughly 96–100 cents was
added to what importers paid, as in 2018–19. Consumer prices of exposed goods rose by part of
that, imprecisely.

Some engineering notes:
- Polars + DuckDB over parquet; pyfixest for regressions with millions of fixed effects.
- Reconciliation gates in the test suite: product-level sums must match the published monthly
  trade totals within 0.5% (they match within 0.07% in all 116 months).
- A GitHub Actions job rebuilds everything when Census releases a new month (about 70 minutes, which
  needed a 32 GB swap file on the runner), runs about 430 tests, and redeploys a Quarto site.
- The product explorer is Observable JS on a static bundle split by HS heading; browser tests
  check it loads in under 3 seconds.

Report: https://johnpospisil.github.io/tariff-pass-through/
Code: https://github.com/johnpospisil/tariff-pass-through

## r/economics

Audience: economics-literate readers; the subreddit expects sources and methods, not opinion.
Check the subreddit's current self-promotion and flair rules before posting.

**Title:** Pass-through of the 2025–26 US tariffs to import and consumer prices: product-level
estimates with open data

**Text:**

Using Census HS10 × country × month import data and the Amiti–Redding–Weinstein (2019) design
(12-month unit-value changes on Δln(1 + tariff), HS6 × month and country × month FE, HS8
clusters):

- Pre-duty import prices: β = +0.04 (SE 0.03); −0.04 (0.01) with ARW's outlier trim. 0 = full
  pass-through to US importers, −1 = full absorption by exporters. 2018–19 in the same data: +0.17
  winsorised, −0.06 trimmed.
- Section 232 metals and autos: −0.09 (0.04), the only significant exporter price cut.
- BLS import price indexes by country of origin: +0.01 (0.02).
- CPI goods: θ ≈ 0.3–0.65 of the duty cost against item-specific trends; not significant.
- Effective tariff rate peaked at 10.8% (statutory 16.8%), October 2025.

Caveats: unit values aren't transaction prices; statutory rates overstate collected duties (we
also instrument the collected rate); the retail estimate depends on pre-trends. No welfare claims.

Report: https://johnpospisil.github.io/tariff-pass-through/ · Code and data:
https://github.com/johnpospisil/tariff-pass-through

## Business journalists (email pitch)

Audience: reporters covering trade, prices and retail. Short, with a story angle and offers of
help.

**Subject:** Data: US importers paid nearly all of the 2025–26 tariffs, product-level estimates

Hi [name],

I've published an open analysis of who paid the 2025–26 tariffs, built from monthly Census import
data for every product and country. The main findings, with data through August 2026:

- Foreign exporters barely cut their prices. Of each dollar of duty, roughly 96–100 cents was
  added to what US importers paid, the same as in the 2018–19 trade war.
- The exception is steel, aluminum and autos (Section 232), where exporters absorbed about 9%.
- Store prices of the most exposed goods rose by part of the duty, gradually.
- Duties actually collected averaged 10.8% at the October 2025 peak, against 16.8% on paper.

A product explorer lets you look up any product (washing machines, toys, solar panels) and see its
tariff, import price and suppliers month by month, which may help with local or industry stories.
The site updates each month after the Census trade release.

Report: https://johnpospisil.github.io/tariff-pass-through/
Explorer: https://johnpospisil.github.io/tariff-pass-through/explore.html

Happy to walk through the method or pull numbers for a specific product.

[Your name]

## Trade economists and think-tank tariff trackers (email or DM)

Audience: researchers who track tariffs (e.g. budget labs, trade policy institutes). The ask is
review and cross-checking, not coverage.

**Subject:** 2025–26 tariff pass-through estimates, open data; comments welcome

Hi [name],

I've built a monthly-updated, open replication of the ARW / FGKK border pass-through design for
2025–26, with a cited HS10 × country tariff timeline (311 components, including the post-ruling
Section 122, 301 and 338 actions). The pre-duty estimate is +0.04 (0.03), −0.04 with the ratio-3
trim; Section 232 is −0.09. Effective rates line up with Penn Wharton's (6.9% vs 7.1% in August
2026).

There's a short review packet with the specifications, data gaps and ten specific questions:
https://github.com/johnpospisil/tariff-pass-through/tree/main/reports/review

If our tariff timeline or effective-rate series would be useful to cross-check against yours, it
is in `data/reference/tariff_actions.csv` and `data/published/effective_rates.csv`.

Thanks,
[Your name]

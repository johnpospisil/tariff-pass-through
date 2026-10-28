# Project 30: Who Pays the Tariffs?

**Backlog ID:** FI-1 · **Difficulty:** Medium–high (trade data) · **Data access:** Open (Census API key optional) · **Estimated time:** 7 weeks

**Working title:** *At the Border and at the Store: Tariff Pass-Through in 2025–26*

**One-sentence pitch:** Use monthly product-level US import data with calculated duties, import price indexes and CPI to measure how much of the 2025–26 tariffs were paid by US importers and consumers vs absorbed by foreign exporters, and how fast trade shifted between countries.

---

## 0. Day-one access check
- [ ] Query the Census International Trade API (`api.census.gov/data/timeseries/intltrade/imports/hs`) for HS10 × country monthly imports with general value, dutiable value, calculated duties and quantity. An API key is free and optional.
- [ ] Download BLS Import/Export Price Indexes (MXP) and CPI item-level series (bls.gov API).
- [ ] Build a tariff timeline table. **Tariff rates, exemptions and legal challenges changed frequently through 2025–26, including a Supreme Court case on emergency-powers (IEEPA) tariffs; check each rate and date against official sources (Federal Register, USTR, CBP).**

## 1. The question

**Primary:** For products hit by new 2025–26 tariffs, did pre-tariff import prices (what foreign exporters charge) fall, meaning foreigners absorbed part of the tariff, or stay flat, meaning US buyers paid the full tariff?

**Secondary:**
- **Retail:** how much did consumer prices rise for tariffed goods relative to non-tariffed goods (CPI categories by import share and tariff exposure)?
- **Trade diversion:** did imports shift from high-tariff countries (e.g. China) to lower-tariff ones (Vietnam, Mexico, India), and did some of that reflect transshipment?
- **Effective tariff rate:** duties collected ÷ import value, monthly, overall and by country, compared with the statutory rates.
- **Front-running:** imports surged before tariffs took effect; how big was the stockpiling and how long did it last?
- **De minimis:** the end of duty-free treatment for low-value shipments (2025). What happened to small-parcel imports?

**A finding that would be wrong if:** pre-duty import unit values fall roughly one-for-one with tariff increases (full foreign absorption), and tariffed CPI categories rise no faster than others.

## 2. Why now
- The 2025 tariffs raised the US average effective tariff rate to its highest level in many decades. **Check current estimates (e.g. Yale Budget Lab, Penn Wharton) and the status of the legal challenges.**
- The 2018–19 trade war literature found near-complete pass-through to US importers: Amiti, Redding & Weinstein (2019); Fajgelbaum et al. (2020); Cavallo et al., *Tariff Pass-Through at the Border and at the Store* (2021). Your contribution: **the same methods applied to the much bigger 2025–26 tariffs, with a public monthly tracker.**

## 3. Data sources

| Source | What it gives you | Grain | Where |
|---|---|---|---|
| **Census International Trade API** | Imports by HS10 × country × month: general value, dutiable value, calculated duties, quantity | HS10 × country × month | api.census.gov (open) |
| **USITC DataWeb** | Same data with tariff programme detail | HS × country × month | dataweb.usitc.gov (free account) |
| **BLS Import Price Indexes** | Import prices by product category (measured before duties) | category × month | bls.gov/mxp |
| **BLS CPI** | Consumer prices by item | item × month | bls.gov/cpi |
| **BLS PPI** | Producer prices | industry × month | bls.gov/ppi |
| **Tariff schedules** | HTS rates, Section 232/301/IEEPA actions and exemptions | HS × country × date | hts.usitc.gov, Federal Register, CBP CSMS messages |
| **BEA input-output tables** | Import content of consumer goods (mapping imports to CPI items) | industry | bea.gov |

## 4. Building the dataset

1. **Tariff timeline:** HS8/HS10 × country × effective date × additional duty rate, compiled from official notices (cited). This is the hardest and most valuable part.
2. **Import panel:** HS10 × country × month: value, quantity, duties, unit value (value ÷ quantity), effective rate (duties ÷ value).
3. **Exposure:** each product's tariff change, and each CPI item's import share × average tariff change (concordance HS → CPI items via BEA tables).
4. **Checks:** Census monthly totals vs the published FT-900 report; calculated duties vs Treasury customs receipts (Monthly Treasury Statement); unit values winsorised (they are noisy).

## 5. Method

### Border pass-through
- Regress the change in log pre-duty unit values on the tariff change, with HS6 × month and country × month fixed effects (the Amiti–Redding–Weinstein design). A coefficient of 0 means full pass-through to US buyers; −1 means full absorption by exporters.

### Retail pass-through
- DiD on CPI items: high- vs low-tariff-exposure categories, before and after; event study by month.

### Trade diversion
- Changes in country shares within HS6 products; gravity-style models; check suspicious surges (transshipment proxies like jumps in a country's exports of products it doesn't produce much of).

### Robustness
- Different unit-value cleaning rules; excluding front-running months; different HS–CPI concordances.

### What you won't claim
Overall welfare effects. Focus on prices and trade flows.

## 6. Charts

| # | Chart | Purpose |
|---|---|---|
| **Hero** | **Pass-through estimate: pre-duty import prices vs tariff increase**, with "foreigners pay" and "Americans pay" reference lines | The headline |
| 2 | Effective tariff rate by month, 2024–today, overall and by major partner | Context |
| 3 | CPI: high- vs low-exposure categories indexed to Jan 2025 | The store |
| 4 | Import shares by country for tariffed products (stacked area) | Trade diversion |
| 5 | Front-running surge and drop (imports by week/month) | Stockpiling |
| 6 | Small-parcel imports before and after de minimis ended | Consumer angle |

**Interactive:** search a product (e.g. "washing machines", "toys") and see its tariff, import prices and sources over time.

## 7. Repo skeleton

```
tariff-pass-through/
  README.md, DATA.md, Makefile, pyproject.toml, uv.lock
  src/tpt/
    ingest/census_trade.py, usitc.py, bls_mxp.py, bls_cpi.py, bea_io.py
    build/tariff_timeline.py, import_panel.py, exposure.py, concordance.py
    models/border_pt.py, retail_did.py, diversion.py
    viz/theme.py, figures.py
  data/reference/tariff_actions.csv (cited)
  tests/          # totals vs FT-900, duties vs Treasury, pinned estimates
  report/index.qmd
  app/
  .github/workflows/monthly_refresh.yml
```

## 8. Milestones

| Week | Deliverable |
|---|---|
| 1 | Census API ingest; totals reconcile |
| 2–3 | Tariff timeline table (the hard part) |
| 3 | Effective rates; descriptive charts |
| 4 | Border pass-through models; hero chart v1 |
| 5 | Retail DiD; trade diversion |
| 6 | Article + product explorer |
| 7 | Review by a trade economist; publish; monthly refresh |

## 9. Distribution
- Economics and trade-policy communities (trade economists on social media, think-tank trackers), business journalists, r/economics, Hacker News.
- A monthly tracker gives journalists a reason to come back.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Tariff schedule complexity | Start with major actions; cite each; verify with duties actually collected |
| Unit values are noisy | Winsorising; product fixed effects; quantity unit checks |
| Rates change and legal status shifts | Dated timeline; update at publication |
| Politically sensitive | Neutral framing; publish code and data |

## 11. Stretch goals
- Retail scraped prices (if you build your own small price-scraping panel, check site terms).
- Export side: retaliatory tariffs and US exports.
- County exposure via industry mix (connect to Project 26).

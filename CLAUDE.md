# CLAUDE.md — Who Pays the Tariffs? (Project 30, FI-1)

Spec: [30-tariff-pass-through.md](30-tariff-pass-through.md). Read it before any prompt. This file holds the
project rules and the prompt sequence; run the prompts in order, one per session or sitting.

---

## Project rules (apply to every prompt)

### Stack
- Python 3.12, **uv** (`uv add`, `uv run`), **Polars** for transforms, **DuckDB** for large joins/queries
  over parquet, **pyfixest** for high-dimensional fixed-effects regressions, **httpx** + **tenacity** for APIs,
  **pytest**, **ruff** (lint + format), **matplotlib** for static figures, **Quarto + Observable JS** for the
  report and product explorer (static site on GitHub Pages).
- Package lives in `src/tpt/` (layout in spec §7). Entry points run through `make` targets.

### Data layout
- `data/raw/` — untouched API/download responses, cached and never edited (git-ignored).
- `data/interim/` — parsed, typed parquet (git-ignored).
- `data/processed/` — analysis-ready panels (git-ignored, rebuilt by `make`).
- `data/reference/` — small hand-built, **cited** tables (committed): `tariff_actions.csv`, concordances,
  series catalogs.
- `data/published/` — small aggregates exported for the report/explorer (committed or built in CI).
- Every raw pull writes a manifest row (source, URL/params, retrieved_at, sha256, row count).

### Secrets
- `CENSUS_API_KEY`, `BLS_API_KEY` in `.env` (git-ignored), loaded via `tpt.config`. Code must still run
  without keys (with lower rate limits) and must never log key values.
- Get keys: Census → https://api.census.gov/data/key_signup.html (emailed, activate via link).
  BLS v2 → https://data.bls.gov/registrationEngine/ (emailed, validate via link). Then
  `cp .env.example .env` and paste both.

### Workflow: TDD + verification gates
1. Write tests / reconciliation checks first (`tests/`), watch them fail.
2. Implement until they pass. `uv run pytest` and `uv run ruff check` must be clean.
3. **Report the numbers**: every prompt ends with a short summary of the actual results (row counts,
   reconciliation gaps, coefficients with SEs), not just "done".
4. **Gates block later work.** If a gate fails (e.g. totals don't reconcile), stop and diagnose; do not
   move to the next prompt or loosen a tolerance without saying so and why.
5. Commit at the end of each prompt with a message `P##: <summary>`.
6. Mark the prompt's heading in the prompt sequence `✅ DONE!`; when every prompt in a phase is done,
   mark the phase heading `✅ DONE!` too.

### Econometric conventions
- Tariff measure: `Δ ln(1 + τ)` where τ is the ad valorem additional duty rate.
- Prices: pre-duty unit value = customs value ÷ quantity (Census `CON_VAL_MO` / `CON_QY1_MO`, imports for
  consumption, which is what duties are assessed on). Duty-inclusive price = unit value × (1 + τ).
- Pass-through coefficient β on pre-duty prices: **β = 0 ⇒ US buyers pay the full tariff; β = −1 ⇒
  foreign exporters absorb it fully.** Duty-inclusive coefficient = 1 + β.
- Use 12-month log differences (or HS10×country + month-of-year FE) to handle seasonality.
- Cluster SEs by HS8 (or HS6) and report two-way (product, country) clustering as robustness.
- Unit values: drop changes of quantity unit, winsorise log changes at 1/99 pct (configurable).

### Things that bite in this data
- **Census country codes**: codes for groupings (world, regions, OECD, etc.) appear alongside individual
  countries. Filter to individual countries before summing or you double count.
- **HS10 codes change** most Januaries; build a cross-year concordance (Pierce–Schott method) before
  computing changes across years.
- **Revisions**: Census revises prior months, with annual revisions each June. Re-pull a trailing window on
  each refresh and record the vintage.
- **Duties ≠ cash receipts**: Census calculated duties are assessed on entry; Treasury receipts lag and
  include refunds/drawback. Expect timing gaps.
- **IEEPA legal status**: the Supreme Court case on IEEPA tariffs may mean duties were struck down and/or
  refunded. Verify the current status by web search before any prompt that uses IEEPA rates, and note the
  date checked. Known so far (DATA.md, from P04): struck down 2026-02-20; refunds from 2026-05 show in
  Treasury receipts (~$115bn by 2026-08); Census calculated duties are as assessed at entry.
- **De minimis**: shipments under $800 were mostly absent from official trade statistics before its end,
  so a post-repeal "increase" in recorded small parcels can be a measurement change, not a real increase.
- **October 2025 BLS gap**: the 2025 shutdown left most CPI (21 of ~700 series) and about half of
  import-price series without an October 2025 value. Handle it explicitly in any monthly price model.
- **Facts about tariffs must be cited**: no rate, date or HS scope goes into `tariff_actions.csv` without
  an official source (Federal Register citation, presidential proclamation/EO, USTR notice or CBP CSMS
  number) and a `verified_on` date. Recall is not a source.

### Scope limits
- No welfare claims (spec §5). Prices and trade flows only.
- Neutral framing in all prose and chart titles.

---

## Prompt sequence

Copy each prompt into Claude Code as written. Prompts assume the earlier ones are done.

### Phase 0 — Setup (Week 1) ✅ DONE!

**P01 — Scaffold the repo ✅ DONE!**
> Read CLAUDE.md and 30-tariff-pass-through.md. Scaffold the repo per spec §7 and the rules in
> CLAUDE.md: `git init`, `uv init` with Python 3.12, `pyproject.toml` (package `tpt` under `src/`),
> dependencies (polars, duckdb, pyarrow, httpx, tenacity, python-dotenv, pyfixest, matplotlib, pytest,
> ruff), `.gitignore` (data/raw, data/interim, data/processed, .env, Quarto output), `.env.example`, a
> `Makefile` with targets `setup, ingest, build, models, figures, report, test, lint, all`, empty module
> stubs, `README.md` and `DATA.md` skeletons, and `src/tpt/config.py` (paths, env loading, sample window
> 2017-01 to latest). Add one smoke test that imports `tpt` and checks config paths. Then create a GitHub
> repo `tariff-pass-through` with `gh repo create` (ask me public/private first) and push. Commit `P01`.

**P02 — Shared HTTP, cache and manifest layer ✅ DONE!**
> Build `src/tpt/ingest/_http.py`: an httpx client with tenacity retries (backoff on 429/5xx), per-source
> rate limiting, an on-disk raw cache keyed by request hash under `data/raw/<source>/`, and a manifest
> writer (`data/raw/manifest.parquet`: source, url, params without keys, retrieved_at, sha256, rows).
> Keys come from `tpt.config`; redact them from logs and manifests. Tests first: cache hit skips the
> network (mock transport), retries on 429, keys never appear in manifest or log output. Commit `P02`.

### Phase 1 — Ingest and reconcile (Week 1) ✅ DONE!

**P03 — Census International Trade ingest ✅ DONE!**
> Implement `src/tpt/ingest/census_trade.py` against `api.census.gov/data/timeseries/intltrade/imports/hs`.
> First, fetch the endpoint's `variables.json` and confirm exact variable names; we need HS10 commodity,
> country code/name, general value, consumption value, dutiable value, calculated duties, quantity 1 and
> its unit, for imports for consumption and general imports, monthly, 2017-01 to the latest month.
> Chunk requests by month × HS2 chapter so responses stay small; cache raw JSON; parse to typed parquet in
> `data/interim/census_imports/` partitioned by year. Also pull the country-level totals (all
> commodities) per month for reconciliation. Flag grouping country codes vs individual countries in a
> `data/reference/census_countries.csv`. Tests first on a recorded small response fixture (parsing, types,
> suppressed/blank values). Run a pilot for one month, report row count and runtime, estimate full-pull
> time, then run the full pull. Add `make ingest-census`. Commit `P03`.

**P04 — Reconciliation gates (FT-900 and Treasury) ✅ DONE!**
> Build `tests/test_reconcile.py` and `src/tpt/build/reconcile.py`. Gate 1: monthly sum of HS10 ×
> individual-country general imports vs the published FT-900 total imports of goods (Census basis, NSA);
> pull the FT-900 values from the Census API country totals or the FT-900 exhibit files and store them in
> `data/reference/ft900_totals.csv` with source URLs. Tolerance 0.5% per month. Gate 2: monthly
> calculated duties vs customs duties in the Monthly Treasury Statement (Fiscal Data API,
> `api.fiscaldata.treasury.gov`); expect timing lags, so compare levels and 3-month rolling sums and
> report the gap rather than hard-fail beyond 10%. Output a reconciliation table and a small diagnostic
> chart in `reports/qa/`. Report results month by month. If Gate 1 fails, diagnose (country groupings,
> revisions, general vs consumption) before continuing. Commit `P04`.

**P05 — BLS import prices, CPI and PPI ingest ✅ DONE!**
> Implement `src/tpt/ingest/bls_mxp.py` and `bls_cpi.py` (and a light PPI ingest in the same pattern)
> using the BLS API v2 (`api.bls.gov/publicAPI/v2/timeseries/data/`), batching up to 50 series and 20
> years per request. Build series catalogs in `data/reference/`: (a) MXP import price indexes by
> locality of origin (China, Canada, Mexico, EU, Japan, ASEAN, etc.) and by end use / HS-based
> categories; (b) CPI-U item-level indexes, NSA and SA, at the most detailed item strata available;
> (c) relevant PPI series. Get series IDs from the BLS series-ID files (`download.bls.gov/pub/time.series/
> ei/`, `/cu/`, `/wp/`), not from memory. Output long parquet (series_id, date, value, footnotes). Tests
> first on fixture responses including missing values ("-"). Report the series count and coverage.
> Commit `P05`.

**P06 — Reference data and concordances ✅ DONE!**
> Build `src/tpt/build/concordance.py` and `src/tpt/ingest/bea_io.py`. Assemble: (1) a cross-year HS10
> concordance 2017–present following Pierce & Schott (synthetic family IDs for split/merged codes), using
> Census annual HS10 concordance files; (2) HS10 → NAICS (Census import concordance); (3) BEA
> input-output use tables (detail level) and the PCE bridge table that maps commodities to PCE
> categories; (4) a PCE → CPI item crosswalk (document its source and any hand mapping in DATA.md);
> (5) the Rauch classification for differentiated vs homogeneous goods (SITC → HS). Tests: concordance
> is many-to-one onto family IDs, no HS10 in the panel is unmapped (report coverage by import value).
> Commit `P06`.

### Phase 2 — Tariff timeline (Weeks 2–3; the hard part)

**P07 — Timeline schema and validator ✅ DONE!**
> Design `data/reference/tariff_actions.csv` and `src/tpt/build/tariff_timeline.py`. One row per action
> component: action_id, authority (S232/S301/S201/IEEPA-fentanyl/IEEPA-reciprocal/de-minimis/other),
> country (ISO + Census code, or ALL), hs_scope (HS chapter/heading/HS8/HS10 list or a file reference in
> `data/reference/hs_lists/`), rate_type (ad valorem, specific), rate, effective_date, end_date,
> stacking_rule, exclusions_ref, legal_status, source_type, source_citation (FR cite / EO number / CSMS
> number), source_url, verified_on, notes. Write a validator (pydantic or pandera) and tests: required
> citation fields, dates parse, no overlapping rows for the same authority × country × HS without an
> explicit supersedes link, HS lists resolve to real HS10 codes. Commit `P07`.

**P08 — Compile 2018–19 actions (validation set)**
> Populate `tariff_actions.csv` with the 2018–19 trade war actions needed to replicate
> Amiti–Redding–Weinstein and Fajgelbaum et al.: Section 201 (washers, solar), Section 232 (steel,
> aluminum, including country exemptions and quotas), Section 301 China Lists 1, 2, 3 (10% then 25%) and
> 4A, plus later 4A reduction. Use web search to find each Federal Register notice and its HTS annex;
> download annex product lists into `data/reference/hs_lists/` and parse them. Every row cited with
> `verified_on` today. Where a published replication dataset exists (e.g. Fajgelbaum et al. replication
> files), cross-check our HS × date list against it and report mismatches. Commit `P08`.

**P09 — Compile 2025–26 actions**
> First, web search the current status of all 2025–26 tariff actions and the Supreme Court IEEPA case
> (ruling, any refunds, replacement authorities), and record findings with dates in DATA.md. Then populate
> `tariff_actions.csv` for 2025–present, verifying each against the Federal Register, White House
> EOs/proclamations, USTR and CBP CSMS messages. Candidate list to verify, not to trust: IEEPA fentanyl
> tariffs on Canada, Mexico and China (with USMCA-qualifying exemptions); IEEPA reciprocal tariffs
> (baseline and country-specific rates, Annex II exemptions, the electronics exemption, later
> modifications and deals); China escalation and the subsequent truce/reductions; Section 232 actions on
> steel/aluminum (rate increases, derivatives), autos and parts, copper, lumber/timber, trucks and any
> later sectors; end of de minimis (China/HK first, then all countries); any rulings or new actions after
> the court decision. Encode stacking rules as stated in the orders (which duties stack, which are
> mutually exclusive). Produce a dated summary table of actions in DATA.md. Flag anything uncertain with
> `legal_status` and `notes` rather than guessing. Commit `P09`.

**P10 — Expand to an HS10 × country × month rate panel**
> Implement the expansion in `tariff_timeline.py`: actions → daily HS10 × country additional duty rates
> applying stacking rules, exclusions, and USMCA treatment → monthly rates (day-weighted average within
> the month) → `data/processed/tariff_rates.parquet` with columns for each authority and the total. Use the
> HS10 concordance from P06. Tests first with hand-worked cases: a China HS10 under S301 List 3 plus 2025
> IEEPA fentanyl and reciprocal; a Canadian USMCA-qualifying vs non-qualifying good (document how we
> approximate qualification, e.g. using the share of imports claiming USMCA from Census `RP` / rate
> provision data if available); a steel product where S232 replaces the reciprocal rate; a mid-month
> effective date. Report the import-weighted statutory rate by month. Commit `P10`.

**P11 — Validate timeline against duties actually collected**
> Compare statutory rates from P10 with implied rates (calculated duties ÷ dutiable/consumption value)
> at HS10 × country × month. Report: correlation, the share of import value where statutory and implied
> differ by more than 5 pp, and the top 30 discrepancies by value with likely causes (exclusions,
> USMCA claims, drawback, timing, missing actions). Fix genuine timeline errors (with citations) and
> document known, explained gaps. Cross-check the overall statutory and effective rates against Yale
> Budget Lab / Penn Wharton published estimates (web search, cite date). Gate: aggregate implied vs
> statutory within a gap you can explain line by line. Commit `P11`.

### Phase 3 — Panel and descriptives (Week 3)

**P12 — Import panel**
> Build `src/tpt/build/import_panel.py` → `data/processed/import_panel.parquet` at HS10-family × country ×
> month: values, quantity, unit, unit value, effective rate, statutory rate (from P10), 12-month log
> changes in unit value, duty-inclusive price, quantity and value, and `Δln(1+τ)`. Cleaning: drop
> quantity-unit changes, zero/missing quantities, winsorise log changes (configurable rules kept in one
> place for robustness later). Use DuckDB for the heavy joins. Tests: no duplicate keys, effective rate in
> [0, 5], cleaning drops reported by reason and value share. Report the cleaned panel size and the share
> of import value retained. Commit `P12`.

**P13 — Chart theme and effective tariff rates (chart 2)**
> Load the dataviz skill first. Create `src/tpt/viz/theme.py` (one palette, neutral framing, consistent
> fonts, source footers) and `figures.py`. Compute monthly effective tariff rates 2017–present, overall and
> for China, Canada, Mexico, EU, Japan, Vietnam, India, and plot them against the import-weighted
> statutory rate. Export the series to `data/published/effective_rates.csv`. Save chart 2 as SVG + PNG in
> `report/figures/`. Commit `P13`.

**P14 — Front-running and de minimis (charts 5 and 6)**
> Front-running: for products hit by each major 2025 action, estimate the pre-effective-date surge and
> post-date drop relative to a counterfactual (same products' 2023–24 seasonal pattern and/or unaffected
> products), as an event study in months around each effective date; quantify excess imports and how long
> stockpiling lasted. De minimis: research how low-value and postal shipments are recorded in Census data
> before and after the de minimis changes (web search Census notices; cite), then chart the series that
> best tracks small parcels, with the measurement-change caveat on the chart. Charts 5 and 6 plus
> published CSVs. Commit `P14`.

### Phase 4 — Border pass-through (Week 4)

**P15 — Replicate 2018–19 (credibility gate)**
> Implement `src/tpt/models/border_pt.py` with pyfixest: regress 12-month Δln unit value (pre-duty) on
> Δln(1+τ) with HS6 × month and country × month FE (Amiti–Redding–Weinstein design), clustered by HS8;
> also duty-inclusive price and quantity regressions, and a Fajgelbaum-style event study with leads and
> lags. Run on 2017–2019. Gate: compare with the published estimates (β on pre-duty prices near 0,
> i.e. near-complete pass-through) and report our β with SEs. If far off, diagnose (unit values,
> concordance, tariff timing) before P16. Pin the estimates in `tests/test_pinned_estimates.py` with
> tolerances. Commit `P15`.

**P16 — 2025–26 border pass-through**
> Run the same design on 2024–present. Main spec with statutory Δln(1+τ); alternative using implied rates
> (flag endogeneity). Heterogeneity: by country (China vs others), by authority (S232 vs IEEPA), by
> Rauch differentiated vs homogeneous, by time since tariff (pass-through may change as contracts
> reset). Event study with leads to test pre-trends and front-running effects. Cross-check with BLS MXP
> import price indexes by locality of origin (China, Canada, Mexico) vs others. Produce the estimates table
> in `data/published/border_pt.csv` and a first hero chart draft. Report coefficients with SEs and the
> plain-language interpretation ("of each 10% tariff, roughly X% fell on US buyers"). Pin estimates.
> Commit `P16`.

**P17 — Robustness grid**
> Run a robustness grid over: unit-value cleaning rules (winsor 1/99 vs 5/95 vs trimming), excluding
> front-running months, alternative FE (HS8 × month), clustering choices, value-weighted vs unweighted,
> dropping China, dropping S232 products, 2025-only vs full window. Output a specification curve chart
> and a table in `data/published/robustness.csv`. Report which choices move β by more than its SE.
> Commit `P17`.

### Phase 5 — Retail and diversion (Week 5)

**P18 — HS → CPI exposure**
> Implement `src/tpt/build/exposure.py`: for each CPI item, the import share of supply and the
> import-weighted tariff change, mapped HS10 → NAICS → BEA commodity → PCE category → CPI item using the
> P06 concordances (spec §4.3). Build two alternative concordances (direct hand-mapping for major goods
> vs the BEA-bridge route) for robustness. Tests: weights sum to 1 within each CPI item; report items with
> low mapping coverage. Output `data/processed/cpi_exposure.parquet` and a top/bottom-20 exposure table.
> Commit `P18`.

**P19 — Retail DiD and event study (chart 3)**
> Implement `src/tpt/models/retail_did.py`: DiD on CPI item indexes with high vs low exposure (and a
> continuous-exposure version), item and month FE, event study by month relative to Jan 2025; replicate on
> 2018–19 as a check against Cavallo et al. Handle seasonality (SA series or NSA with item × month-of-year
> FE). Report the implied retail pass-through relative to the border estimate. Chart 3: high- vs
> low-exposure CPI indexed to Jan 2025. Pin estimates. Commit `P19`.

**P20 — Trade diversion (chart 4)**
> Implement `src/tpt/models/diversion.py`: within-HS6 country import shares over time for tariffed
> products; regressions of share changes on relative tariff changes; a gravity-style model with HS6 ×
> month and country × HS6 FE (PPML via pyfixest). Transshipment proxies: HS6 products where a country's
> US exports surged while it had little prior share and China's share fell, and unit-value convergence
> with China's; list top flagged pairs, framed as suspicious patterns, not proof. Chart 4: stacked area of
> import shares by country for tariffed products. Commit `P20`.

### Phase 6 — Publish (Weeks 6–7)

**P21 — Hero chart and final figures**
> Load the dataviz skill. Finalize the hero chart: pass-through estimates (2018–19 vs 2025–26, by
> authority/country) of pre-duty import prices vs the tariff change, with reference lines labelled "Foreign
> exporters pay" (β = −1) and "US buyers pay" (β = 0), CIs shown. Polish charts 2–6 for consistency,
> accessibility and dark/light rendering. All figures generated by `make figures` from processed data.
> Commit `P21`.

**P22 — Report**
> Write `report/index.qmd` (Quarto): the article *At the Border and at the Store: Tariff Pass-Through in
> 2025–26*. Structure: findings up front, data and tariff timeline, effective rates, border pass-through,
> retail, diversion, front-running, de minimis, robustness, limitations, what we don't claim, methods
> appendix, and "data as of" / legal status date. Pull all numbers from `data/published/` (no hard-coded
> figures). Neutral framing. Cite literature (Amiti–Redding–Weinstein 2019, Fajgelbaum et al. 2020,
> Cavallo et al. 2021) and all data sources. Render locally and report any warnings. Commit `P22`.

**P23 — Product explorer**
> Build the interactive explorer as an Observable JS page in the Quarto site (`app/` or `report/explore.qmd`):
> search a product by description ("washing machines", "toys") → its HS codes, tariff timeline by
> country, pre-duty unit value and duty-inclusive price over time, and import sources over time. Export
> a compact data bundle (`data/published/explorer/`, parquet or JSON, split by HS chapter to keep loads
> small; include HS descriptions). Test with playwright: search works, charts render, page loads under
> 3 s on the bundle. Commit `P23`.

**P24 — Monthly refresh and deploy**
> Create `.github/workflows/monthly_refresh.yml`: on a schedule after the Census monthly release plus a
> manual trigger, re-pull a trailing 24-month window (revisions), rebuild, run all tests including
> reconciliation gates and pinned estimates (pinned tests may warn rather than fail on new months; decide
> and document), render Quarto, deploy to GitHub Pages, and open an issue if a gate fails. Keys via
> repository secrets. Also add a workflow that reminds (issue) to re-verify tariff actions monthly. Run it
> once manually and report. Commit `P24`.

**P25 — Review packet and launch**
> Run the data:validate-data skill over the whole analysis. Then prepare a review packet for a trade
> economist in `reports/review/`: one-page summary, key estimates with specs, the tariff timeline with
> citations, known data gaps, and specific questions for the reviewer. Finalize README (how to run,
> findings, links) and DATA.md (every source, vintage, licence, known issues). Draft distribution posts
> (spec §9) in `reports/launch/`, written for each audience. Re-verify tariff legal status on publication
> day and update the "as of" date. Commit `P25`.

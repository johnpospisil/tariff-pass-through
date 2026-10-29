.PHONY: setup ingest ingest-census ingest-bls ingest-reference ingest-status reconcile concordance hs-lists timeline-2025 timeline-validate rates mfn usmca-share validate-rates import-panel effective-rates front-running low-value exposure retail-did diversion explorer review refresh snapshot-pack snapshot-unpack border-pt border-pt-2025 robustness build models figures report test lint format all

UV := uv run

setup:
	uv sync
	$(UV) playwright install chromium-headless-shell

ingest: ingest-census ingest-bls ingest-reference

ingest-census:  ## HS10 x country x month imports; resumable (cached chunks are skipped)
	$(UV) python -m tpt.ingest.census_trade

ingest-bls:  ## BLS import prices, CPI, PPI (API v2; ~45 requests)
	$(UV) python -m tpt.ingest.bls_mxp
	$(UV) python -m tpt.ingest.bls_cpi
	$(UV) python -m tpt.ingest.bls_ppi

ingest-reference:  ## HS10 code lists, BEA I-O tables and PCE bridge, Rauch, BLS CPI-PCE map
	$(UV) python -m tpt.ingest.hs_codes
	$(UV) python -m tpt.ingest.bea_io
	$(UV) python -m tpt.ingest.rauch
	$(UV) python -m tpt.ingest.cpi_pce_map

ingest-status:  ## live progress bar for a running ingest: make ingest-status SOURCE=bls
	@$(UV) python -m tpt.ingest.progress $(or $(SOURCE),census)

reconcile:  ## P04 gates: HS10 sums vs FT-900, duties vs Treasury (re-downloads both checks)
	$(UV) python -m tpt.build.reconcile

concordance:  ## P06 HS10 families, HS10->NAICS->BEA, Rauch, CPI<->PCE
	$(UV) python -m tpt.build.concordance

hs-lists:  ## P08/P09 product lists and country groups from official HTSUS Chapter 99 notes
	$(UV) python -m tpt.build.hs_lists
	$(UV) python -m tpt.build.hs_lists_2025

mfn:  ## P10 MFN (column 1 general) rates by HS10 from the HTSUS export
	$(UV) python -m tpt.build.mfn

usmca-share:  ## P10 USMCA-claimed import shares for Canada/Mexico from Census rate provisions
	$(UV) python -m tpt.ingest.census_rp

rates: mfn usmca-share  ## P10 HS10 x country x month additional-duty panel
	$(UV) python -m tpt.build.tariff_rates

validate-rates:  ## P11 statutory (P10 panel) vs implied rates from Census calculated duties
	$(UV) python -m tpt.build.validate_rates

import-panel:  ## P12 HS10-family x country x month panel: unit values, rates, 12-month changes
	$(UV) python -m tpt.build.import_panel

effective-rates:  ## P13 monthly effective vs statutory tariff rates by partner -> data/published/
	$(UV) python -m tpt.build.effective_rates

front-running:  ## P14 event studies of imports around the 2025 tariff actions -> data/published/
	$(UV) python -m tpt.build.front_running

low-value:  ## P14 Census low-value import estimates (HTS 9999.95) by origin -> data/published/
	$(UV) python -m tpt.build.low_value

timeline-2025:  ## P09 regenerate the 2024-26 rows of tariff_actions.csv
	$(UV) python -m tpt.build.actions_2025

timeline-validate:  ## P07 check data/reference/tariff_actions.csv (citations, dates, HS codes, overlaps)
	$(UV) python -m tpt.build.tariff_timeline

build: concordance timeline-validate rates validate-rates import-panel effective-rates front-running low-value exposure

models: border-pt robustness retail-did diversion  ## P15-P20 regressions -> data/published/

border-pt:  ## P15 replication + P16 2025-26 border pass-through (~1 h)
	$(UV) python -u -m tpt.models.border_pt

exposure:  ## P18 CPI item import shares and tariff exposure (BEA bridge and hand routes)
	$(UV) python -u -m tpt.build.exposure

retail-did:  ## P19 CPI DiD and event studies on P18 exposure (both periods)
	$(UV) python -u -m tpt.models.retail_did

diversion:  ## P20 long differences, PPML gravity, transshipment flags, chart 4 shares
	$(UV) python -u -m tpt.models.diversion

robustness:  ## P17 robustness grid (cleaning x variants, both periods, ~15 min)
	$(UV) python -u -m tpt.models.robustness

border-pt-2025:  ## P16 only: static grid, heterogeneity, MXP check, 2025-26 event studies
	$(UV) python -u -m tpt.models.border_pt pt
	$(UV) python -u -m tpt.models.border_pt events25

review:  ## P25 review packet tables -> reports/review/
	$(UV) python -m tpt.report.review

explorer:  ## P23 product explorer bundle -> data/published/explorer/
	$(UV) python -u -m tpt.report.explorer

figures:  ## charts from data/published/ in light and dark -> report/figures/
	$(UV) python -m tpt.viz.figures

report:  ## P22/P23 report numbers + explorer data + Quarto render -> report/_site/
	$(UV) python -m tpt.report.numbers
	rsync -a --delete data/published/explorer/ report/explorer_data/
	JUPYTER_PATH=$(CURDIR)/.venv/share/jupyter QUARTO_PYTHON=$(CURDIR)/.venv/bin/python $(UV) quarto render report --execute-daemon-restart

# --- P24 monthly refresh (.github/workflows/monthly_refresh.yml) ---------------------------
REFRESH_MONTHS ?= 24
SNAPSHOT ?= data-snapshot.tar.gz

refresh:  ## re-pull trailing Census window (revisions) + BLS/Treasury, rebuild everything, render
	$(UV) python -u -m tpt.ingest.census_trade --refresh-months $(REFRESH_MONTHS)
	$(MAKE) ingest-bls ingest-reference reconcile build models explorer review figures report

snapshot-pack:  ## CI data snapshot: raw downloads (not Census HS10 JSON) + parsed interim data
	COPYFILE_DISABLE=1 tar -czf $(SNAPSHOT) --exclude='._*' --exclude=data/raw/census --exclude=data/interim/import_panel_unwinsorised.parquet --exclude='_progress.json' data/raw data/interim

snapshot-unpack:  ## (drops any macOS AppleDouble ._ files, which DuckDB would read as parquet)
	tar -xzf $(SNAPSHOT)
	find data -name '._*' -delete

test:
	$(UV) pytest

lint:
	$(UV) ruff check .
	$(UV) ruff format --check .

format:
	$(UV) ruff format .
	$(UV) ruff check --fix .

all: ingest build models figures report

.PHONY: setup ingest ingest-census ingest-bls ingest-reference ingest-status reconcile concordance hs-lists timeline-2025 timeline-validate rates mfn usmca-share validate-rates build models figures report test lint format all

UV := uv run

setup:
	uv sync

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

timeline-2025:  ## P09 regenerate the 2024-26 rows of tariff_actions.csv
	$(UV) python -m tpt.build.actions_2025

timeline-validate:  ## P07 check data/reference/tariff_actions.csv (citations, dates, HS codes, overlaps)
	$(UV) python -m tpt.build.tariff_timeline

build: concordance timeline-validate rates validate-rates
	@echo "build: not implemented yet (P10, P12, P18)"

models:
	@echo "models: not implemented yet (P15-P20)"

figures:
	@echo "figures: not implemented yet (P13, P21)"

report:
	@echo "report: not implemented yet (P22)"

test:
	$(UV) pytest

lint:
	$(UV) ruff check .
	$(UV) ruff format --check .

format:
	$(UV) ruff format .
	$(UV) ruff check --fix .

all: ingest build models figures report

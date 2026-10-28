.PHONY: setup ingest ingest-status build models figures report test lint format all

UV := uv run

setup:
	uv sync

ingest:
	@echo "ingest: not implemented yet (P03, P05, P06)"

ingest-status:  ## live progress bar for a running ingest: make ingest-status SOURCE=bls
	@$(UV) python -m tpt.ingest.progress $(or $(SOURCE),census)

build:
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

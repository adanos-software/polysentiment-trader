PYTHON ?= python3
VENV ?= venv
BIN := $(VENV)/bin
TRADER := $(BIN)/python -m polysentiment_trader.cli
ANALYZE := $(BIN)/python -m polysentiment_trader.analysis
LEDGER ?= data/paper-portfolio.json
ANALYZE_HOURS ?= 12
INTERVAL ?= 60
CYCLES ?= 3
SCAN_LIMIT ?= 25
MIN_EDGE ?= 0.015
MAX_STAKE ?= 25

.PHONY: help setup setup-dev test preview test-run run loop demo portfolio analyze clean

help:
	@printf "PolySentimentTrader commands:\n"
	@printf "  make setup       create/update venv and editable install\n"
	@printf "  make preview     one dry run, no ledger write\n"
	@printf "  make run         one papertrade cycle, writes ledger\n"
	@printf "  make test-run    3 one-minute loop cycles by default\n"
	@printf "  make loop        hourly loop by default\n"
	@printf "  make demo        loop with tunable demo knobs\n"
	@printf "  make portfolio   pretty-print the JSON ledger\n"
	@printf "  make analyze     replay latest snapshots and explain filter pressure\n"
	@printf "  make test        run unit tests\n"

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install -e .

setup-dev:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install -e ".[dev]"

test: setup-dev
	$(BIN)/python -m pytest tests -q

preview:
	$(TRADER) --no-write

test-run:
	$(TRADER) --loop --interval-minutes 1 --cycles $(CYCLES)

run:
	$(TRADER)

loop:
	$(TRADER) --loop --interval-minutes $(INTERVAL)

demo:
	$(TRADER) --loop --interval-minutes $(INTERVAL) --scan-limit $(SCAN_LIMIT) --min-edge $(MIN_EDGE) --max-stake $(MAX_STAKE)

portfolio:
	@if [ -f "$(LEDGER)" ]; then \
		$(PYTHON) -m json.tool "$(LEDGER)"; \
	else \
		echo "No ledger at $(LEDGER)"; \
	fi

analyze:
	$(ANALYZE) --hours $(ANALYZE_HOURS)

clean:
	rm -rf .pytest_cache polysentiment_trader.egg-info

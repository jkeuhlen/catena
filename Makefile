# Catena — build & dev tasks. Run `make` (or `make help`) to list targets.

PORT      ?= 8000
GRAPH     := site/data/graph.json
PIPE_SRC  := $(wildcard pipeline/*.py)
PREVIEW   := docs/preview.png
# Headless browser used to render the preview image; override if needed:
#   make preview CHROME="/path/to/chrome"
CHROME    ?= /Applications/Google Chrome.app/Contents/MacOS/Google Chrome

.DEFAULT_GOAL := help

## ----------------------------------------------------------------------------
.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_][a-zA-Z0-9_ -]*:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[1;33m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install/sync dependencies with uv
	uv sync

## ---- pipeline --------------------------------------------------------------
# Rebuild the graph automatically whenever pipeline code changes or it's missing.
# (uv run auto-syncs the environment, so no explicit install step is needed.)
$(GRAPH): $(PIPE_SRC)
	uv run catena build

.PHONY: build
build: ## Rebuild the citation graph from the pipeline (force)
	uv run catena build

.PHONY: validate-pontiffs
validate-pontiffs: ## Check curated pontiff slugs against the live Vatican index
	uv run catena validate-pontiffs

.PHONY: preview
preview: $(PREVIEW) ## Regenerate docs/preview.png from the live site (needs Chrome)

$(PREVIEW): $(GRAPH) site/index.html site/styles.css site/app.js
	@test -e "$(CHROME)" || { echo "Chrome not found at '$(CHROME)'. Pass CHROME=…"; exit 1; }
	@mkdir -p docs
	@python3 -m http.server $(PORT) --directory site >/dev/null 2>&1 & srv=$$!; \
		trap "kill $$srv 2>/dev/null" EXIT; \
		sleep 1; \
		"$(CHROME)" --headless --disable-gpu --hide-scrollbars --window-size=1600,1000 \
			--screenshot="$(CURDIR)/$(PREVIEW)" --virtual-time-budget=4000 \
			"http://localhost:$(PORT)/?still=1" >/dev/null 2>&1; \
		status=$$?; kill $$srv 2>/dev/null; \
		test $$status -eq 0 && echo "Wrote $(PREVIEW)" || { echo "screenshot failed"; exit 1; }

## ---- serve -----------------------------------------------------------------
.PHONY: run serve
run serve: | $(GRAPH) ## Serve the static site (PORT=8000 by default)
	@echo "Catena → http://localhost:$(PORT)  (Ctrl-C to stop)"
	@cd site && python3 -m http.server $(PORT)

## ---- quality ---------------------------------------------------------------
.PHONY: test
test: ## Run the test suite
	uv run pytest -q

.PHONY: lint
lint: ## Lint Python (ruff) and check site JS syntax
	uv run ruff check pipeline tests
	@command -v node >/dev/null 2>&1 && node --check site/app.js && echo "site/app.js OK" \
		|| echo "node not found; skipping JS check"

.PHONY: fmt format
fmt format: ## Auto-format Python and apply safe lint fixes
	uv run ruff format pipeline tests
	uv run ruff check --fix pipeline tests

.PHONY: check
check: lint test ## Lint + test (use before committing)

## ---- housekeeping ----------------------------------------------------------
.PHONY: clean
clean: ## Remove caches and fetched HTML (keeps the built graph)
	rm -rf data/raw data/parsed .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

.PHONY: distclean
distclean: clean ## Also remove built graph + preview image
	rm -f $(GRAPH) data/graph/graph.json $(PREVIEW)

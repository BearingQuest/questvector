# Local gates. Each recipe line runs in bash with -euo pipefail, and make
# stops at the first line that fails.
SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help
.PHONY: help check audit sbom hooks

help: ## List the targets
	@grep -E '^[a-z0-9]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{ printf "  %-6s %s\n", $$1, $$2 }'

check: ## Ruff, mypy, pytest with coverage, template validation
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest --cov=questvector
	find templates -type f -name '*.yaml' -print0 | xargs -0 -n1 uv run qv template validate

# The same commands as the pip-audit job in .github/workflows/security.yml;
# tests/test_hooks.py fails if the two drift apart.
audit: ## pip-audit every package locked in uv.lock
	uv export --locked --all-extras --all-groups --no-emit-project --no-hashes \
	  --format requirements-txt | sed 's/ *;.*//' > audit-requirements.txt
	uv run --locked --only-group audit pip-audit --strict --disable-pip --no-deps -r audit-requirements.txt

# CycloneDX SBOM of the locked runtime dependencies and the optional AI
# extras the wheel can install, never the dev or audit groups, kept in dist/.
# uv's CycloneDX export is a preview feature (ADR-0023).
sbom: ## CycloneDX SBOM of the runtime dependencies in dist/sbom.cdx.json
	mkdir -p dist
	uv export --locked --all-extras --no-dev --no-emit-project --format cyclonedx1.5 --preview-features sbom-export --quiet -o dist/sbom.cdx.json

hooks: ## Use the committed hooks in .githooks (pre-push runs gitleaks)
	git config core.hooksPath .githooks

#!/usr/bin/env bash
.PHONY: help
help: ## Display this help screen
        @echo "Available commands:"
        @awk 'BEGIN {FS = ":.*?## "}; /^[a-zA-Z_-]+:.*?## / {printf "  \033[32m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ==============================================================================
# Application Tasks
# ==============================================================================

test: ## Run unit tests
	@uv run pytest

lint: ## Run linting and type checks
	@uv run ruff check .
	@uv run ruff format --check .
	@uv run mypy src

next: ## Display the top issue from the queue
	@uv run python -m taskagent next

list: ## List all issues in the queue
	@uv run python -m taskagent list

active: ## Mark an issue as active (usage: make active [SLUG=slug])
	@uv run python -m taskagent active $(SLUG)

done: ## Mark an issue as done (usage: make done [SLUG=slug])
	@uv run python -m taskagent done $(SLUG)

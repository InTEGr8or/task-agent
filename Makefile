#!/usr/bin/env bash
.PHONY: help
help: ## Display this help screen
        @echo "Available commands:"
        @awk 'BEGIN {FS = ":.*?## "}; /^[a-zA-Z_-]+:.*?## / {printf "  \033[32m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ==============================================================================
# Application Tasks
# ==============================================================================

test: ## Run unit tests

next: ## Display the top issue from the queue
	@uv run python -m issue_agent.cli

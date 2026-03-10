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
	@uv run python -m taskagent next

done: ## Mark an issue as done (usage: make done [SLUG=slug])
	@uv run python -m taskagent done $(SLUG)

SHELL := /bin/bash
.DEFAULT_GOAL := help

ENV ?=
PORT ?=
ARGS ?=

.PHONY: help build build-all test companion companion-pair companion-once companion-test clean device-info backup flash monitor

help: ## Show the available commands
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target> [ENV=name] [PORT=/dev/cu.usbmodem...]\n\n"} /^[a-zA-Z_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build default_envs (10_sokkon), or only ENV when supplied
	@PIO_ENV="$(ENV)" ./scripts/build.sh

build-all: ## Build every firmware environment, then run native tests
	@./scripts/build.sh --all

test: ## Run native unit tests
	@pio test --environment native

companion: ## Run the local-first macOS Sokkon USB companion (pass ARGS="...")
	@python3 -m companion $(ARGS)

companion-pair: ## Trust the attached Sokkon without sending app context, then exit
	@python3 -m companion --pair $(ARGS)

companion-once: ## Connect once for a quick Sokkon host/device check
	@python3 -m companion --once $(ARGS)

companion-test: ## Run the macOS companion unit and PTY integration tests
	@python3 -m unittest discover -s test_companion -v

clean: ## Clean default_envs, or only ENV when supplied
	@if [[ -n "$(ENV)" ]]; then pio run --environment "$(ENV)" --target clean; else pio run --target clean; fi

device-info: ## Read chip, flash, and security information without writing
	@PORT="$(PORT)" ./scripts/device-info.sh

backup: ## Read the full 16 MiB flash into ignored backups/ with SHA-256
	@PORT="$(PORT)" ./scripts/backup-factory.sh

flash: ## Explicitly build and upload ENV to the connected device
	@PIO_ENV="$(ENV)" PORT="$(PORT)" ./scripts/flash.sh

monitor: ## Open the serial monitor for ENV
	@PIO_ENV="$(ENV)" PORT="$(PORT)" ./scripts/monitor.sh

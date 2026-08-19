SHELL := /bin/bash
.DEFAULT_GOAL := help

ENV ?=
PORT ?=
ARGS ?=
FIRMWARE ?= 10_sokkon

# Recipes only receive one of these trusted constants. A command-line make
# variable is never interpolated into a shell command verbatim.
ifeq ($(value FIRMWARE),10_sokkon)
override SIMULATOR_FIRMWARE := 10_sokkon
else ifeq ($(value FIRMWARE),99_stopwatch)
override SIMULATOR_FIRMWARE := 99_stopwatch
else
override SIMULATOR_FIRMWARE := unsupported
endif

.PHONY: help build build-all test simulator-build simulator simulator-serve simulator-test workbench-install workbench-build workbench companion companion-pair companion-once companion-test macos-app macos-dmg clean device-info backup flash monitor

help: ## Show the available commands
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target> [ENV=name] [FIRMWARE=10_sokkon|99_stopwatch] [PORT=/dev/cu.usbmodem...] [ARGS=\"...\"]\n\n"} /^[a-zA-Z_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build default_envs (10_sokkon), or only ENV when supplied
	@PIO_ENV="$(ENV)" ./scripts/build.sh

build-all: ## Build every firmware environment, then run native tests
	@./scripts/build.sh --all

test: ## Run native unit tests
	@pio test --environment native

simulator-build: ## Compile selected production firmware as a native simulator
	@./scripts/build-simulator.sh --firmware "$(SIMULATOR_FIRMWARE)"

simulator: simulator-build ## Start selected local simulator and open a browser
	@python3 -m simulator --firmware "$(SIMULATOR_FIRMWARE)" --open $(ARGS)

simulator-serve: simulator-build ## Start selected local simulator without opening a browser
	@python3 -m simulator --firmware "$(SIMULATOR_FIRMWARE)" --no-open $(ARGS)

simulator-test: simulator-build ## Run native-runner, process-bridge, and HTTP/static-UI tests
	@python3 -m unittest discover -s test_simulator -v

workbench-install: ## Install the desktop workbench UI dependencies
	@npm --prefix simulator/workbench install --prefer-offline --no-audit --no-fund

workbench-build: ## Build the distributable desktop workbench frontend
	@npm --prefix simulator/workbench run build

workbench: ## Run the Firmware Workbench UI and switchable native backend
	@FIRMWARE="$(SIMULATOR_FIRMWARE)" ./scripts/run-workbench.sh

macos-app: ## Build the standalone M5Stack Simulator.app for this Mac
	@./macos/M5StackSimulator/scripts/build-app.sh --adhoc-sign

macos-dmg: macos-app ## Package the local app as a versioned DMG with SHA-256
	@./macos/M5StackSimulator/scripts/build-dmg.sh

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

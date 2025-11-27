### Defensive settings for make:
# See: https://tech.davis-hansson.com/p/make/
SHELL:=bash
.ONESHELL:                      # Each recipe runs in a single shell
.SHELLFLAGS:=-xeu -o pipefail -O inherit_errexit -c
.SILENT:                        # Hide command echo, we print our own messages
.DELETE_ON_ERROR:               # Delete targets if a recipe fails
MAKEFLAGS+=--warn-undefined-variables
MAKEFLAGS+=--no-builtin-rules   # Disable implicit rules for more predictable builds

# Export environment variables so QUALITY=20 works:
export QUALITY?=
export DRY_RUN?=
export PLONE_SITE_ID?=


# Terminal colors for nicer logging
# From: https://coderwall.com/p/izxssa/colored-makefile-for-golang-projects
RED=`tput setaf 1`
GREEN=`tput setaf 2`
RESET=`tput sgr0`
YELLOW=`tput setaf 3`

IMAGE_NAME_PREFIX=registry.gitlab.com/collective/fzjuelich
IMAGE_TAG=latest

# UV note: uv-specific PATH checks removed; still used for dependency management

PLONE_SITE_ID=Plone
BACKEND_FOLDER=$(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))
PLONE_VERSION=$(shell cat $(BACKEND_FOLDER)/version.txt)
EXAMPLE_CONTENT_FOLDER=${BACKEND_FOLDER}/src/fzjuelich/setuphandlers/examplecontent

VENV_FOLDER=$(BACKEND_FOLDER)/.venv
export VIRTUAL_ENV=$(VENV_FOLDER)
BIN_FOLDER=$(VENV_FOLDER)/bin

# Environment variables to be exported
export PYTHONWARNINGS := ignore
export DOCKER_BUILDKIT := 1

# Default target
all: build

# --------------------------------------------------------------------
# Helper: `make help` prints all targets with `##` descriptions
# --------------------------------------------------------------------
.PHONY: help
help: ## This help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------
# Dependencies & virtualenv
# --------------------------------------------------------------------
requirements-mxdev.txt: pyproject.toml mx.ini ## Generate constraints file
	@echo "$(GREEN)==> Generate constraints file$(RESET)"
	@echo '-c https://dist.plone.org/release/$(PLONE_VERSION)/constraints.txt' > requirements.txt
	@uvx mxdev -c mx.ini

$(VENV_FOLDER): requirements-mxdev.txt ## Install dependencies into local venv
	@echo "$(GREEN)==> Install environment$(RESET)"
ifdef CI
	@uv venv $(VENV_FOLDER)
else
	@uv venv --python=3.12 $(VENV_FOLDER)
endif
	@uv pip install -r requirements-mxdev.txt

.PHONY: sync
sync: $(VENV_FOLDER) ## Sync project dependencies
	@echo "$(GREEN)==> Sync project dependencies$(RESET)"
	@uv pip install -r requirements-mxdev.txt

# --------------------------------------------------------------------
# Plone instance configuration
# --------------------------------------------------------------------
instance/etc/zope.ini instance/etc/zope.conf: instance.yaml ## Create instance configuration
	@echo "$(GREEN)==> Create instance configuration$(RESET)"
	@uvx cookiecutter -f --no-input -c 2.1.1 --config-file instance.yaml gh:plone/cookiecutter-zope-instance

.PHONY: config
config: instance/etc/zope.ini ## Ensure instance config exists

.PHONY: install
install: $(VENV_FOLDER) config ## Install Plone and dependencies

# --------------------------------------------------------------------
# Cleanup / data management
# --------------------------------------------------------------------
.PHONY: clean
clean: ## Clean installation and instance
	@echo "$(RED)==> Cleaning environment and build$(RESET)"
	@rm -rf $(VENV_FOLDER) pyvenv.cfg .installed.cfg instance/etc .venv .pytest_cache .ruff_cache constraints* requirements*

.PHONY: remove-data
remove-data: ## Remove all instance data (var)
	@echo "$(RED)==> Removing all content$(RESET)"
	rm -rf $(VENV_FOLDER) instance/var

# --------------------------------------------------------------------
# Runtime helpers
# --------------------------------------------------------------------
.PHONY: start
start: $(VENV_FOLDER) instance/etc/zope.ini ## Start a Plone instance on localhost:8080
	@$(BIN_FOLDER)/runwsgi instance/etc/zope.ini

.PHONY: console
console: $(VENV_FOLDER) instance/etc/zope.ini ## Start a console into a Plone instance
	@$(BIN_FOLDER)/zconsole debug instance/etc/zope.conf

.PHONY: create-site
create-site: $(VENV_FOLDER) instance/etc/zope.ini ## Create a new site from scratch
	@$(BIN_FOLDER)/zconsole run instance/etc/zope.conf ./scripts/create_site.py

# WebP conversion helper target (for your script)
.PHONY: convert-images-to-webp
convert-images-to-webp: $(VENV_FOLDER) instance/etc/zope.ini ## Convert all stored images to WEBP
	@$(BIN_FOLDER)/zconsole run instance/etc/zope.conf ./scripts/convert_images_to_webp.py

# --------------------------------------------------------------------
# Example content export
# --------------------------------------------------------------------
.PHONY: update-example-content
update-example-content: $(VENV_FOLDER) ## Export example content inside package
	@echo "$(GREEN)==> Export example content into $(EXAMPLE_CONTENT_FOLDER) $(RESET)"
	if [ -d $(EXAMPLE_CONTENT_FOLDER)/content ]; then rm -r $(EXAMPLE_CONTENT_FOLDER)/* ;fi
	@$(BIN_FOLDER)/plone-exporter instance/etc/zope.conf $(PLONE_SITE_ID) $(EXAMPLE_CONTENT_FOLDER)

# --------------------------------------------------------------------
# QA / formatting / tests
# --------------------------------------------------------------------
.PHONY: lint
lint: ## Check and fix code base according to Plone standards
	@echo "$(GREEN)==> Lint codebase$(RESET)"
	@uvx ruff@latest check --fix --config $(BACKEND_FOLDER)/pyproject.toml
	@uvx pyroma@latest -d .
	@uvx check-python-versions@latest .
	@uvx zpretty@latest --check src

.PHONY: format
format: ## Format codebase according to Plone standards
	@echo "$(GREEN)==> Format codebase$(RESET)"
	@uvx ruff@latest check --select I --fix --config $(BACKEND_FOLDER)/pyproject.toml
	@uvx ruff@latest format --config $(BACKEND_FOLDER)/pyproject.toml
	@uvx zpretty@latest -i src

# i18n
.PHONY: i18n
i18n: $(VENV_FOLDER) ## Update locales
	@echo "$(GREEN)==> Updating locales$(RESET)"
	@$(BIN_FOLDER)/python -m fzjuelich.locales

# Tests
.PHONY: test
test: $(VENV_FOLDER) ## Run test suite
	@$(BIN_FOLDER)/pytest

.PHONY: test-coverage
test-coverage: $(VENV_FOLDER) ## Run tests with coverage
	@$(BIN_FOLDER)/pytest --cov=fzjuelich --cov-report term-missing

# --------------------------------------------------------------------
# Docker / acceptance
# --------------------------------------------------------------------
.PHONY: build-image
build-image:  ## Build Docker Images
	@docker build . -t $(IMAGE_NAME_PREFIX)-backend:$(IMAGE_TAG) -f Dockerfile --build-arg PLONE_VERSION=$(PLONE_VERSION)

# Acceptance tests
.PHONY: acceptance-backend-start
acceptance-backend-start: ## Start backend acceptance server
	ZSERVER_HOST=0.0.0.0 ZSERVER_PORT=55001 LISTEN_PORT=55001 APPLY_PROFILES="fzjuelich:default" CONFIGURE_PACKAGES="plone.restapi,plone.volto,plone.volto.cors,fzjuelich" $(BIN_FOLDER)/robot-server plone.app.robotframework.testing.VOLTO_ROBOT_TESTING

.PHONY: acceptance-image-build
acceptance-image-build:  ## Build Docker Images for acceptance
	@docker build . -t $(IMAGE_NAME_PREFIX)-backend-acceptance:$(IMAGE_TAG) -f Dockerfile.acceptance --build-arg PLONE_VERSION=$(PLONE_VERSION)

## Add bobtemplates features (plonecli integration)
add: $(VENV_FOLDER)
	@uvx plonecli add -b .mrbob.ini $(filter-out $@,$(MAKECMDGOALS))

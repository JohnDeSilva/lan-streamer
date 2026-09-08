.PHONY: run run-desktop run-agent lint check-lint reformat test test-desktop test-local test-agent test-agent-front test-agent-back load-test build validate-executable clean revision migrate release build-test-image build-agent-test-image agent-test agent-lint agent-run agent-down

UNAME_S := $(shell uname -s)

UV := $(shell command -v uv 2> /dev/null)
ifeq ($(UV),)
	PYTHON := .venv/bin/python
	PYTEST := .venv/bin/pytest
	RUFF := .venv/bin/ruff
	MYPY := .venv/bin/mypy
	PRE_COMMIT := .venv/bin/pre-commit
else
	PYTHON := uv run python
	PYTEST := uv run pytest
	RUFF := uv run ruff
	MYPY := uv run mypy
	PRE_COMMIT := uv run pre-commit
endif
# Wayland detection for stable VLC embedding
ifeq ($(XDG_SESSION_TYPE),wayland)
    QT_PLATFORM := QT_QPA_PLATFORM=xcb
else
    QT_PLATFORM :=
endif

# Container engine detection (prefers docker, falls back to podman, defaults to docker)
CONTAINER_ENGINE ?= $(shell command -v docker 2> /dev/null || command -v podman 2> /dev/null || echo docker)

TEST_OS ?= fedora
TEST_OS_VERSION ?= latest
GIT_HASH := $(shell git rev-parse --short HEAD)
VERSION := $(shell python3 -c "import re; print(re.search(r'__version__\s*=\s*[\x22\x27]([^\x22\x27]+)[\x22\x27]', open('src/lan_streamer/__init__.py').read()).group(1))")
DOCKERFILE := $(shell if [ -f docker/Dockerfile.$(TEST_OS)-$(TEST_OS_VERSION) ]; then echo docker/Dockerfile.$(TEST_OS)-$(TEST_OS_VERSION); else echo docker/Dockerfile.$(TEST_OS); fi)

run: migrate
	$(MAKE) -C agent up
	PYTHONPATH=src $(QT_PLATFORM) $(PYTHON) -m lan_streamer.main --config ./dev_run/config.json

run-desktop: migrate
	PYTHONPATH=src $(QT_PLATFORM) $(PYTHON) -m lan_streamer.main --config ./dev_run/config.json

run-agent:
	$(MAKE) -C agent run

typecheck:
	$(MYPY) src/

format:
	$(RUFF) format .

ruff-check:
	$(RUFF) check --fix .

lint: format ruff-check typecheck
	$(PRE_COMMIT) run --all-files

reformat: format ruff-check

check-lint:
	$(RUFF) format --check .
	$(RUFF) check .

setup-git-hooks:
	$(PRE_COMMIT) install --hook-type commit-msg --hook-type pre-push --hook-type pre-commit

test-local:
	LAN_STREAMER_DB=./test_library.db PYTHONPATH=src QT_QPA_PLATFORM=offscreen $(PYTEST) -n auto --cov-fail-under=90 -m "not load" tests/
	rm -f ./test_library.db ./test_library.db-wal ./test_library.db-shm

build-test-image:
	@if [ -z "$$($(CONTAINER_ENGINE) images -q lan-streamer-test-$(TEST_OS):$(GIT_HASH) 2>/dev/null)" ] || [ -n "$$(git status --porcelain 2>/dev/null)" ]; then \
		$(CONTAINER_ENGINE) build --build-arg TEST_OS_VERSION=$(TEST_OS_VERSION) -t lan-streamer-test-$(TEST_OS):$(GIT_HASH) -f $(DOCKERFILE) . ; \
	else \
		echo "Image lan-streamer-test-$(TEST_OS):$(GIT_HASH) already exists and workspace is clean. Skipping build."; \
	fi

build-agent-test-image:
	@if [ -z "$$($(CONTAINER_ENGINE) images -q lan-streamer-agent-test:$(GIT_HASH) 2>/dev/null)" ] || [ -n "$$(git status --porcelain 2>/dev/null)" ]; then \
		$(CONTAINER_ENGINE) build -t lan-streamer-agent-test:$(GIT_HASH) -f docker/Dockerfile.agent-test . ; \
	else \
		echo "Image lan-streamer-agent-test:$(GIT_HASH) already exists and workspace is clean. Skipping build."; \
	fi

ifeq ($(UNAME_S),Linux)
test-desktop: build-test-image
	$(CONTAINER_ENGINE) rm -f lan-streamer-test-$(TEST_OS)-run || true
	$(CONTAINER_ENGINE) run --name lan-streamer-test-$(TEST_OS)-run lan-streamer-test-$(TEST_OS):$(GIT_HASH) make test-local; \
	EXIT_CODE=$$?; \
	mkdir -p ./coverage-results; \
	$(CONTAINER_ENGINE) cp lan-streamer-test-$(TEST_OS)-run:/app/.coverage ./coverage-results/$(TEST_OS).coverage || true; \
	$(CONTAINER_ENGINE) rm -f lan-streamer-test-$(TEST_OS)-run; \
	exit $$EXIT_CODE
else
test-desktop: test-local
endif

test: test-desktop test-agent-front test-agent-back

ifeq ($(UNAME_S),Linux)
test-agent: build-agent-test-image
	$(CONTAINER_ENGINE) rm -f lan-streamer-agent-run || true
	$(CONTAINER_ENGINE) run --name lan-streamer-agent-run lan-streamer-agent-test:$(GIT_HASH) make -C agent test; \
	EXIT_CODE=$$?; \
	$(CONTAINER_ENGINE) rm -f lan-streamer-agent-run; \
	exit $$EXIT_CODE

test-agent-front: build-agent-test-image
	$(CONTAINER_ENGINE) rm -f lan-streamer-agent-front-run || true
	$(CONTAINER_ENGINE) run --name lan-streamer-agent-front-run lan-streamer-agent-test:$(GIT_HASH) make -C agent test-front; \
	EXIT_CODE=$$?; \
	$(CONTAINER_ENGINE) rm -f lan-streamer-agent-front-run; \
	exit $$EXIT_CODE

test-agent-back: build-agent-test-image
	$(CONTAINER_ENGINE) rm -f lan-streamer-agent-back-run || true
	$(CONTAINER_ENGINE) run --name lan-streamer-agent-back-run lan-streamer-agent-test:$(GIT_HASH) make -C agent test-back; \
	EXIT_CODE=$$?; \
	mkdir -p ./coverage-results; \
	$(CONTAINER_ENGINE) cp lan-streamer-agent-back-run:/app/agent/.coverage ./coverage-results/agent.coverage || true; \
	$(CONTAINER_ENGINE) rm -f lan-streamer-agent-back-run; \
	exit $$EXIT_CODE
else
test-agent:
	$(MAKE) -C agent test

test-agent-front:
	$(MAKE) -C agent test-front

test-agent-back:
	$(MAKE) -C agent test-back
endif

load-test:
	PYTHONPATH=src QT_QPA_PLATFORM=offscreen $(PYTEST) -m "load" -s --no-cov tests/



build:
	$(PYTHON) -m PyInstaller --noconfirm lan-streamer.spec
ifeq ($(UNAME_S),Darwin)
	rm -rf dist/lan-streamer-$(VERSION)
	ln -sf lan-streamer-$(VERSION).app/Contents/MacOS/lan-streamer-$(VERSION) dist/lan-streamer-$(VERSION)
endif

validate-executable:
ifeq ($(UNAME_S),Darwin)
	$(MAKE) build
	# 1. Dry run verification
	LAN_STREAMER_DRY_RUN=1 QT_QPA_PLATFORM=offscreen ./dist/lan-streamer-$(VERSION).app/Contents/MacOS/lan-streamer-$(VERSION)
	# 2. Runtime integration verification with timeout
	python3 -c "import subprocess, os, sys; res = subprocess.run(['./dist/lan-streamer-$(VERSION).app/Contents/MacOS/lan-streamer-$(VERSION)'], env=dict(os.environ, LAN_STREAMER_TEST_RUN='1', QT_QPA_PLATFORM='offscreen'), timeout=15); sys.exit(res.returncode)"
else
	$(MAKE) build-test-image
	# 1. Dry run verification inside container
	$(CONTAINER_ENGINE) run --rm -e LAN_STREAMER_DRY_RUN=1 -e QT_QPA_PLATFORM=offscreen lan-streamer-test-$(TEST_OS):$(GIT_HASH) ./dist/lan-streamer-$(VERSION)
	# 2. Runtime integration verification with timeout inside container (invoked from host python)
	python3 -c "import subprocess, os, sys; res = subprocess.run(['$(CONTAINER_ENGINE)', 'run', '--rm', '-e', 'LAN_STREAMER_TEST_RUN=1', '-e', 'QT_QPA_PLATFORM=offscreen', 'lan-streamer-test-$(TEST_OS):$(GIT_HASH)', './dist/lan-streamer-$(VERSION)'], env=os.environ, timeout=15); sys.exit(res.returncode)"
	$(CONTAINER_ENGINE) rm -f lan-streamer-test-$(TEST_OS)-extract || true
	$(CONTAINER_ENGINE) create --name lan-streamer-test-$(TEST_OS)-extract lan-streamer-test-$(TEST_OS):$(GIT_HASH)
	mkdir -p dist
	$(CONTAINER_ENGINE) cp lan-streamer-test-$(TEST_OS)-extract:/app/dist/lan-streamer-$(VERSION) ./dist/lan-streamer-$(VERSION)
	$(CONTAINER_ENGINE) rm -f lan-streamer-test-$(TEST_OS)-extract
endif





clean:
	rm -rf build/ dist/ .pytest_cache .ruff_cache *.log *.db*
	find . -type d -name "__pycache__" -exec rm -rf {} +

revision:
	export LAN_STREAMER_DB=./alembic_db.db
	PYTHONPATH=src $(PYTHON) -m alembic upgrade head
	PYTHONPATH=src $(PYTHON) -m alembic revision --autogenerate -m "$(name)"
	rm -f ./alembic_db.db ./alembic_db.db-wal ./alembic_db.db-shm



release:
	@echo "Release automation now runs in GitHub Actions."
	@echo "Merge feature branches into rc for manual-test artifacts."
	@echo "Merge rc into main to trigger the Commitizen release and tag publish workflow."
	@false
	@exit 1

agent-test: test-agent

agent-lint:
	$(MAKE) -C agent lint

agent-run: run-agent

agent-down:
	$(MAKE) -C agent down

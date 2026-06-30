.PHONY: run lint check-lint reformat test test-local load-test build validate-executable clean revision migrate release build-test-image

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
	PYTHONPATH=src $(QT_PLATFORM) $(PYTHON) -m lan_streamer.main

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
	$(CONTAINER_ENGINE) build --build-arg TEST_OS_VERSION=$(TEST_OS_VERSION) -t lan-streamer-test-$(TEST_OS):$(GIT_HASH) -f $(DOCKERFILE) .

ifeq ($(UNAME_S),Linux)
test: build-test-image
	$(CONTAINER_ENGINE) rm -f lan-streamer-test-$(TEST_OS)-run || true
	$(CONTAINER_ENGINE) run --name lan-streamer-test-$(TEST_OS)-run lan-streamer-test-$(TEST_OS):$(GIT_HASH) make test-local; \
	EXIT_CODE=$$?; \
	mkdir -p ./coverage-results; \
	$(CONTAINER_ENGINE) cp lan-streamer-test-$(TEST_OS)-run:/app/.coverage ./coverage-results/$(TEST_OS).coverage || true; \
	$(CONTAINER_ENGINE) rm -f lan-streamer-test-$(TEST_OS)-run; \
	exit $$EXIT_CODE
else
test: test-local
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
	python3 -c "import subprocess, os, sys; \
	p = subprocess.Popen(['./dist/lan-streamer-$(VERSION).app/Contents/MacOS/lan-streamer-$(VERSION)'], env=dict(os.environ, LAN_STREAMER_TEST_RUN='1', QT_QPA_PLATFORM='offscreen')); \
	try: \
		sys.exit(p.wait(timeout=15)) \
	except subprocess.TimeoutExpired: \
		p.terminate(); \
		p.wait(); \
		sys.exit(124)"
else
	$(MAKE) build-test-image
	# 1. Dry run verification inside container
	$(CONTAINER_ENGINE) run --rm -e LAN_STREAMER_DRY_RUN=1 -e QT_QPA_PLATFORM=offscreen lan-streamer-test-$(TEST_OS):$(GIT_HASH) ./dist/lan-streamer-$(VERSION)
	# 2. Runtime integration verification with timeout inside container (invoked from host python)
	python3 -c "import subprocess, os, sys; \
	p = subprocess.Popen(['$(CONTAINER_ENGINE)', 'run', '--rm', '-e', 'LAN_STREAMER_TEST_RUN=1', '-e', 'QT_QPA_PLATFORM=offscreen', 'lan-streamer-test-$(TEST_OS):$(GIT_HASH)', './dist/lan-streamer-$(VERSION)'], env=os.environ); \
	try: \
		sys.exit(p.wait(timeout=15)) \
	except subprocess.TimeoutExpired: \
		p.terminate(); \
		p.wait(); \
		sys.exit(124)"
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

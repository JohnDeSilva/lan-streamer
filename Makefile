.PHONY: run lint check-lint reformat test load-test test-ubuntu test-fedora test-distros build validate-executable validate-ubuntu validate-fedora validate-distros clean revision migrate release

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

run: migrate
	PYTHONPATH=src $(QT_PLATFORM) $(PYTHON) -m lan_streamer.main

typecheck:
	$(MYPY) src/

format:
	$(RUFF) format .

ruff-check:
	$(RUFF) check --fix .

lint: format ruff-check typecheck

reformat: format ruff-check

check-lint:
	$(RUFF) format --check .
	$(RUFF) check .

setup-git-hooks:
	$(PRE_COMMIT) install --hook-type commit-msg --hook-type pre-push --hook-type pre-commit

test:
	LAN_STREAMER_DB=./test_library.db PYTHONPATH=src $(PYTHON) -m alembic upgrade head
	LAN_STREAMER_DB=./test_library.db PYTHONPATH=src QT_QPA_PLATFORM=offscreen $(PYTEST) --cov-fail-under=90 -m "not load" tests/
	rm -f ./test_library.db ./test_library.db-wal ./test_library.db-shm

load-test: migrate
	PYTHONPATH=src QT_QPA_PLATFORM=offscreen $(PYTEST) -m "load" -s --no-cov tests/

test-ubuntu:
	$(CONTAINER_ENGINE) build -t lan-streamer-test-ubuntu -f docker/Dockerfile.ubuntu .
	$(CONTAINER_ENGINE) rm -f lan-streamer-test-ubuntu-run || true
	$(CONTAINER_ENGINE) run --name lan-streamer-test-ubuntu-run lan-streamer-test-ubuntu make test; \
	EXIT_CODE=$$?; \
	$(CONTAINER_ENGINE) cp lan-streamer-test-ubuntu-run:/app/.coverage ./coverage-results/ubuntu.coverage || true; \
	$(CONTAINER_ENGINE) rm -f lan-streamer-test-ubuntu-run; \
	if [ $$EXIT_CODE -eq 0 ]; then \
		$(MAKE) validate-ubuntu; \
		EXIT_CODE=$$?; \
	fi; \
	exit $$EXIT_CODE

test-fedora:
	$(CONTAINER_ENGINE) build -t lan-streamer-test-fedora -f docker/Dockerfile.fedora .
	$(CONTAINER_ENGINE) rm -f lan-streamer-test-fedora-run || true
	$(CONTAINER_ENGINE) run --name lan-streamer-test-fedora-run lan-streamer-test-fedora make test; \
	EXIT_CODE=$$?; \
	$(CONTAINER_ENGINE) cp lan-streamer-test-fedora-run:/app/.coverage ./coverage-results/fedora.coverage || true; \
	$(CONTAINER_ENGINE) rm -f lan-streamer-test-fedora-run; \
	if [ $$EXIT_CODE -eq 0 ]; then \
		$(MAKE) validate-fedora; \
		EXIT_CODE=$$?; \
	fi; \
	exit $$EXIT_CODE

validate-ubuntu:
	$(CONTAINER_ENGINE) run --rm -e LAN_STREAMER_DRY_RUN=1 -e QT_QPA_PLATFORM=offscreen lan-streamer-test-ubuntu ./dist/lan-streamer

validate-fedora:
	$(CONTAINER_ENGINE) run --rm -e LAN_STREAMER_DRY_RUN=1 -e QT_QPA_PLATFORM=offscreen lan-streamer-test-fedora ./dist/lan-streamer

validate-distros: validate-ubuntu validate-fedora

test-distros: test-ubuntu test-fedora

build:
	$(PYTHON) -m PyInstaller --onefile --paths src src/entrypoint.py --name lan-streamer

validate-executable: build
	LAN_STREAMER_DRY_RUN=1 QT_QPA_PLATFORM=offscreen ./dist/lan-streamer

clean:
	rm -rf build/ dist/ *.spec .pytest_cache .ruff_cache *.log *.db*
	find . -type d -name "__pycache__" -exec rm -rf {} +

revision:
	PYTHONPATH=src $(PYTHON) -m alembic revision --autogenerate -m "$(name)"

migrate:
	PYTHONPATH=src $(PYTHON) -m alembic upgrade head

release: check-lint typecheck test
	uv lock
	uv run cz bump
	uv lock
	git add uv.lock
	git commit --amend --no-edit
	git tag -d "$$(uv run cz version --project)" || true
	git tag -a "v$$(uv run cz version --project)" -m "Release v$$(uv run cz version --project)"
	git push origin main
	git push origin --tags

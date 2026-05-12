.PHONY: run lint check-lint reformat test load-test build-mac clean revision migrate release

UV := $(shell command -v uv 2> /dev/null)
ifeq ($(UV),)
	PYTHON := .venv/bin/python
	PYTEST := .venv/bin/pytest
	RUFF := .venv/bin/ruff
	MYPY := .venv/bin/mypy
else
	PYTHON := uv run python
	PYTEST := uv run pytest
	RUFF := uv run ruff
	MYPY := uv run mypy
endif
# Wayland detection for stable VLC embedding
ifeq ($(XDG_SESSION_TYPE),wayland)
    QT_PLATFORM := QT_QPA_PLATFORM=xcb
else
    QT_PLATFORM :=
endif

run: migrate
	PYTHONPATH=src $(QT_PLATFORM) $(PYTHON) -m lan_streamer.main

typecheck:
	$(MYPY) src/

lint: typecheck
	$(RUFF) format .
	$(RUFF) check --fix .

reformat: lint

check-lint: typecheck
	$(RUFF) format --check .
	$(RUFF) check .

test:
	LAN_STREAMER_DB=./test_library.db PYTHONPATH=src $(PYTHON) -m alembic upgrade head
	LAN_STREAMER_DB=./test_library.db PYTHONPATH=src QT_QPA_PLATFORM=offscreen $(PYTEST) --cov-fail-under=90 -m "not load" tests/
	rm -f ./test_library.db ./test_library.db-wal ./test_library.db-shm

load-test: migrate
	PYTHONPATH=src QT_QPA_PLATFORM=offscreen $(PYTEST) -m "load" -s --no-cov tests/

build-mac:
	uv run pyinstaller --name "Lan Streamer" --windowed --noconfirm src/lan_streamer/main.py

clean:
	rm -rf build/ dist/ *.spec .pytest_cache .ruff_cache *.log *.db*
	find . -type d -name "__pycache__" -exec rm -rf {} +

revision:
	PYTHONPATH=src $(PYTHON) -m alembic revision --autogenerate -m "$(name)"

migrate:
	PYTHONPATH=src $(PYTHON) -m alembic upgrade head

release: check-lint test
	uv lock
	uv run cz bump
	uv lock
	git add uv.lock
	git commit -m "chore: update lockfile for $$(uv run cz version --project)"
	git push origin main
	git push origin --tags

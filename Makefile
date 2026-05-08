.PHONY: run lint test load-test build-mac clean

UV := $(shell command -v uv 2> /dev/null)
ifeq ($(UV),)
	PYTHON := .venv/bin/python
	PYTEST := .venv/bin/pytest
	RUFF := .venv/bin/ruff
else
	PYTHON := uv run python
	PYTEST := uv run pytest
	RUFF := uv run ruff
endif

run:
	PYTHONPATH=src $(PYTHON) -m lan_streamer.main

lint:
	$(RUFF) format .
	$(RUFF) check --fix .

test:
	PYTHONPATH=src QT_QPA_PLATFORM=offscreen $(PYTEST) -m "not load" tests/

load-test:
	PYTHONPATH=src QT_QPA_PLATFORM=offscreen $(PYTEST) -m "load" -s --no-cov tests/

build-mac:
	uv run pyinstaller --name "Lan Streamer" --windowed --noconfirm src/lan_streamer/main.py

clean:
	rm -rf build/ dist/ *.spec .pytest_cache .ruff_cache .venv *.log
	find . -type d -name "__pycache__" -exec rm -rf {} +

release:
	uv lock
	uv run cz bump
	uv lock
	git add uv.lock
	git commit -m "chore: update lockfile for $$(uv run cz version --project)"
	git push origin main
	git push origin --tags

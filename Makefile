.PHONY: run lint test build-mac clean

run:
	PYTHONPATH=src uv run python -m lan_streamer.main

lint:
	uv run ruff format .
	uv run ruff check --fix .

test:
	PYTHONPATH=src uv run pytest tests/

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

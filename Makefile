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
	uv run cz bump
	git push origin main
	git push origin --tags

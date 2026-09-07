.PHONY: test lint format check-lint run

test:
	PYTHONPATH=../src:src uv run pytest

format:
	uv run ruff format .
	uv run ruff check --fix .

check-lint:
	uv run ruff format --check .
	uv run ruff check .

lint: check-lint
	uv run mypy src/

run:
	PYTHONPATH=../src:src uv run python -m scan_agent.serve

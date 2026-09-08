.PHONY: test lint format check-lint run run-local up down build

DOCKER_COMPOSE ?= $(shell if command -v docker-compose >/dev/null 2>&1; then echo docker-compose; elif command -v podman-compose >/dev/null 2>&1; then echo podman-compose; else echo "docker compose"; fi)

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

build:
	$(DOCKER_COMPOSE) build

run:
	mkdir -p media data
	$(DOCKER_COMPOSE) up --build

up:
	mkdir -p media data
	$(DOCKER_COMPOSE) up -d --build

down:
	$(DOCKER_COMPOSE) down

run-local:
	mkdir -p data
	SCAN_AGENT_CONFIG=./data/config.json PYTHONPATH=../src:src uv run python -m scan_agent.serve

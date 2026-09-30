.PHONY: lint-fix format all-check mypy test run run-mcp seed

lint-fix:
	uv run ruff check --fix .

format:
	uv run ruff format .

all-check:
	uv run ruff check .
	uv run ruff check --fix .
	uv run ruff format .

mypy:
	uv run mypy src tests

test:
	uv run pytest tests/

run:
	uv run uvicorn main:app --app-dir src --reload --host 127.0.0.1 --port 8000

run-mcp:
	uv run python src/mcp_server/main.py

seed:
	uv run python src/commands.py seed

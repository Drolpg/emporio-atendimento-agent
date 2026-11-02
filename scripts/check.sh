#!/bin/bash
set -euo pipefail

echo "Linting..."
uv run ruff check .

echo "Checking format..."
uv run ruff format --check .

echo "Running tests..."
uv run pytest

echo "All checks passed!"

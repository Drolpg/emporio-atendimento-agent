#!/bin/bash
set -euo pipefail

uv run ruff check .

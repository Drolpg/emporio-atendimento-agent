.PHONY: setup check test lint fmt

setup:
	uv sync

check:
	bash scripts/check.sh

test:
	bash scripts/test.sh

lint:
	bash scripts/lint.sh

fmt:
	bash scripts/fmt.sh

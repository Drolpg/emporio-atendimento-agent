.PHONY: setup check test lint fmt policies evals

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

policies:
	bash scripts/policies.sh

evals:
	bash scripts/evals.sh

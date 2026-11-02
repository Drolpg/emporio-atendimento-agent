.PHONY: setup check test lint fmt

setup:
	bash scripts/check.sh

check:
	bash scripts/check.sh

test:
	bash scripts/test.sh

lint:
	bash scripts/lint.sh

fmt:
	bash scripts/fmt.sh

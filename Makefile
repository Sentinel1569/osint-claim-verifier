.PHONY: install dev test lint demo serve clean

install:
	python -m venv .venv && .venv/bin/pip install -e ".[dev]"

test:
	OSINT_OFFLINE=1 pytest -q

lint:
	ruff check .

demo:
	OSINT_OFFLINE=1 python -m claimbench serve

serve:
	python -m claimbench serve

clean:
	rm -rf .cache .pytest_cache .ruff_cache *.egg-info **/__pycache__

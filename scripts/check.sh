#!/usr/bin/env bash
# Run the standard local checks: lint, tests, and supervisor self-test.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."

echo "== ruff =="
.venv/bin/ruff check src tests

echo "== pytest =="
.venv/bin/python -m pytest -q

echo "== supervisor selftest =="
bash .supervisor/selftest.sh

echo "all checks passed"

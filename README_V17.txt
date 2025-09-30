V17 — Packaging & CI + Tests

Includes:
- Makefile (dev/test/coverage/package)
- scripts/: run_dev.sh, run_tests.sh, package_zip.py
- tests/: chart_state, trade_validate, analytics overview, SSE smoke
- pyproject.toml and requirements-dev.txt

Usage:
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements-dev.txt
  make test
  make package   # -> dist/app.zip

.PHONY: help dev test coverage package clean
PY?=python3
help:
	@echo "make dev | make test | make coverage | make package | make clean"
dev:
	FLASK_DEBUG=1 FLASK_APP=server.py $(PY) -m flask run --port=5000
test:
	$(PY) -m pytest -q
coverage:
	$(PY) -m pytest --maxfail=1 --disable-warnings -q --cov=. --cov-report=term-missing
package:
	$(PY) scripts/package_zip.py
clean:
	rm -rf __pycache__ .pytest_cache .coverage dist

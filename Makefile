export PATH := $(CURDIR)/.tools/bin:$(PATH)
PYTHON ?= python3
VENV = .venv/bin/python
NPM ?= npm
NODE ?= node

.PHONY: install install-backend install-frontend doctor dev serve build lint typecheck test e2e backup
install: install-backend install-frontend
install-backend:
	$(PYTHON) -c 'import sys; assert sys.version_info >= (3,11), "Use Python >=3.11 (recommended conda Python 3.12)"'
	$(PYTHON) -m venv .venv
	$(VENV) -m pip install -r backend/requirements.lock
install-frontend:
	cd frontend && $(NPM) ci
	$(VENV) scripts/build_reader.py
doctor:
	$(VENV) scripts/doctor.py
dev:
	$(VENV) scripts/run.py dev
serve:
	$(VENV) scripts/run.py serve
build:
	cd frontend && $(NPM) run build
	$(VENV) scripts/build_reader.py
lint:
	.venv/bin/ruff check --config backend/pyproject.toml backend scripts tests
	cd frontend && $(NPM) run lint
typecheck:
	cd frontend && $(NPM) run typecheck
test:
	$(VENV) -m pytest tests -q
	cd frontend && $(NPM) test
e2e: build
	$(VENV) scripts/create_fixture.py
	cd frontend && $(NPM) run e2e
backup:
	$(VENV) scripts/backup.py backup

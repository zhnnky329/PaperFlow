export PATH := $(CURDIR)/.tools/bin:$(PATH)
unexport PYTHONPATH
PYTHON ?= python3
NPM ?= npm
NODE ?= node

.PHONY: install install-backend install-frontend doctor dev serve build lint typecheck test e2e backup
install: install-backend install-frontend
install-backend:
	$(PYTHON) -c 'import sys; assert sys.version_info >= (3,11), "Use Python >=3.11 (recommended conda Python 3.12)"'
	$(PYTHON) -c 'import sys; from pathlib import Path; assert sys.prefix != sys.base_prefix or (Path(sys.prefix) / "conda-meta").is_dir(), "Activate the paperflow conda environment or a virtualenv first"'
	$(PYTHON) -m pip install -r backend/requirements.lock
install-frontend:
	$(NODE) -e 'if (Number(process.versions.node.split(".")[0]) !== 24) { console.error("Use Node.js 24 in the paperflow environment"); process.exit(1); }'
	cd frontend && $(NPM) ci
	$(PYTHON) scripts/build_reader.py
doctor:
	$(PYTHON) scripts/doctor.py
dev:
	$(PYTHON) scripts/run.py dev
serve:
	$(PYTHON) scripts/run.py serve
build:
	cd frontend && $(NPM) run build
	$(PYTHON) scripts/build_reader.py
lint:
	$(PYTHON) -m ruff check --config backend/pyproject.toml backend scripts tests
	cd frontend && $(NPM) run lint
typecheck:
	cd frontend && $(NPM) run typecheck
test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest tests -q
	cd frontend && $(NPM) test
e2e: build
	$(PYTHON) scripts/create_fixture.py
	cd frontend && PAPERFLOW_PYTHON="$(PYTHON)" $(NPM) run e2e
backup:
	$(PYTHON) scripts/backup.py backup

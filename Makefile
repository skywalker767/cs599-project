.PHONY: install dev api ui test coverage benchmark demo lint format clean docker-dev docker-prod

PYTHON ?= python

# Cross-platform venv paths
ifeq ($(OS),Windows_NT)
    PY := $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python.exe,$(PYTHON))
    PIP := $(if $(wildcard .venv/Scripts/pip.exe),.venv/Scripts/pip.exe,$(PYTHON) -m pip)
    COPY_ENV = if not exist .env copy .env.example .env
    CLEAN_CMD = $(PY) -c "import pathlib,shutil; [p.unlink() for d in ['storage/generated','storage/diagrams'] if (p:=pathlib.Path(d)).exists() for p in p.glob('*')]; shutil.rmtree('.pytest_cache', ignore_errors=True)"
    DEMO_ENV = set IMAGE_PROVIDER=mock&& set LLM_PROVIDER=mock&& set DEMO_MODE=true&&
    BENCH_ENV = set IMAGE_PROVIDER=mock&& set LLM_PROVIDER=mock&& set DEMO_MODE=true&&
else
    PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,$(PYTHON))
    PIP := $(if $(wildcard .venv/bin/pip),.venv/bin/pip,$(PYTHON) -m pip)
    COPY_ENV = cp -n .env.example .env 2>/dev/null || true
    CLEAN_CMD = rm -f storage/generated/* storage/diagrams/* 2>/dev/null; rm -rf .pytest_cache
    DEMO_ENV = IMAGE_PROVIDER=mock LLM_PROVIDER=mock DEMO_MODE=true
    BENCH_ENV = IMAGE_PROVIDER=mock LLM_PROVIDER=mock DEMO_MODE=true
endif

install:
	$(PYTHON) -m venv .venv
	$(PIP) install -r requirements.txt
	@$(COPY_ENV)

dev:
	$(PY) run.py

api:
	$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

ui:
	$(PY) -m streamlit run app/ui/streamlit_app.py --server.port 8501

test:
	$(PY) -m pytest tests/ -v

coverage:
	$(PY) -m pytest tests/ --cov=app --cov-config=.coveragerc --cov-report=term-missing --cov-fail-under=80

benchmark:
	$(BENCH_ENV) $(PY) -m app.tools.benchmark

demo:
	$(DEMO_ENV) $(PY) scripts/run_demo.py

readme-examples:
	$(DEMO_ENV) $(PY) scripts/generate_readme_examples.py

lint:
	$(PY) -m ruff check app tests

format:
	$(PY) -m black app tests scripts

clean:
	$(CLEAN_CMD)

docker-dev:
	docker compose --profile dev up --build

docker-prod:
	docker compose --profile prod up --build -d

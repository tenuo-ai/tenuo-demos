.PHONY: help setup demo demo-injection demo-auto demo-auto-injection clean

help:
	@echo "Available targets:"
	@echo "  setup                Install dependencies into .venv"
	@echo "  demo                 Run the nominal scenario with the live approval UI"
	@echo "                       (UI auto-launches at http://localhost:5050)"
	@echo "  demo-injection       Run the injection scenario with the live approval UI"
	@echo "  demo-auto            Run the nominal scenario with simulated operator"
	@echo "                       (auto-approve after 2s; no UI needed)"
	@echo "  demo-auto-injection  Run the injection scenario with simulated operator"
	@echo "                       (auto-reject after 2s; no UI needed)"
	@echo "  clean                Remove .venv and caches"

setup:
	python -m venv .venv
	./.venv/bin/pip install --upgrade pip
	./.venv/bin/pip install -r requirements.txt
	@echo ""
	@echo "Setup complete. Next:"
	@echo "  1. In another terminal: temporal server start-dev"
	@echo "  2. make demo"

demo:
	./.venv/bin/python run.py --scenario nominal --no-auto-approve

demo-injection:
	./.venv/bin/python run.py --scenario injection --no-auto-approve

demo-auto:
	./.venv/bin/python run.py --scenario nominal

demo-auto-injection:
	./.venv/bin/python run.py --scenario injection

clean:
	rm -rf .venv .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

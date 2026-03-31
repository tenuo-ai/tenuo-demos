.PHONY: dev seed reset run dashboard lint build deploy

dev:
	docker compose up -d postgres opa
	@echo "Services started (postgres + OPA only). Run 'make seed' to populate the database."
	@echo "Note: 'docker compose up -d' (no args) also starts tenuo-authorizer, which needs TENUO_API_KEY."

seed:
	python -m db.seed

reset:
	python -m db.reset

run:
	@test -d agents || (echo "Error: agents/ not found. Run './scripts/switch-mode.sh baseline' or './scripts/switch-mode.sh with-tenuo' first." && exit 1)
	python -m agents.graph

dashboard:
	cd dashboard && npm run dev

lint:
	ruff check .
	ruff format --check .

fmt:
	ruff check --fix .
	ruff format .

build:
	docker compose build

deploy:
	./scripts/deploy.sh

clean:
	docker compose down -v
	@echo "All services stopped and volumes removed."

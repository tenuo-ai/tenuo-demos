.PHONY: dev seed reset run dashboard test lint build deploy

dev:
	docker compose up -d
	@echo "Services started. Run 'make seed' to populate the database."

seed:
	python -m db.seed

reset:
	python -m db.reset

run:
	python -m agents.graph

dashboard:
	cd dashboard && npm run dev

test:
	pytest tests/ -v

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

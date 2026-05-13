.PHONY: help setup dev test lint fmt clean logs

help:
	@grep -E '^[a-zA-Z_-]+:' Makefile | sed 's/:.*//'

setup:  ## First-time setup
	python -m venv .venv && source .venv/bin/activate && pip install -e "backend[dev,test]"
	cd frontend && npm ci
	cp .env.example .env
	docker compose --profile dev up -d
	@echo "Setup complete. Run 'make dev' to start."

dev:  ## Start development environment
	docker compose --profile dev up -d
	cd frontend && npm run dev &
	source .venv/bin/activate && uvicorn backend.main:app --reload --port 8000

test:  ## Run test suite
	docker compose --profile test up -d
	sleep 5
	docker compose exec backend pytest backend/tests/unit backend/tests/integration -q --tb=short

lint:  ## Lint + type-check
	ruff check backend/ --fix
	mypy backend/ --ignore-missing-imports
	cd frontend && npm run lint

fmt:  ## Format code
	ruff format backend/
	cd frontend && npm run format

logs:  ## Tail backend logs
	docker compose logs -f backend

clean:  ## Remove containers + volumes
	docker compose down -v --remove-orphans
	rm -rf frontend/node_modules .venv

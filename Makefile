.PHONY: help setup dev dev-host dev-down test lint fmt clean logs docker-up docker-down migrate

help:
	@grep -E '^[a-zA-Z_-]+:' Makefile | sed 's/:.*//'

setup:  ## First-time setup
	python -m venv .venv && source .venv/bin/activate && pip install -e "backend[dev,test]"
	cd frontend && npm ci
	cp .env.example .env
	docker compose --profile dev up -d
	@echo "Setup complete. Run 'make dev' to start."

dev:  ## Start full dev stack via compose (backend + frontend_dev + chroma + ollama)
	docker compose --profile dev up -d --build
	@echo ""
	@echo "Frontend (Vite HMR):  http://127.0.0.1:5173"
	@echo "Backend API:          http://127.0.0.1:8000"
	@echo "Backend health:       http://127.0.0.1:8000/health"
	@echo ""
	@echo "Tail logs with:  make logs"
	@echo "Stop with:       make dev-down"

dev-host:  ## Start backend in compose, frontend on host (faster HMR, requires local node)
	docker compose --profile dev up -d backend chroma ollama
	cd frontend && npm run dev &
	source .venv/bin/activate && uvicorn backend.main:app --reload --port 8000

dev-down:  ## Stop the dev stack
	docker compose --profile dev down

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

logs:  ## Tail backend + frontend logs
	docker compose logs -f backend frontend_dev

docker-up:  ## Start all Docker containers
	docker compose up -d

docker-down:  ## Stop all Docker containers
	docker compose down

migrate:  ## Run PGLite migrations (Alembic)
	docker compose run --rm backend alembic upgrade head

clean:  ## Remove containers + volumes
	docker compose down -v --remove-orphans
	rm -rf frontend/node_modules .venv

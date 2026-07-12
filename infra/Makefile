# Infra — Legal GraphRAG

.PHONY: up down logs status init-schema shell-neo4j clean m3-up m3-status m3-init-schema m3-verify-schema m3-write m3-snapshot m3-embed m3-vector-smoke m3-graph-quality m3-integration m3-reset m3-down m3-logs

# Load .env nếu tồn tại
ifneq (,$(wildcard .env))
  include .env
  export
endif

NEO4J_PASSWORD ?= changeme_strong_password
UV_CACHE_DIR ?= $(abspath ../.cache/uv)
export UV_CACHE_DIR

## ─── Docker ──────────────────────────────────────────────────────────────────

up: _check_env
	@echo "🚀 Starting Neo4j..."
	docker compose up -d
	@echo "⏳ Waiting for Neo4j to be healthy..."
	@until docker inspect graphrag-neo4j --format='{{.State.Health.Status}}' 2>/dev/null | grep -q healthy; do \
		printf '.'; sleep 3; \
	done
	@echo ""
	@echo "✅ Neo4j is ready at http://localhost:7474"

_check_env:
	@if [ ! -f .env ]; then \
		echo "❌ File .env không tồn tại. Chạy: cp .env.example .env rồi điền NEO4J_PASSWORD."; \
		exit 1; \
	fi
	@if grep -q 'NEO4J_PASSWORD=changeme' .env; then \
		echo "⚠️  NEO4J_PASSWORD vẫn là default. Đổi password trong .env trước khi tiếp tục."; \
		exit 1; \
	fi
	@if [ -z "$$(grep NEO4J_PASSWORD .env | cut -d= -f2)" ]; then \
		echo "❌ NEO4J_PASSWORD chưa được set trong .env."; \
		exit 1; \
	fi

down:
	docker compose down

logs:
	docker compose logs -f neo4j

status:
	@docker inspect graphrag-neo4j --format='Status: {{.State.Status}} | Health: {{.State.Health.Status}}' 2>/dev/null || echo "Container not running"

## ─── Schema ──────────────────────────────────────────────────────────────────

init-schema:
	@echo "📐 Applying Neo4j schema (constraints + indexes + vector indexes)..."
	@docker exec -i graphrag-neo4j cypher-shell \
		-u neo4j \
		-p "$(NEO4J_PASSWORD)" \
		--format plain \
		< neo4j/init/01_schema_init.cypher
	@echo "✅ Schema applied. Run 'make verify-schema' to confirm."

verify-schema:
	@echo "🔍 Constraints:"
	@docker exec graphrag-neo4j cypher-shell \
		-u neo4j -p "$(NEO4J_PASSWORD)" --format plain \
		"SHOW CONSTRAINTS YIELD name, type, labelsOrTypes RETURN name, type, labelsOrTypes;"
	@echo ""
	@echo "🔍 Indexes (including vector):"
	@docker exec graphrag-neo4j cypher-shell \
		-u neo4j -p "$(NEO4J_PASSWORD)" --format plain \
		"SHOW INDEXES YIELD name, type, state, labelsOrTypes RETURN name, type, state, labelsOrTypes ORDER BY type, name;"

## ─── Debug ───────────────────────────────────────────────────────────────────

shell-neo4j:
	@docker exec -it graphrag-neo4j cypher-shell -u neo4j -p "$(NEO4J_PASSWORD)"

## ─── Cleanup ─────────────────────────────────────────────────────────────────

clean:
	@echo "⚠️  This will remove all Neo4j data volumes!"
	@read -p "Are you sure? [y/N] " confirm; \
	if [ "$$confirm" = "y" ]; then \
		docker compose down -v; \
		echo "✅ Volumes removed."; \
	else \
		echo "Aborted."; \
	fi

## ─── Disposable M3 Runtime ──────────────────────────────────────────────────

M3_COMPOSE = docker compose --project-name graphrag-m3 -f docker-compose.m3.yml
RAW_DOC_CODE ?= L59_2020
OUTPUT ?= snapshot.json

m3-up: _check_env
	@$(M3_COMPOSE) up -d neo4j-m3
	@echo "Waiting for graphrag-neo4j-m3..."
	@until [ "$$(docker inspect graphrag-neo4j-m3 --format='{{.State.Health.Status}}' 2>/dev/null)" = "healthy" ]; do printf '.'; sleep 2; done
	@echo "\nM3 Neo4j ready: http://localhost:7475 / bolt://localhost:7688"

m3-status:
	@docker inspect graphrag-neo4j-m3 --format='Status: {{.State.Status}} | Health: {{.State.Health.Status}} | Image: {{.Config.Image}}' 2>/dev/null || echo "M3 container not running"

m3-init-schema: _check_env
	@docker exec -i graphrag-neo4j-m3 cypher-shell -u neo4j -p "$(NEO4J_PASSWORD)" --format plain < neo4j/init/01_schema_init.cypher

m3-verify-schema: _check_env
	@cd .. && NEO4J_URI=bolt://localhost:7688 uv run python -m src.pipeline.main verify-m3-schema

m3-write: _check_env
	@cd .. && NEO4J_URI=bolt://localhost:7688 uv run python -m src.pipeline.main write --raw-doc-code "$(RAW_DOC_CODE)"

m3-snapshot: _check_env
	@cd .. && NEO4J_URI=bolt://localhost:7688 uv run python -m src.pipeline.main graph-snapshot --raw-doc-code "$(RAW_DOC_CODE)" --output "$(OUTPUT)"

m3-embed: _check_env
	@cd .. && NEO4J_URI=bolt://localhost:7688 uv run python -m src.pipeline.main embed --raw-doc-code "$(RAW_DOC_CODE)" --batch-size 32

m3-vector-smoke: _check_env
	@cd .. && NEO4J_URI=bolt://localhost:7688 uv run python -m src.pipeline.main vector-smoke --raw-doc-code "$(RAW_DOC_CODE)"

m3-graph-quality: _check_env
	@cd .. && NEO4J_URI=bolt://localhost:7688 uv run python -m src.pipeline.main graph-quality --raw-doc-code "$(RAW_DOC_CODE)"

m3-integration: _check_env
	@cd .. && RUN_NEO4J_INTEGRATION=1 NEO4J_URI=bolt://localhost:7688 uv run pytest tests/integration -q -m integration

m3-reset:
	@bash scripts/m3-reset.sh

m3-down:
	@$(M3_COMPOSE) down

m3-logs:
	@$(M3_COMPOSE) logs -f neo4j-m3

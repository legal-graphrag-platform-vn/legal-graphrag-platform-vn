# Infra — Legal GraphRAG

.PHONY: up down logs status init-schema shell-neo4j clean

# Load .env nếu tồn tại
ifneq (,$(wildcard .env))
  include .env
  export
endif

NEO4J_PASSWORD ?= changeme_strong_password

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

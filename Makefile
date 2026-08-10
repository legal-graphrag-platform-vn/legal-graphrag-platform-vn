
.PHONY: dev-fe dev-be test conversation-db-up conversation-db-status conversation-db-down test-conversation-db setup-ssh deploy help

CONVERSATION_TEST_COMPOSE = docker compose --project-name graphrag-conversation-test -f infra/docker-compose.test.yml
CONVERSATION_TEST_DATABASE_URL ?= postgresql+asyncpg://graphrag_test:graphrag_test@127.0.0.1:55432/graphrag_conversations_test

help:
	@echo "Các lệnh hỗ trợ:"
	@echo "  make dev-fe     - Chạy Frontend (Next.js)"
	@echo "  make dev-be     - Chạy Backend (FastAPI mock mode)"
	@echo "  make test       - Chạy contract tests cho Backend"
	@echo "  make conversation-db-up   - Start PostgreSQL test disposable"
	@echo "  make test-conversation-db - Chạy conversation integration tests"
	@echo "  make conversation-db-down - Stop PostgreSQL test disposable"
	@echo "  make setup-ssh  - Khởi tạo SSH Key & đẩy sang Remote Server"
	@echo "  make deploy     - Triển khai ứng dụng lên Remote Server qua SSH"

dev-fe:
	cd apps/frontend && npm run dev

dev-be:
	cd apps/backend && APP_MODE=mock PYTHONPATH=. uv run uvicorn main:app --reload --port 8000

test:
	cd apps/backend && PYTHONPATH=. uv run pytest tests/ -v

conversation-db-up:
	$(CONVERSATION_TEST_COMPOSE) up -d --wait postgres-test

conversation-db-status:
	$(CONVERSATION_TEST_COMPOSE) ps postgres-test

conversation-db-down:
	$(CONVERSATION_TEST_COMPOSE) down

test-conversation-db: conversation-db-up
	CONVERSATION_TEST_DATABASE_URL="$(CONVERSATION_TEST_DATABASE_URL)" .venv/bin/pytest -q apps/backend/tests/conversation

setup-ssh:
	./infra/scripts/setup-ssh-key.sh

deploy:
	./infra/scripts/deploy-ssh.sh

.PHONY: dev-fe dev-be test help

help:
	@echo "Các lệnh hỗ trợ:"
	@echo "  make dev-fe   - Chạy Frontend (Next.js)"
	@echo "  make dev-be   - Chạy Backend (FastAPI mock mode)"
	@echo "  make test     - Chạy contract tests cho Backend"

dev-fe:
	cd apps/frontend && npm run dev

dev-be:
	cd apps/backend && APP_MODE=mock PYTHONPATH=. uv run uvicorn main:app --reload --port 8000

test:
	cd apps/backend && PYTHONPATH=. uv run pytest tests/ -v

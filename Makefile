
.PHONY: dev-fe dev-be test setup-ssh deploy help

help:
	@echo "Các lệnh hỗ trợ:"
	@echo "  make dev-fe     - Chạy Frontend (Next.js)"
	@echo "  make dev-be     - Chạy Backend (FastAPI mock mode)"
	@echo "  make test       - Chạy contract tests cho Backend"
	@echo "  make setup-ssh  - Khởi tạo SSH Key & đẩy sang Remote Server"
	@echo "  make deploy     - Triển khai ứng dụng lên Remote Server qua SSH"

dev-fe:
	cd apps/frontend && npm run dev

dev-be:
	cd apps/backend && APP_MODE=mock PYTHONPATH=. uv run uvicorn main:app --reload --port 8000

test:
	cd apps/backend && PYTHONPATH=. uv run pytest tests/ -v

setup-ssh:
	./infra/scripts/setup-ssh-key.sh

deploy:
	./infra/scripts/deploy-ssh.sh


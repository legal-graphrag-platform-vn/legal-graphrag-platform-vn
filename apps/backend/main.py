"""
FastAPI entrypoint — App factory pattern.
Settings được tạo 1 lần duy nhất và inject vào toàn bộ app.
Flask app.py được giữ nguyên cho đến khi SSE parity test pass.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.error_handlers import register_error_handlers
from api.routes import chat, documents, query
from container import build_container
from settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    App factory. Nhận optional Settings để test inject mock settings.

    Ví dụ trong test:
        from main import create_app
        from settings import Settings
        app = create_app(Settings(app_mode="mock"))
        client = TestClient(app)

    Không cần monkeypatch environment.
    """
    # 1.   Tạo settings một lần duy nhất — không tạo lại ở bất kỳ đâu khác
    settings = settings or Settings()
    settings.validate_runtime()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 2.   Startup: build container và lưu vào app.state
        container = await build_container(settings)
        app.state.container = container
        try:
            yield
        finally:
            # 3.   Shutdown: đóng resources (Neo4j driver khi graphrag mode)
            await container.close()

    app = FastAPI(
        title="Legal GraphRAG API",
        version="1.0.0",
        description="Legal knowledge graph RAG backend — Vietnamese enterprise law.",
        lifespan=lifespan,
    )

    # 4.   CORS — chỉ allow origins đã cấu hình, không dùng ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 5.   Stable request/domain error envelopes
    register_error_handlers(app)

    # 6.   Routes — tất cả prefix /api/v1
    app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
    app.include_router(query.router, prefix="/api/v1", tags=["query"])
    app.include_router(documents.router, prefix="/api/v1", tags=["documents"])

    return app


# 7.   Module-level app instance cho uvicorn:
# uvicorn apps.backend.main:app --reload
# hoặc từ repo root: cd apps/backend && uvicorn main:app --reload
app = create_app()

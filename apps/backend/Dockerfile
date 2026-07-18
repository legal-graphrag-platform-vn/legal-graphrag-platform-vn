FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/apps/backend \
    PATH=/app/.venv/bin:$PATH

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group embedding --group llm --no-install-project

COPY src ./src
COPY apps/backend ./apps/backend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--app-dir", "apps/backend", "--host", "0.0.0.0", "--port", "8000"]

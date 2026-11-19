FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN python -m pip install --no-cache-dir uv==0.11.8
COPY pyproject.toml uv.lock ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY start-render.sh ./start-render.sh
RUN uv sync --locked --no-dev

RUN chmod 755 /app/start-render.sh \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

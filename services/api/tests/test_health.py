import asyncio

import httpx

from app.api.routes import health
from app.main import app


def get(path: str) -> httpx.Response:
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def test_liveness_reports_running_process() -> None:
    response = get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_database_dependency(monkeypatch) -> None:
    monkeypatch.setattr(health, "database_is_ready", lambda: True)

    response = get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ready"}


def test_readiness_fails_when_database_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(health, "database_is_ready", lambda: False)

    response = get("/api/v1/health/ready")

    assert response.status_code == 503

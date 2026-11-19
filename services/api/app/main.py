from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Assessment delivery, course reporting, and consent-based review API.",
    docs_url=None if settings.app_env.lower() in {"production", "prod"} else "/docs",
    redoc_url=None if settings.app_env.lower() in {"production", "prod"} else "/redoc",
    openapi_url=None if settings.app_env.lower() in {"production", "prod"} else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-CSRF-Token",
        "X-Event-Key",
    ],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)

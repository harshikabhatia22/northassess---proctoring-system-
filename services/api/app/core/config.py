from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Assessment Proctoring API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = (
        "postgresql+psycopg://proctoring:local-development-only@localhost:5432/proctoring"
    )
    jwt_secret_key: str = "development-only-change-this-secret"
    jwt_issuer: str = "northstar-assess"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = False
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def require_production_secret(self) -> "Settings":
        if self.app_env.lower() in {"production", "prod"}:
            if len(self.jwt_secret_key) < 32 or self.jwt_secret_key in {
                "development-only-change-this-secret",
                "local-development-secret-change-before-deployment-000000000000",
            }:
                raise ValueError(
                    "Production requires a unique JWT_SECRET_KEY of at least 32 characters"
                )
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS must list specific trusted origins in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

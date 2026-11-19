import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_rejects_development_secret():
    with pytest.raises(ValidationError, match="unique JWT_SECRET_KEY"):
        Settings(
            app_env="production",
            jwt_secret_key="local-development-secret-change-before-deployment-000000000000",
            cookie_secure=True,
            cors_origins=["https://assess.example"],
        )


def test_production_requires_secure_cookie_and_explicit_origin():
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        Settings(
            app_env="production",
            jwt_secret_key="a-unique-production-key-with-more-than-32-characters",
            cookie_secure=False,
            cors_origins=["https://assess.example"],
        )
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        Settings(
            app_env="production",
            jwt_secret_key="a-unique-production-key-with-more-than-32-characters",
            cookie_secure=True,
            cors_origins=["*"],
        )

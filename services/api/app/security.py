import hmac
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import RefreshSession, User

password_hasher = PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=2)
bearer_scheme = HTTPBearer(auto_error=False)
REFRESH_COOKIE = "refresh_token"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FIELD = "csrf_token"


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def utc_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def issue_access_token(user_id: str) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    lifetime = settings.access_token_minutes * 60
    token = jwt.encode(
        {
            "sub": user_id,
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + timedelta(seconds=lifetime),
            "type": "access",
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )
    return token, lifetime


def create_refresh_session(db: Session, user_id: str) -> tuple[RefreshSession, str, str]:
    settings = get_settings()
    token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    session = RefreshSession(
        user_id=user_id,
        token_hash=digest(token),
        csrf_hash=digest(csrf_token),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
    )
    db.add(session)
    return session, token, csrf_token


def set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=settings.refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api/v1/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="strict",
        path="/api/v1/auth",
    )


def verify_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin not in get_settings().cors_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted request origin"
        )


def require_csrf(request: Request, expected_hash: str) -> None:
    candidate = request.headers.get(CSRF_HEADER, "")
    if not candidate or not hmac.compare_digest(digest(candidate), expected_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        claims = jwt.decode(
            credentials.credentials,
            get_settings().jwt_secret_key,
            algorithms=["HS256"],
            issuer=get_settings().jwt_issuer,
            options={"require": ["exp", "iat", "iss", "sub", "type"]},
        )
    except jwt.InvalidTokenError:
        raise unauthorized from None
    if claims.get("type") != "access":
        raise unauthorized
    user = db.scalar(select(User).where(User.id == claims["sub"]))
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_roles(*allowed: str):
    def role_check(user: User = Depends(current_user)) -> User:
        if not any(role.name in allowed for role in user.roles):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return role_check


def find_refresh_session(db: Session, raw_token: str) -> RefreshSession | None:
    return db.scalar(select(RefreshSession).where(RefreshSession.token_hash == digest(raw_token)))

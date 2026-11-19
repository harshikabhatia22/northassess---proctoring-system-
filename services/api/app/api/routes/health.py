from fastapi import APIRouter, HTTPException, status

from app.db.session import database_is_ready

router = APIRouter()


@router.get("/live", summary="Process liveness")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Service readiness")
def ready() -> dict[str, str]:
    if not database_is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        )
    return {"status": "ready", "database": "ready"}

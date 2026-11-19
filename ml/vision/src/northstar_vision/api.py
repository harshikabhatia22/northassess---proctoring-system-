"""Private FastAPI wrapper for versioned vision inference."""

from __future__ import annotations

import asyncio
import hmac
import os
import threading

from fastapi import FastAPI, Header, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from northstar_vision.inference import MAX_IMAGE_BYTES, infer_image_bytes, load_model_bundle

app = FastAPI(
    title="Northstar Vision Inference",
    version="1.0.0",
    description="Private low-stakes visual observation inference API.",
)
MODEL_PATH = os.environ.get("VISION_MODEL_PATH", "")
SERVICE_KEY = os.environ.get("VISION_INTERNAL_API_KEY", "")
_model: dict | None = None
_model_error: str | None = None
_INFERENCE_TIMEOUT_SECONDS = 5.0
_INFERENCE_SLOTS = threading.BoundedSemaphore(value=2)
_ASYNC_TIMEOUT_ERROR = asyncio.TimeoutError


@app.on_event("startup")
def load_configured_model() -> None:
    global _model, _model_error
    if not MODEL_PATH:
        _model_error = "VISION_MODEL_PATH is not configured"
        return
    try:
        _model = load_model_bundle(MODEL_PATH)
        _model_error = None
    except Exception:  # noqa: BLE001 - a bad artifact must not crash service startup
        _model = None
        _model_error = "Configured vision model could not be loaded"


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/health/ready")
def ready() -> dict[str, str]:
    if _model is None:
        raise HTTPException(status_code=503, detail="Vision model is unavailable")
    return {"status": "ready", "model_id": _model["model_id"]}


@app.post("/api/v1/detect")
async def detect(
    request: Request,
    x_internal_api_key: str = Header(default="", alias="X-Internal-API-Key"),
) -> dict:
    if not SERVICE_KEY:
        raise HTTPException(status_code=503, detail="Vision inference service is not configured")
    if not hmac.compare_digest(x_internal_api_key, SERVICE_KEY):
        raise HTTPException(status_code=401, detail="Invalid service credential")
    if _model is None:
        raise HTTPException(status_code=503, detail="Vision model is unavailable")
    media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if media_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(status_code=415, detail="Content-Type must be image/jpeg or image/png")
    chunks: list[bytes] = []
    body_size = 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image exceeds the 4 MiB request limit")
        chunks.append(chunk)
    body = b"".join(chunks)
    if not _INFERENCE_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="Vision inference is busy")

    def infer_and_release() -> dict:
        try:
            return infer_image_bytes(_model, body)
        finally:
            _INFERENCE_SLOTS.release()

    inference_task = asyncio.create_task(run_in_threadpool(infer_and_release))
    try:
        return await asyncio.wait_for(
            asyncio.shield(inference_task), timeout=_INFERENCE_TIMEOUT_SECONDS
        )
    except _ASYNC_TIMEOUT_ERROR as exc:
        raise HTTPException(status_code=504, detail="Vision inference timed out") from exc
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Inference failed"
        ) from exc

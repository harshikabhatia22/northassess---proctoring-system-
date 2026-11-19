"""Versioned, bounded image inference contract for the trained vision baseline."""

from __future__ import annotations

import time
from typing import Any

import cv2
import joblib
import numpy as np

from northstar_vision.training import _detect_class

MODEL_ID = "northstar-hog-linear-svm-detector-v3"
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_PIXELS = 8_000_000
MODEL_EDGE = 640


def load_model_bundle(path: str) -> dict[str, Any]:
    """Load a locally produced model artifact and verify its schema identifier."""
    bundle = joblib.load(path)
    if not isinstance(bundle, dict) or bundle.get("model_id") != MODEL_ID:
        raise ValueError("Unsupported or invalid vision model artifact")
    required = {"class_names", "models", "windows", "median_sizes", "source_archive_sha256"}
    if not required.issubset(bundle):
        raise ValueError("Vision model artifact is missing required fields")
    if len(bundle["models"]) != len(bundle["class_names"]):
        raise ValueError("Vision model class schema is inconsistent")
    return bundle


def infer_image_bytes(bundle: dict[str, Any], data: bytes) -> dict[str, Any]:
    """Detect visible behavior labels in one JPEG/PNG, returning source-pixel boxes."""
    if not data:
        raise ValueError("Image body is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise OverflowError("Image exceeds the 4 MiB request limit")
    start = time.perf_counter()
    encoded = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("Image is corrupt or uses an unsupported encoding")
    original_h, original_w = image.shape[:2]
    if original_w * original_h > MAX_PIXELS:
        raise OverflowError("Image dimensions exceed the 8 megapixel limit")
    if float(np.std(image)) < 1.0:
        return {
            "api_version": "v1",
            "model_id": bundle["model_id"],
            "source_archive_sha256": bundle["source_archive_sha256"],
            "observation_semantics": "Visible behavior annotations only; not a misconduct determination.",
            "image_size": {"width": original_w, "height": original_h},
            "processing_status": "no_visual_signal",
            "detections": [],
            "inference_latency_ms": round((time.perf_counter() - start) * 1000, 3),
            "latency_includes_decode_and_resize": True,
        }
    scale = min(MODEL_EDGE / original_w, MODEL_EDGE / original_h)
    resized_w, resized_h = max(1, round(original_w * scale)), max(1, round(original_h * scale))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (resized_w, resized_h), interpolation=interpolation)
    left = (MODEL_EDGE - resized_w) // 2
    top = (MODEL_EDGE - resized_h) // 2
    canvas = cv2.copyMakeBorder(
        resized,
        top,
        MODEL_EDGE - resized_h - top,
        left,
        MODEL_EDGE - resized_w - left,
        cv2.BORDER_CONSTANT,
        value=114,
    )
    results: list[dict[str, Any]] = []
    for class_id, class_name in enumerate(bundle["class_names"]):
        window = tuple(bundle["windows"][class_id])
        median_size = tuple(bundle["median_sizes"][class_id])
        detections = _detect_class(
            canvas,
            bundle["models"][class_id],
            window,
            median_size,
            tuple(bundle["scale_factors"]),
        )
        for item in detections:
            if item["score"] < 0.0:
                continue
            x1, y1, x2, y2 = item["box"]
            x1 = min(original_w, max(0.0, (x1 - left) / scale))
            x2 = min(original_w, max(0.0, (x2 - left) / scale))
            y1 = min(original_h, max(0.0, (y1 - top) / scale))
            y2 = min(original_h, max(0.0, (y2 - top) / scale))
            if x2 <= x1 or y2 <= y1:
                continue
            results.append(
                {
                    "class_id": class_id,
                    "class_name": class_name,
                    "score": item["score"],
                    "box_xyxy": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                }
            )
    results.sort(key=lambda item: item["score"], reverse=True)
    return {
        "api_version": "v1",
        "model_id": bundle["model_id"],
        "source_archive_sha256": bundle["source_archive_sha256"],
        "observation_semantics": "Visible behavior annotations only; not a misconduct determination.",
        "image_size": {"width": original_w, "height": original_h},
        "processing_status": "ok",
        "detections": results,
        "inference_latency_ms": round((time.perf_counter() - start) * 1000, 3),
        "latency_includes_decode_and_resize": True,
    }

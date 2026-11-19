"""Original HOG + linear-SVM multi-class sliding-window detector."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import re
import statistics
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

import cv2
import joblib
import numpy as np
import sklearn
from sklearn.svm import LinearSVC

HOG_EDGE = 128
HOG_STRIDE = 32
MODEL_ID = "northstar-hog-linear-svm-detector-v3"
SCALE_FACTORS = (0.64, 0.82, 1.0, 1.22, 1.56)
NEGATIVE_WINDOWS_PER_IMAGE = 1
HARD_NEGATIVE_IMAGES_PER_GROUP = 12
HARD_NEGATIVES_PER_IMAGE = 3
HARD_NEGATIVES_PER_GROUP = 20
DETECTIONS_PER_CLASS_IMAGE = 100
INVALID_BOXES = "zero-width-or-height"


def _base_name(path: str) -> str:
    name = PurePosixPath(path).name
    while name.lower().endswith((".jpg", ".jpeg", ".png", ".txt")):
        name = name[: name.rfind(".")]
    return name


def source_group(path: str) -> str:
    """Use the filename prefix before the final frame number as a proxy group."""
    name = _base_name(path)
    match = re.fullmatch(r"(.*?)[ _](\d+)", name)
    if not match:
        raise ValueError(f"Cannot derive a filename source group from {path!r}")
    return match.group(1)


def _valid_box(
    class_id: int, values: list[float], image_w: int, image_h: int
) -> dict[str, Any] | None:
    if len(values) != 4 or any(not np.isfinite(v) or v < 0 or v > 1 for v in values):
        return None
    xc, yc, width, height = values
    if width <= 0 or height <= 0:
        return None
    x1 = max(0.0, (xc - width / 2) * image_w)
    y1 = max(0.0, (yc - height / 2) * image_h)
    x2 = min(float(image_w), (xc + width / 2) * image_w)
    y2 = min(float(image_h), (yc + height / 2) * image_h)
    if x2 <= x1 or y2 <= y1:
        return None
    return {"class_id": class_id, "box": [x1, y1, x2, y2]}


def read_records(archive_path: str) -> tuple[list[dict[str, Any]], list[str], int]:
    """Load labeled train/valid samples, excluding unlabeled test files and invalid boxes."""
    records: list[dict[str, Any]] = []
    invalid_box_count = 0
    with zipfile.ZipFile(archive_path) as archive:
        members = set(archive.namelist())
        class_path = next(
            name for name in members if PurePosixPath(name).name.lower() == "classes.txt"
        )
        class_names = [
            line.strip()
            for line in archive.read(class_path).decode("utf-8-sig").splitlines()
            if line.strip()
        ]
        images = sorted(
            name
            for name in members
            if "/images/" in name
            and "/test/" not in name
            and PurePosixPath(name).suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        for image_path in images:
            label_path = str(
                PurePosixPath(image_path.replace("/images/", "/labels/")).with_suffix(".txt")
            )
            if label_path not in members:
                continue
            data = np.frombuffer(archive.read(image_path), dtype=np.uint8)
            image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise ValueError(f"Image cannot be decoded: {image_path}")
            height, width = image.shape[:2]
            boxes = []
            for line_number, line in enumerate(
                archive.read(label_path).decode("utf-8-sig").splitlines(), 1
            ):
                values = line.split()
                if not values:
                    continue
                if len(values) != 5:
                    raise ValueError(f"Malformed YOLO label {label_path}:{line_number}")
                class_id = int(values[0])
                if class_id < 0 or class_id >= len(class_names):
                    raise ValueError(f"Unknown class id {class_id} in {label_path}:{line_number}")
                box = _valid_box(class_id, list(map(float, values[1:])), width, height)
                if box is None:
                    invalid_box_count += 1
                    continue
                boxes.append(box)
            records.append(
                {
                    "image_path": image_path,
                    "label_path": label_path,
                    "source_group": source_group(image_path),
                    "width": width,
                    "height": height,
                    "boxes": boxes,
                }
            )
    return records, class_names, invalid_box_count


def grouped_holdout(
    records: list[dict[str, Any]], seed: int = 42, fraction: float = 0.2
) -> dict[str, Any]:
    """Select a deterministic source-name-group holdout with class support in each side."""
    group_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    group_classes: dict[str, Counter[int]] = defaultdict(Counter)
    total_classes: Counter[int] = Counter()
    for record in records:
        group = record["source_group"]
        group_records[group].append(record)
        for box in record["boxes"]:
            group_classes[group][box["class_id"]] += 1
            total_classes[box["class_id"]] += 1
    groups = sorted(group_records)
    holdout_count = max(2, round(len(groups) * fraction))
    required_classes = set(total_classes)
    rng = random.Random(seed)
    best: tuple[float, tuple[str, ...]] | None = None
    for _ in range(25000):
        selected = tuple(sorted(rng.sample(groups, holdout_count)))
        holdout_counts = Counter()
        for group in selected:
            holdout_counts.update(group_classes[group])
        if set(holdout_counts) != required_classes or any(
            holdout_counts[c] >= total_classes[c] for c in required_classes
        ):
            continue
        n_holdout = sum(len(group_records[group]) for group in selected)
        image_fraction = n_holdout / len(records)
        class_error = sum(
            abs(holdout_counts[c] / total_classes[c] - fraction) for c in required_classes
        )
        score = class_error + 2 * abs(image_fraction - fraction)
        if best is None or score < best[0]:
            best = (score, selected)
    if best is None:
        raise ValueError(
            "Could not find a source-group holdout containing every class on both sides"
        )
    test_groups = set(best[1])
    train_records = [r for r in records if r["source_group"] not in test_groups]
    test_records = [r for r in records if r["source_group"] in test_groups]
    return {
        "seed": seed,
        "grouping": "filename prefix before final frame number; provisional recording proxy, not participant ID",
        "target_test_fraction": fraction,
        "train_groups": sorted({r["source_group"] for r in train_records}),
        "test_groups": sorted(test_groups),
        "train_images": len(train_records),
        "test_images": len(test_records),
        "train_records": train_records,
        "test_records": test_records,
    }


def _class_window(records: list[dict[str, Any]], class_id: int) -> tuple[int, int, float, float]:
    widths: list[float] = []
    heights: list[float] = []
    for record in records:
        for item in record["boxes"]:
            if item["class_id"] == class_id:
                x1, y1, x2, y2 = item["box"]
                widths.append(x2 - x1)
                heights.append(y2 - y1)
    median_w = statistics.median(widths)
    median_h = statistics.median(heights)
    ratio = HOG_EDGE / max(median_w, median_h)
    window_w = max(64, round(median_w * ratio / 8) * 8)
    window_h = max(64, round(median_h * ratio / 8) * 8)
    return window_w, window_h, median_w, median_h


def _crop(
    image: np.ndarray, box: tuple[float, float, float, float], context: float = 1.0
) -> np.ndarray:
    x1, y1, x2, y2 = box
    center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
    width, height = (x2 - x1) * context, (y2 - y1) * context
    left = max(0, int(center_x - width / 2))
    right = min(image.shape[1], int(center_x + width / 2))
    top = max(0, int(center_y - height / 2))
    bottom = min(image.shape[0], int(center_y + height / 2))
    return image[top:bottom, left:right]


def _descriptor(hog: cv2.HOGDescriptor, patch: np.ndarray, win_size: tuple[int, int]) -> np.ndarray:
    resized = cv2.resize(patch, win_size, interpolation=cv2.INTER_AREA)
    values = hog.compute(resized)
    return np.asarray(values, dtype=np.float32).reshape(-1)


def _new_hog(window_w: int, window_h: int) -> cv2.HOGDescriptor:
    return cv2.HOGDescriptor(
        (window_w, window_h),
        (16, 16),
        (8, 8),
        (8, 8),
        9,
    )


def _random_background(
    image: np.ndarray,
    boxes: list[dict[str, Any]],
    window_w: float,
    window_h: float,
    rng: random.Random,
) -> np.ndarray | None:
    image_h, image_w = image.shape
    box_w, box_h = min(window_w, image_w), min(window_h, image_h)
    if box_w < 16 or box_h < 16:
        return None
    for _ in range(40):
        left = rng.randint(0, max(0, int(image_w - box_w)))
        top = rng.randint(0, max(0, int(image_h - box_h)))
        candidate = (left, top, left + box_w, top + box_h)
        if all(_iou(candidate, item["box"]) < 0.05 for item in boxes):
            return image[int(top) : int(top + box_h), int(left) : int(left + box_w)]
    return None


def _fit_class_model(
    archive: zipfile.ZipFile,
    train_records: list[dict[str, Any]],
    class_id: int,
    window: tuple[int, int],
    median_size: tuple[float, float],
    seed: int,
) -> tuple[LinearSVC, np.ndarray, np.ndarray]:
    window_w, window_h = window
    hog = _new_hog(window_w, window_h)
    positive: list[np.ndarray] = []
    negative: list[np.ndarray] = []
    rng = random.Random(seed + class_id)
    for record in train_records:
        raw = np.frombuffer(archive.read(record["image_path"]), dtype=np.uint8)
        image = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError(f"Image cannot be decoded: {record['image_path']}")
        class_boxes = [box for box in record["boxes"] if box["class_id"] == class_id]
        for item in class_boxes:
            patch = _crop(image, tuple(item["box"]), context=1.0)
            if patch.size:
                positive.append(_descriptor(hog, patch, window))
                positive.append(_descriptor(hog, cv2.flip(patch, 1), window))
        patch = _random_background(
            image,
            record["boxes"],
            median_size[0],
            median_size[1],
            rng,
        )
        if patch is not None:
            negative.append(_descriptor(hog, patch, window))
    if not positive or not negative:
        raise ValueError(
            f"Insufficient samples for class {class_id}: positives={len(positive)}, negatives={len(negative)}"
        )
    print(
        f"class={class_id} window={window_w}x{window_h} positives={len(positive)} negatives={len(negative)}; fitting linear SVM",
        flush=True,
    )
    x = np.vstack([np.vstack(positive), np.vstack(negative)])
    y = np.concatenate(
        [np.ones(len(positive), dtype=np.int8), np.zeros(len(negative), dtype=np.int8)]
    )
    estimator = LinearSVC(
        C=0.01, class_weight="balanced", dual="auto", max_iter=5000, random_state=seed
    )
    estimator.fit(x, y)
    return estimator, x, y


def _mine_hard_negatives(
    archive: zipfile.ZipFile,
    train_records: list[dict[str, Any]],
    class_id: int,
    window: tuple[int, int],
    median_size: tuple[float, float],
    model: LinearSVC,
    seed: int,
) -> tuple[np.ndarray, int]:
    """Mine high scoring background windows from training groups only."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in train_records:
        grouped[record["source_group"]].append(record)
    rng = random.Random(seed + 1009 * (class_id + 1))
    selected: list[dict[str, Any]] = []
    for group in sorted(grouped):
        candidates = sorted(grouped[group], key=lambda record: record["image_path"])
        rng.shuffle(candidates)
        selected.extend(candidates[:HARD_NEGATIVE_IMAGES_PER_GROUP])

    window_w, window_h = window
    hog = _new_hog(window_w, window_h)
    target_scale = HOG_EDGE / max(median_size)
    mined_by_group: dict[str, list[tuple[float, np.ndarray]]] = defaultdict(list)
    for record in selected:
        image_data = np.frombuffer(archive.read(record["image_path"]), dtype=np.uint8)
        image = cv2.imdecode(image_data, cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError(f"Image cannot be decoded: {record['image_path']}")
        gt_boxes = [tuple(box["box"]) for box in record["boxes"] if box["class_id"] == class_id]
        candidates: list[tuple[float, tuple[float, float, float, float], np.ndarray]] = []
        for scale in sorted({round(target_scale * factor, 4) for factor in SCALE_FACTORS}):
            new_w, new_h = round(image.shape[1] * scale), round(image.shape[0] * scale)
            if new_w < window_w or new_h < window_h:
                continue
            interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
            resized = cv2.resize(image, (new_w, new_h), interpolation=interpolation)
            descriptors = hog.compute(resized, winStride=(HOG_STRIDE, HOG_STRIDE))
            if descriptors is None:
                continue
            features = np.asarray(descriptors, dtype=np.float32).reshape(
                -1, hog.getDescriptorSize()
            )
            scores = model.decision_function(features)
            xs = list(range(0, new_w - window_w + 1, HOG_STRIDE))
            ys = list(range(0, new_h - window_h + 1, HOG_STRIDE))
            if len(xs) * len(ys) != len(scores):
                raise ValueError("HOG mining descriptor count did not match candidate coordinates")
            for index, score in enumerate(scores):
                if score <= 0:
                    continue
                row, column = divmod(index, len(xs))
                box = (
                    xs[column] / scale,
                    ys[row] / scale,
                    min(image.shape[1], (xs[column] + window_w) / scale),
                    min(image.shape[0], (ys[row] + window_h) / scale),
                )
                if any(_iou(box, gt_box) >= 0.2 for gt_box in gt_boxes):
                    continue
                candidates.append((float(score), box, features[index]))
        candidates.sort(key=lambda item: item[0], reverse=True)
        chosen: list[tuple[float, float, float, float]] = []
        for score, box, feature in candidates:
            if any(_iou(box, prior) >= 0.5 for prior in chosen):
                continue
            mined_by_group[record["source_group"]].append((float(score), feature))
            chosen.append(box)
            if len(chosen) >= HARD_NEGATIVES_PER_IMAGE:
                break
    mined = [
        feature
        for group in sorted(mined_by_group)
        for _, feature in sorted(mined_by_group[group], key=lambda item: item[0], reverse=True)[
            :HARD_NEGATIVES_PER_GROUP
        ]
    ]
    if not mined:
        return np.empty((0, hog.getDescriptorSize()), dtype=np.float32), len(selected)
    return np.vstack(mined), len(selected)


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


def _detect_class(
    image: np.ndarray,
    model: LinearSVC,
    window: tuple[int, int],
    median_size: tuple[float, float],
    scale_factors: tuple[float, ...] = SCALE_FACTORS,
) -> list[dict[str, Any]]:
    window_w, window_h = window
    target_scale = HOG_EDGE / max(median_size)
    hog = _new_hog(window_w, window_h)
    detections: list[dict[str, Any]] = []
    scales = sorted({round(target_scale * factor, 4) for factor in scale_factors})
    for scale in scales:
        new_w, new_h = round(image.shape[1] * scale), round(image.shape[0] * scale)
        if new_w < window_w or new_h < window_h:
            continue
        interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
        resized = cv2.resize(image, (new_w, new_h), interpolation=interpolation)
        descriptors = hog.compute(resized, winStride=(HOG_STRIDE, HOG_STRIDE))
        if descriptors is None:
            continue
        features = np.asarray(descriptors, dtype=np.float32).reshape(-1, hog.getDescriptorSize())
        scores = model.decision_function(features)
        xs = list(range(0, new_w - window_w + 1, HOG_STRIDE))
        ys = list(range(0, new_h - window_h + 1, HOG_STRIDE))
        if len(xs) * len(ys) != len(scores):
            raise ValueError(
                "HOG sliding-window descriptor count did not match candidate coordinates"
            )
        for index, score in enumerate(scores):
            top_index, left_index = divmod(index, len(xs))
            x1 = xs[left_index] / scale
            y1 = ys[top_index] / scale
            x2 = min(image.shape[1], x1 + window_w / scale)
            y2 = min(image.shape[0], y1 + window_h / scale)
            detections.append({"box": (x1, y1, x2, y2), "score": float(score)})
    detections.sort(key=lambda item: item["score"], reverse=True)
    detections = detections[: DETECTIONS_PER_CLASS_IMAGE * 5]
    if not detections:
        return []
    rects = [
        [
            round(d["box"][0]),
            round(d["box"][1]),
            round(d["box"][2] - d["box"][0]),
            round(d["box"][3] - d["box"][1]),
        ]
        for d in detections
    ]
    minimum_score = min(d["score"] for d in detections)
    nms_scores = [d["score"] - minimum_score + 1e-6 for d in detections]
    indices = cv2.dnn.NMSBoxes(
        rects,
        nms_scores,
        score_threshold=0.0,
        nms_threshold=0.4,
        top_k=DETECTIONS_PER_CLASS_IMAGE,
    )
    return [detections[int(i)] for i in np.asarray(indices).reshape(-1)]


def _average_precision(
    predictions: list[dict[str, Any]],
    truths: dict[str, list[tuple[float, float, float, float]]],
    threshold: float,
) -> tuple[float, float, float]:
    total_truth = sum(len(boxes) for boxes in truths.values())
    if total_truth == 0:
        return float("nan"), 0.0, 0.0
    matched = {image: set() for image in truths}
    tp: list[int] = []
    fp: list[int] = []
    for prediction in sorted(predictions, key=lambda item: item["score"], reverse=True):
        image = prediction["image"]
        candidates = truths.get(image, [])
        overlaps = [_iou(prediction["box"], box) for box in candidates]
        best_index = int(np.argmax(overlaps)) if overlaps else -1
        if (
            best_index >= 0
            and overlaps[best_index] >= threshold
            and best_index not in matched[image]
        ):
            matched[image].add(best_index)
            tp.append(1)
            fp.append(0)
        else:
            tp.append(0)
            fp.append(1)
    tp_array = np.cumsum(tp, dtype=np.float64)
    fp_array = np.cumsum(fp, dtype=np.float64)
    recall = tp_array / total_truth
    precision = tp_array / np.maximum(tp_array + fp_array, 1)
    ap = float(
        np.mean(
            [
                np.max(precision[recall >= value]) if np.any(recall >= value) else 0.0
                for value in np.linspace(0, 1, 101)
            ]
        )
    )
    fixed = [item for item in predictions if item["score"] >= 0.0]
    fixed_matched = {image: set() for image in truths}
    fixed_tp = fixed_fp = 0
    for prediction in sorted(fixed, key=lambda item: item["score"], reverse=True):
        image = prediction["image"]
        overlaps = [_iou(prediction["box"], box) for box in truths.get(image, [])]
        best_index = int(np.argmax(overlaps)) if overlaps else -1
        if (
            best_index >= 0
            and overlaps[best_index] >= threshold
            and best_index not in fixed_matched[image]
        ):
            fixed_matched[image].add(best_index)
            fixed_tp += 1
        else:
            fixed_fp += 1
    precision0 = fixed_tp / max(1, fixed_tp + fixed_fp)
    recall0 = fixed_tp / total_truth
    return ap, precision0, recall0


def train_and_evaluate(
    archive_path: str,
    output_dir: str,
    seed: int = 42,
) -> dict[str, Any]:
    records, class_names, invalid_boxes = read_records(archive_path)
    split = grouped_holdout(records, seed=seed)
    train_records, test_records = split.pop("train_records"), split.pop("test_records")
    windows: dict[int, tuple[int, int]] = {}
    median_sizes: dict[int, tuple[float, float]] = {}
    for class_id in range(len(class_names)):
        ww, wh, mw, mh = _class_window(train_records, class_id)
        windows[class_id] = (ww, wh)
        median_sizes[class_id] = (mw, mh)

    os.makedirs(output_dir, exist_ok=True)
    split["train_class_instances"] = dict(
        Counter(box["class_id"] for r in train_records for box in r["boxes"])
    )
    split["test_class_instances"] = dict(
        Counter(box["class_id"] for r in test_records for box in r["boxes"])
    )
    archive_hash = hashlib.sha256()
    with open(archive_path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            archive_hash.update(chunk)
    split["source_archive_sha256"] = archive_hash.hexdigest()
    split["invalid_box_count_excluded"] = invalid_boxes
    with open(os.path.join(output_dir, "split.json"), "w", encoding="utf-8") as stream:
        json.dump(split, stream, indent=2, sort_keys=True)
        stream.write("\n")

    models: dict[int, LinearSVC] = {}
    hard_negative_counts: dict[str, Any] = {}
    with zipfile.ZipFile(archive_path) as archive:
        for class_id in range(len(class_names)):
            print(f"Training class {class_id}: {class_names[class_id]}", flush=True)
            model, x, y = _fit_class_model(
                archive, train_records, class_id, windows[class_id], median_sizes[class_id], seed
            )
            hard_negatives, mining_images = _mine_hard_negatives(
                archive,
                train_records,
                class_id,
                windows[class_id],
                median_sizes[class_id],
                model,
                seed,
            )
            if len(hard_negatives):
                x = np.vstack([x, hard_negatives])
                y = np.concatenate([y, np.zeros(len(hard_negatives), dtype=np.int8)])
                model = LinearSVC(
                    C=0.01,
                    class_weight="balanced",
                    dual="auto",
                    max_iter=5000,
                    random_state=seed,
                )
                model.fit(x, y)
            models[class_id] = model
            hard_negative_counts[class_names[class_id]] = {
                "windows": len(hard_negatives),
                "mining_images": mining_images,
            }
            print(
                f"class={class_names[class_id]} hard_negatives={len(hard_negatives)} from {mining_images} training images",
                flush=True,
            )
            del x, y, hard_negatives

    class_predictions: dict[int, list[dict[str, Any]]] = defaultdict(list)
    truths: dict[int, dict[str, list[tuple[float, float, float, float]]]] = {
        class_id: defaultdict(list) for class_id in range(len(class_names))
    }
    latencies: list[float] = []
    with zipfile.ZipFile(archive_path) as archive:
        for record in test_records:
            raw = np.frombuffer(archive.read(record["image_path"]), dtype=np.uint8)
            image = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise ValueError(f"Image cannot be decoded: {record['image_path']}")
            for item in record["boxes"]:
                truths[item["class_id"]][record["image_path"]].append(tuple(item["box"]))
            start = time.perf_counter()
            for class_id in range(len(class_names)):
                detections = _detect_class(
                    image,
                    models[class_id],
                    windows[class_id],
                    median_sizes[class_id],
                    SCALE_FACTORS,
                )
                for detection in detections:
                    class_predictions[class_id].append({**detection, "image": record["image_path"]})
            latencies.append((time.perf_counter() - start) * 1000)
            if len(latencies) % 100 == 0:
                print(
                    f"Evaluated {len(latencies)}/{len(test_records)} grouped holdout images",
                    flush=True,
                )

    per_class: dict[str, Any] = {}
    thresholds = np.arange(0.5, 0.951, 0.05)
    for class_id, class_name in enumerate(class_names):
        ap_by_iou = [
            _average_precision(class_predictions[class_id], truths[class_id], float(iou))
            for iou in thresholds
        ]
        ap50, precision, recall = ap_by_iou[0]
        per_class[class_name] = {
            "ground_truth_instances": sum(len(v) for v in truths[class_id].values()),
            "ap50": ap50,
            "ap50_95": float(np.nanmean([x[0] for x in ap_by_iou])),
            "precision_at_svm_margin_0_iou_0_5": precision,
            "recall_at_svm_margin_0_iou_0_5": recall,
            "test_source_groups": sum(
                any(
                    r["source_group"] == group
                    and any(b["class_id"] == class_id for b in r["boxes"])
                    for r in test_records
                )
                for group in split["test_groups"]
            ),
        }

    evaluation = {
        "experiment": MODEL_ID,
        "seed": seed,
        "source_archive_sha256": split["source_archive_sha256"],
        "dataset_id": "zenodo-students-online-exam-v1",
        "split": split,
        "classes": per_class,
        "macro_map50": float(np.mean([v["ap50"] for v in per_class.values()])),
        "macro_map50_95": float(np.mean([v["ap50_95"] for v in per_class.values()])),
        "latency_ms_per_image": {
            "mean": float(np.mean(latencies)),
            "p50": float(np.percentile(latencies, 50)),
            "p95": float(np.percentile(latencies, 95)),
            "images": len(latencies),
            "includes_image_decode": False,
            "hardware": "macOS CPU via OpenCV/scikit-learn; no GPU or pretrained weights",
        },
        "software_versions": {
            "python": platform.python_version(),
            "opencv": cv2.__version__,
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "training_config": {
            "features": "OpenCV HOG",
            "classifier": "one-vs-rest LinearSVC per class",
            "C": 0.01,
            "positive_crop_context": 1.0,
            "positive_horizontal_flip": True,
            "negative_windows_per_image": NEGATIVE_WINDOWS_PER_IMAGE,
            "hard_negative_mining_images_per_group": HARD_NEGATIVE_IMAGES_PER_GROUP,
            "hard_negatives_per_mining_image": HARD_NEGATIVES_PER_IMAGE,
            "hard_negatives_cap_per_group": HARD_NEGATIVES_PER_GROUP,
            "hard_negative_counts_by_class": hard_negative_counts,
            "hog_edge": HOG_EDGE,
            "hog_stride": HOG_STRIDE,
            "scale_factors": SCALE_FACTORS,
            "nms_iou_threshold": 0.4,
            "detections_per_class_image": DETECTIONS_PER_CLASS_IMAGE,
            "margin_for_precision_recall": 0.0,
            "pretrained_weights": False,
        },
        "limitations": [
            "Single-university imagery; no participant ID was found.",
            "The source-group split uses a filename prefix as a provisional recording proxy.",
            "This v3 iteration reuses the previously inspected seed-42 holdout; results are exploratory, not an independent final test.",
            "Metrics describe visible annotation agreement only, not cheating or intent.",
            "One invalid zero-area annotation was excluded. The 81 unlabeled test images were excluded.",
            "The linked paper's reported metrics are not reused as project results.",
        ],
    }
    with open(os.path.join(output_dir, "evaluation.json"), "w", encoding="utf-8") as stream:
        json.dump(evaluation, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    metric_rows = "\n".join(
        "| {name} | {n} | {ap50:.4f} | {ap5095:.4f} | {precision:.4f} | {recall:.4f} |".format(
            name=name,
            n=values["ground_truth_instances"],
            ap50=values["ap50"],
            ap5095=values["ap50_95"],
            precision=values["precision_at_svm_margin_0_iou_0_5"],
            recall=values["recall_at_svm_margin_0_iou_0_5"],
        )
        for name, values in per_class.items()
    )
    model_card = f"""# Model card — {evaluation["experiment"]}

## Intended use

Research-only detector for the five visible behavior labels in the Zenodo Students' Abnormal Behavior in Online Exam dataset. Its outputs are visual annotations, not evidence of cheating, intent, attention, or a policy violation. Do not connect this artifact to grading, student discipline, or an automated exam decision.

## Training and provenance

- Dataset: {evaluation["dataset_id"]} (CC BY 4.0 record; creator Muhanad Alkhalisy).
- Source archive SHA-256: `{evaluation["source_archive_sha256"]}`.
- Labeled images used: {split["train_images"]} training and {split["test_images"]} held-out.
- Split: filename-prefix source-group holdout, seed {seed}; test groups: {", ".join(split["test_groups"])}.
- Invalid zero-area boxes excluded: {invalid_boxes}. The unlabeled 81-image source test folder was excluded.
- Model: five independently trained linear SVM classifiers over OpenCV HOG features; no pretrained model weights.
- Software: Python {evaluation["software_versions"]["python"]}, OpenCV {evaluation["software_versions"]["opencv"]}, NumPy {evaluation["software_versions"]["numpy"]}, scikit-learn {evaluation["software_versions"]["scikit_learn"]}.

## Held-out metrics

| Class | GT instances | AP@0.5 | AP@[0.5:0.95] | Precision at margin 0 | Recall at margin 0 |
|---|---:|---:|---:|---:|---:|
{metric_rows}

- Macro mAP@0.5: {evaluation["macro_map50"]:.4f}
- Macro mAP@[0.5:0.95]: {evaluation["macro_map50_95"]:.4f}
- Inference time (CPU, per image, excludes decode): p50 {evaluation["latency_ms_per_image"]["p50"]:.1f} ms; p95 {evaluation["latency_ms_per_image"]["p95"]:.1f} ms.

Precision/recall use an uncalibrated SVM margin threshold of 0 and IoU 0.5. AP scores rank post-NMS sliding-window detections. This v3 iteration adds hard-negative mining from training groups, then reuses the previously inspected seed-42 holdout; these metrics are exploratory, not a fresh confirmatory test. The 38 filename-derived group keys are only proxies for recordings; the dataset contains no verified participant IDs, so these scores do not measure unseen-person generalization. Low AP values make this a weak baseline, not a deployment-ready detector.

## Data and fairness limitations

The associated paper reports a single-university cohort and inconsistent dataset counts/format descriptions. The archive's provided train/valid split shares all filename-derived groups; its unlabeled test folder contains cross-split duplicates. We therefore made a new filename-group holdout and excluded the supplied test folder. Participant consent/ethics approval evidence is not clear in the source paper. The CC BY 4.0 dataset license does not resolve that gap. No subgroup fairness evaluation is possible from the available metadata.

## Versioned inference

The artifact is identified as `{evaluation["experiment"]}` and is consumed by `/api/v1/detect`. It returns only the class, uncalibrated SVM margin, and bounding box. Invalid images, oversize payloads, unavailable model artifacts, and service timeouts must be handled as errors; exam attempts do not depend on this endpoint.
"""
    with open(os.path.join(output_dir, "MODEL_CARD.md"), "w", encoding="utf-8") as stream:
        stream.write(model_card)
    joblib.dump(
        {
            "model_id": MODEL_ID,
            "class_names": class_names,
            "models": models,
            "windows": windows,
            "median_sizes": median_sizes,
            "hog_edge": HOG_EDGE,
            "hog_stride": HOG_STRIDE,
            "scale_factors": SCALE_FACTORS,
            "source_archive_sha256": split["source_archive_sha256"],
            "seed": seed,
            "software_versions": evaluation["software_versions"],
            "training_config": evaluation["training_config"],
        },
        os.path.join(output_dir, "detector.joblib"),
        compress=3,
    )
    print(
        json.dumps(
            {
                "classes": per_class,
                "macro_map50": evaluation["macro_map50"],
                "latency_ms_per_image": evaluation["latency_ms_per_image"],
            },
            indent=2,
        )
    )
    return evaluation

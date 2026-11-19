"""Read-only audit for YOLO-style image detection archives."""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

import cv2
import numpy as np

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
EXPECTED_MD5 = "78fde2372a5a58efba55ed4d47039429"


def _label_for_image(image_name: str) -> str:
    path = PurePosixPath(image_name)
    parts = list(path.parts)
    if "images" in parts:
        parts[parts.index("images")] = "labels"
    return str(PurePosixPath(*parts).with_suffix(".txt"))


def _is_safe_zip_path(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and "\\" not in name


def audit_archive(archive_path: str) -> dict[str, Any]:
    """Inspect archive inventory, paired YOLO labels, and normalized boxes.

    The archive is never extracted. The MD5 is checked against the digest
    published on the Zenodo record; SHA-256 is also emitted for local provenance.
    """
    digest_md5 = hashlib.md5(usedforsecurity=False)
    digest_sha256 = hashlib.sha256()
    with open(archive_path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest_md5.update(chunk)
            digest_sha256.update(chunk)

    with zipfile.ZipFile(archive_path) as archive:
        entries = [entry for entry in archive.infolist() if not entry.is_dir()]
        unsafe_paths = [
            entry.filename for entry in entries if not _is_safe_zip_path(entry.filename)
        ]
        names = {entry.filename for entry in entries}
        images = [name for name in names if PurePosixPath(name).suffix.lower() in IMAGE_SUFFIXES]
        paired = {_label_for_image(image) for image in images}
        labels = [
            name
            for name in names
            if PurePosixPath(name).suffix.lower() == ".txt"
            and "labels" in PurePosixPath(name).parts
        ]
        missing_labels = sorted(paired - names)
        unmatched_labels = sorted(set(labels) - paired)
        class_counts: Counter[int] = Counter()
        split_counts: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "image_count": 0,
                "label_count": 0,
                "missing_label_count": 0,
                "class_instance_counts": Counter(),
            }
        )
        image_digests: dict[str, list[tuple[str, str]]] = defaultdict(list)
        image_dimensions: Counter[tuple[int, int]] = Counter()
        undecodable_images: list[str] = []
        empty_labels = 0
        malformed_lines: list[dict[str, Any]] = []
        invalid_boxes: list[dict[str, Any]] = []
        label_files = 0
        class_names: list[str] = []
        class_file = next(
            (name for name in names if PurePosixPath(name).name.lower() == "classes.txt"), None
        )
        if class_file:
            class_names = [
                line.strip()
                for line in archive.read(class_file).decode("utf-8-sig").splitlines()
                if line.strip()
            ]
        dataset_config: dict[str, str] = {}
        config_file = next(
            (name for name in names if PurePosixPath(name).name.lower() == "data.yaml"), None
        )
        if config_file:
            for line in archive.read(config_file).decode("utf-8-sig").splitlines():
                match = re.match(r"^\s*(train|val|test)\s*:\s*(.*?)\s*$", line)
                if match:
                    dataset_config[match.group(1)] = match.group(2).strip("'\"")
        directory_names = {
            str(PurePosixPath(entry.filename)) for entry in archive.infolist() if entry.is_dir()
        }
        for image_name in images:
            path = PurePosixPath(image_name)
            parts = path.parts
            split = parts[-3] if len(parts) >= 3 and parts[-2] == "images" else "unspecified"
            split_counts[split]["image_count"] += 1
            image_data = archive.read(image_name)
            image_digests[hashlib.sha256(image_data).hexdigest()].append((split, image_name))
            decoded = cv2.imdecode(np.frombuffer(image_data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if decoded is None:
                undecodable_images.append(image_name)
            else:
                image_dimensions[(int(decoded.shape[1]), int(decoded.shape[0]))] += 1
            label_name = _label_for_image(image_name)
            if label_name not in names:
                split_counts[split]["missing_label_count"] += 1
        for label_name in sorted(set(labels) & paired):
            parts = PurePosixPath(label_name).parts
            split = parts[-3] if len(parts) >= 3 and parts[-2] == "labels" else "unspecified"
            split_counts[split]["label_count"] += 1
            label_files += 1
            try:
                content = archive.read(label_name).decode("utf-8-sig")
            except (UnicodeDecodeError, OSError, RuntimeError) as exc:
                malformed_lines.append({"file": label_name, "line": 0, "reason": str(exc)})
                continue
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            if not lines:
                empty_labels += 1
            for line_no, line in enumerate(lines, 1):
                values = re.split(r"\s+", line)
                if len(values) != 5:
                    malformed_lines.append(
                        {"file": label_name, "line": line_no, "reason": "expected 5 YOLO fields"}
                    )
                    continue
                try:
                    class_id = int(values[0])
                    x_center, y_center, width, height = map(float, values[1:])
                except ValueError:
                    malformed_lines.append(
                        {"file": label_name, "line": line_no, "reason": "non-numeric YOLO field"}
                    )
                    continue
                if class_id < 0:
                    malformed_lines.append(
                        {"file": label_name, "line": line_no, "reason": "negative class id"}
                    )
                    continue
                class_counts[class_id] += 1
                split_counts[split]["class_instance_counts"][class_id] += 1
                box = (x_center, y_center, width, height)
                if any(value < 0 or value > 1 for value in box) or width == 0 or height == 0:
                    invalid_boxes.append({"file": label_name, "line": line_no, "box": box})
        corrupt_entry = archive.testzip()

    digest = digest_md5.hexdigest()
    duplicate_groups = [items for items in image_digests.values() if len(items) > 1]
    cross_split_duplicates = [
        items for items in duplicate_groups if len({item[0] for item in items}) > 1
    ]
    configured_splits = {
        key: {
            "path": value,
            "path_exists": any(
                name.rstrip("/").endswith(value.rstrip("/")) for name in directory_names
            ),
        }
        for key, value in dataset_config.items()
    }
    return {
        "archive": archive_path,
        "archive_md5": digest,
        "published_md5_match": digest == EXPECTED_MD5,
        "archive_sha256": digest_sha256.hexdigest(),
        "archive_bytes": os.path.getsize(archive_path),
        "file_count": len(entries),
        "image_count": len(images),
        "undecodable_image_count": len(undecodable_images),
        "image_dimensions": {
            f"{width}x{height}": count
            for (width, height), count in sorted(image_dimensions.items())
        },
        "label_count": len(labels),
        "class_names_by_id": {str(i): name for i, name in enumerate(class_names)},
        "configured_splits": configured_splits,
        "split_counts": {
            split: {
                **values,
                "class_instance_counts": {
                    str(k): v for k, v in sorted(values["class_instance_counts"].items())
                },
            }
            for split, values in sorted(split_counts.items())
        },
        "paired_label_count": label_files,
        "missing_label_count": len(missing_labels),
        "unmatched_label_count": len(unmatched_labels),
        "empty_label_count": empty_labels,
        "class_instance_counts": {str(k): v for k, v in sorted(class_counts.items())},
        "exact_duplicate_image_group_count": len(duplicate_groups),
        "cross_split_exact_duplicate_group_count": len(cross_split_duplicates),
        "cross_split_exact_duplicate_examples": [
            [image for _, image in items] for items in cross_split_duplicates[:10]
        ],
        "class_ids_without_names": sorted(
            class_id for class_id in class_counts if class_id >= len(class_names)
        ),
        "malformed_annotation_count": len(malformed_lines),
        "invalid_box_count": len(invalid_boxes),
        "unsafe_zip_path_count": len(unsafe_paths),
        "corrupt_zip_entry": corrupt_entry,
        "examples": {
            "missing_labels": missing_labels[:10],
            "unmatched_labels": unmatched_labels[:10],
            "malformed_annotations": malformed_lines[:10],
            "invalid_boxes": invalid_boxes[:10],
            "unsafe_paths": unsafe_paths[:10],
            "undecodable_images": undecodable_images[:10],
        },
    }


def write_report(report: dict[str, Any], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")

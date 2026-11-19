"""Provenance-gated data inspection, evaluation, and strict inference helpers."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


class PipelineError(ValueError):
    """Raised when a dataset or inference payload fails the declared contract."""


@dataclass(frozen=True)
class Dataset:
    manifest_path: Path
    manifest: dict[str, Any]
    frame: pd.DataFrame
    target: str
    positive_label: Any
    group_column: str | None
    features: list[str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(path: Path, *, allow_unreviewed: bool = False) -> tuple[dict, pd.DataFrame]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"Cannot read manifest: {exc}") from exc
    required = (
        "dataset_name",
        "source_url",
        "version",
        "license",
        "license_url",
        "license_evidence",
        "license_reviewed",
        "attribution",
        "retrieved_at",
        "file_path",
        "sha256",
        "target_column",
        "positive_label",
        "label_semantics",
        "limitations",
        "research_only",
        "provenance_reviewed",
    )
    absent = [field for field in required if field not in manifest or manifest[field] in (None, "")]
    if absent:
        raise PipelineError(f"Manifest missing required fields: {', '.join(absent)}")
    if not manifest["research_only"]:
        raise PipelineError("This training pipeline only supports research-only exploratory runs")
    if allow_unreviewed and manifest.get("owner_authorized_local_exploratory_use") is not True:
        raise PipelineError(
            "Unreviewed data requires an explicit owner_authorized_local_exploratory_use manifest entry"
        )
    if not allow_unreviewed and (
        manifest["provenance_reviewed"] is not True or manifest["license_reviewed"] is not True
    ):
        raise PipelineError("Dataset provenance has not been reviewed; training is blocked")
    data_path = (path.parent / manifest["file_path"]).resolve()
    if not data_path.is_relative_to(path.parent.resolve()):
        raise PipelineError("Dataset file_path must remain within the manifest directory")
    if not data_path.is_file():
        raise PipelineError(f"Dataset file does not exist: {data_path}")
    expected_hash = str(manifest["sha256"]).lower()
    if len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
        raise PipelineError("Manifest sha256 must be a 64-character hexadecimal digest")
    actual_hash = sha256_file(data_path)
    if actual_hash != expected_hash:
        raise PipelineError(
            f"Dataset checksum mismatch: expected {expected_hash}, got {actual_hash}"
        )
    try:
        frame = pd.read_csv(data_path, low_memory=False)
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise PipelineError(f"Cannot parse dataset CSV: {exc}") from exc
    if frame.empty:
        raise PipelineError("Dataset contains no records")
    if frame.columns.duplicated().any() or any(not str(col).strip() for col in frame.columns):
        raise PipelineError("Dataset column names must be non-empty and unique")
    target = manifest["target_column"]
    if target not in frame.columns:
        raise PipelineError(f"Target column not found: {target}")
    if frame[target].isna().any():
        raise PipelineError("Target labels contain missing values")
    labels = set(frame[target].unique().tolist())
    if len(labels) != 2 or manifest["positive_label"] not in labels:
        raise PipelineError(
            "This baseline requires exactly two target labels and a declared positive_label"
        )
    group = manifest.get("group_column")
    if group is not None and group not in frame.columns:
        raise PipelineError(f"Declared group column not found: {group}")
    excluded = set(manifest.get("excluded_columns", [])) | {target}
    if group:
        excluded.add(group)
    unknown_excluded = excluded.difference(frame.columns)
    if unknown_excluded:
        raise PipelineError(f"Excluded columns are not present: {sorted(unknown_excluded)}")
    features = [str(col) for col in frame.columns if col not in excluded]
    if not features:
        raise PipelineError("No feature columns remain after exclusions")
    if frame[features].isna().all(axis=1).all():
        raise PipelineError("All feature values are missing")
    return manifest, frame


def load_dataset(path: Path, *, allow_unreviewed: bool = False) -> Dataset:
    manifest, frame = read_manifest(path, allow_unreviewed=allow_unreviewed)
    group = manifest.get("group_column")
    features = [
        str(col)
        for col in frame.columns
        if col != manifest["target_column"]
        and col != group
        and col not in set(manifest.get("excluded_columns", []))
    ]
    return Dataset(
        manifest_path=path.resolve(),
        manifest=manifest,
        frame=frame,
        target=manifest["target_column"],
        positive_label=manifest["positive_label"],
        group_column=group,
        features=features,
    )


def inspect_data(dataset: Dataset) -> dict[str, Any]:
    frame, target = dataset.frame, dataset.target
    labels = frame[target].value_counts(dropna=False).to_dict()
    exact_duplicates = int(frame.duplicated().sum())
    feature_duplicates = int(frame[dataset.features].duplicated().sum())
    possible_leakage = [
        name
        for name in dataset.features
        if any(
            token in name.lower() for token in ("label", "target", "outcome", "cheat", "suspicious")
        )
    ]
    group_summary = None
    if dataset.group_column:
        groups = frame[dataset.group_column]
        group_summary = {
            "column": dataset.group_column,
            "unique_groups": int(groups.nunique(dropna=False)),
            "missing_rows": int(groups.isna().sum()),
        }
    return {
        "dataset_name": dataset.manifest["dataset_name"],
        "records": len(frame),
        "feature_count": len(dataset.features),
        "features": dataset.features,
        "target_column": target,
        "label_counts": {str(k): int(v) for k, v in labels.items()},
        "missing_by_column": {str(k): int(v) for k, v in frame.isna().sum().items()},
        "exact_duplicate_rows": exact_duplicates,
        "duplicate_feature_rows": feature_duplicates,
        "possible_target_leakage_columns_for_manual_review": possible_leakage,
        "groups": group_summary,
        "warnings": list(dataset.manifest["limitations"]),
    }


def _split(dataset: Dataset, *, test_size: float, seed: int):
    frame = dataset.frame
    x = frame[dataset.features]
    y = frame[dataset.target]
    if dataset.group_column:
        group_values = frame[dataset.group_column]
        if group_values.isna().any():
            raise PipelineError("Group split cannot run with missing group identifiers")
        splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
        train_idx, test_idx = next(splitter.split(x, y, groups=group_values))
        split_type = "group_holdout"
        if set(group_values.iloc[train_idx]).intersection(set(group_values.iloc[test_idx])):
            raise PipelineError("Group leakage detected between train and test splits")
    else:
        train_idx, test_idx = train_test_split(
            np.arange(len(frame)), test_size=test_size, random_state=seed, stratify=y
        )
        split_type = "stratified_random_holdout_no_group_ids"
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    if y_train.nunique() != 2 or y_test.nunique() != 2:
        raise PipelineError("Both classes must occur in train and held-out test data")
    return x.iloc[train_idx], x.iloc[test_idx], y_train, y_test, split_type, train_idx, test_idx


def _build_pipeline(x: pd.DataFrame, estimator):
    numeric = x.select_dtypes(include=["number", "bool"]).columns.tolist()
    categorical = [col for col in x.columns if col not in numeric]
    transforms = []
    if numeric:
        transforms.append(
            (
                "numeric",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            )
        )
    if categorical:
        transforms.append(
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("encode", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            )
        )
    return Pipeline([("preprocess", ColumnTransformer(transforms)), ("model", estimator)])


def _metrics(y_true, probabilities: np.ndarray, positive_label: Any) -> dict[str, Any]:
    labels = list(pd.unique(y_true))
    negative_label = next(label for label in labels if label != positive_label)
    binary_true = np.asarray(y_true == positive_label, dtype=int)
    prediction = np.where(probabilities >= 0.5, positive_label, negative_label)
    return {
        "threshold": 0.5,
        "accuracy": float(accuracy_score(y_true, prediction)),
        "precision": float(
            precision_score(y_true, prediction, pos_label=positive_label, zero_division=0)
        ),
        "recall": float(
            recall_score(y_true, prediction, pos_label=positive_label, zero_division=0)
        ),
        "f1": float(f1_score(y_true, prediction, pos_label=positive_label, zero_division=0)),
        "roc_auc": float(roc_auc_score(binary_true, probabilities)),
        "average_precision": float(average_precision_score(binary_true, probabilities)),
        "brier_score": float(brier_score_loss(binary_true, probabilities)),
        "log_loss": float(log_loss(binary_true, probabilities, labels=[0, 1])),
        "confusion_matrix_labels_negative_then_positive": confusion_matrix(
            y_true, prediction, labels=[negative_label, positive_label]
        ).tolist(),
        "test_class_counts": {str(k): int(v) for k, v in y_true.value_counts().to_dict().items()},
    }


def train_and_evaluate(
    dataset: Dataset,
    output_dir: Path,
    *,
    seed: int = 42,
    test_size: float = 0.2,
    forest_trees: int = 300,
) -> dict[str, Any]:
    if not 0.1 <= test_size <= 0.4:
        raise PipelineError("test_size must be between 0.10 and 0.40")
    x_train, x_test, y_train, y_test, split_type, train_idx, test_idx = _split(
        dataset, test_size=test_size, seed=seed
    )
    positive = dataset.positive_label
    negative = next(label for label in pd.unique(y_train) if label != positive)
    models = {
        "majority_class_baseline": None,
        "logistic_regression": _build_pipeline(
            x_train, LogisticRegression(max_iter=2000, random_state=seed)
        ),
        "random_forest": _build_pipeline(
            x_train,
            RandomForestClassifier(
                n_estimators=forest_trees,
                min_samples_leaf=2,
                class_weight="balanced",
                random_state=seed,
                n_jobs=1,
            ),
        ),
    }
    results: dict[str, Any] = {}
    fitted: dict[str, Pipeline] = {}
    for name, model in models.items():
        if model is None:
            probability = np.full(len(y_test), float((y_train == positive).mean()))
        else:
            model.fit(x_train, y_train)
            fitted[name] = model
            classes = list(model.named_steps["model"].classes_)
            probability = model.predict_proba(x_test)[:, classes.index(positive)]
        results[name] = _metrics(y_test, probability, positive)
    output_dir.mkdir(parents=True, exist_ok=True)
    data_path = dataset.manifest_path.parent / dataset.manifest["file_path"]
    data_digest = sha256_file(data_path)
    manifest = {
        "dataset_name": dataset.manifest["dataset_name"],
        "source_url": dataset.manifest["source_url"],
        "version": dataset.manifest["version"],
        "license": dataset.manifest["license"],
        "attribution": dataset.manifest["attribution"],
        "data_sha256": data_digest,
        "feature_names": dataset.features,
        "feature_kinds": {
            feature: "numeric"
            if pd.api.types.is_numeric_dtype(dataset.frame[feature])
            or pd.api.types.is_bool_dtype(dataset.frame[feature])
            else "categorical"
            for feature in dataset.features
        },
        "target_column": dataset.target,
        "positive_label": positive,
        "negative_label": negative,
        "group_column": dataset.group_column,
        "model_name": "random_forest",
        "research_only": True,
        "created_at": datetime.now(UTC).isoformat(),
        "python_pipeline_version": "0.1.0",
        "scikit_learn_version": __import__("sklearn").__version__,
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
    }
    joblib.dump(
        {"pipeline": fitted["random_forest"], "contract": manifest}, output_dir / "model.joblib"
    )
    report = {
        "dataset": inspect_data(dataset),
        "run": {
            "seed": seed,
            "split_type": split_type,
            "train_rows": len(train_idx),
            "test_rows": len(test_idx),
            "train_group_count": int(dataset.frame.iloc[train_idx][dataset.group_column].nunique())
            if dataset.group_column
            else None,
            "test_group_count": int(dataset.frame.iloc[test_idx][dataset.group_column].nunique())
            if dataset.group_column
            else None,
            "random_state": seed,
            "models": results,
            "data_sha256": data_digest,
            "research_only": True,
            "interpretation": "Metrics measure agreement with the dataset's labels only; they do not measure misconduct or intent.",
        },
    }
    (output_dir / "evaluation.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    write_model_card(output_dir / "MODEL_CARD.md", manifest, report)
    return report


def write_model_card(path: Path, contract: dict[str, Any], report: dict[str, Any]) -> None:
    run = report["run"]
    metrics = run["models"].get("random_forest", {})
    limitations = report["dataset"].get("warnings", [])
    card = [
        "# Exploratory tabular model card",
        "",
        "> Research-only artifact. It is not approved for live exams, decisions about students, or claims of misconduct.",
        "",
        "## Provenance",
        f"- Dataset: {contract['dataset_name']} (version {contract['version']})",
        f"- Source: {contract['source_url']}",
        f"- License: {contract['license']}",
        f"- Attribution: {contract['attribution']}",
        f"- SHA-256: `{contract['data_sha256']}`",
        "",
        "## Task and evaluation",
        f"- Target column: `{contract['target_column']}`; positive dataset label: `{contract['positive_label']}`",
        f"- Split: `{run['split_type']}`; random seed: {run['seed']}; test rows: {run['test_rows']}",
        "- Metrics quantify only agreement with the dataset's labels. They do not establish the truth of those labels.",
        f"- Random-forest held-out metrics: `{json.dumps(metrics, sort_keys=True)}`",
        "",
        "## Intended use and prohibited interpretation",
        "Exploratory replication and pipeline verification only. A predicted class or probability is not evidence of intent, honesty, attention, cheating, or policy violation. Do not use this artifact to grade, accuse, discipline, rank, or automatically flag a student.",
        "",
        "## Limitations",
        *(
            [f"- {limitation}" for limitation in limitations]
            or ["- Dataset-specific limitations require review."]
        ),
        "- Dependence between records can make random row splits optimistic; review the declared group field and split design above for this dataset.",
        "- The training dataset may encode its scripted collection protocol and manual annotation assumptions rather than generalizable behavior.",
        "- No fairness, calibration, external-validity, or real-world proctoring claim is made.",
        "",
    ]
    path.write_text("\n".join(card), encoding="utf-8")


def validate_inference_payload(contract: dict[str, Any], payload: Any) -> pd.DataFrame:
    if not isinstance(payload, dict):
        raise PipelineError("Inference input must be a JSON object with one record")
    required = contract["feature_names"]
    missing, extra = set(required) - set(payload), set(payload) - set(required)
    if missing or extra:
        raise PipelineError(f"Feature mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    values: dict[str, Any] = {}
    for feature, kind in contract["feature_kinds"].items():
        value = payload[feature]
        if value is None:
            values[feature] = np.nan
        elif kind == "numeric":
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise PipelineError(f"Feature {feature!r} must be a finite number or null")
            values[feature] = value
        elif isinstance(value, str):
            values[feature] = value
        else:
            raise PipelineError(f"Feature {feature!r} must be a string or null")
    return pd.DataFrame([values], columns=required)


def predict(model_path: Path, payload: Any) -> dict[str, Any]:
    loaded = joblib.load(model_path)
    contract, pipeline = loaded["contract"], loaded["pipeline"]
    if contract.get("research_only") is not True:
        raise PipelineError("Artifact does not declare research_only=true")
    row = validate_inference_payload(contract, payload)
    classes = list(pipeline.named_steps["model"].classes_)
    positive = contract["positive_label"]
    probability = float(pipeline.predict_proba(row)[0, classes.index(positive)])
    label = positive if probability >= 0.5 else contract["negative_label"]
    return {
        "dataset_label_prediction": label,
        "positive_label_probability": probability,
        "threshold": 0.5,
        "model_use": "research_only_not_for_student_decisions",
        "interpretation": "Agreement with dataset annotations only; not evidence of intent or misconduct.",
    }

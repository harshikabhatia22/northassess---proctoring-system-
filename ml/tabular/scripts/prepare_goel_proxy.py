"""Build student-level features from the supplied Goel assessment CSVs.

The resulting target is the source CSV's unverified `Cheater` proxy. This script
does not establish misconduct labels or person-level ground truth.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _json_list(value: str, *, context: str) -> list:
    try:
        result = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Invalid JSON in {context}: {exc}") from exc
    if not isinstance(result, list):
        raise TypeError(f"Expected a JSON list in {context}")
    return result


def _features_for_cohort(
    raw_path: Path,
    summary_path: Path,
    cohort: str,
) -> list[dict]:
    raw = pd.read_csv(raw_path, low_memory=False)
    summary = pd.read_csv(summary_path, low_memory=False)
    required_raw = {
        "Username/ID",
        "Question",
        "BT level",
        "Question-Visit-Timestamp",
        "Response-Submit-Timestamp",
        "Response",
        "Time",
        "Score",
        "Tab Switch",
    }
    missing_raw = required_raw.difference(raw.columns)
    if missing_raw:
        raise ValueError(f"{raw_path.name} missing columns: {sorted(missing_raw)}")
    if not {"Username/ID", "Cheater"}.issubset(summary.columns):
        raise ValueError(f"{summary_path.name} needs Username/ID and Cheater columns")
    if summary["Username/ID"].duplicated().any():
        raise ValueError(f"{summary_path.name} has duplicate student keys")
    if raw.duplicated(["Username/ID", "Question"]).any():
        raise ValueError(f"{raw_path.name} has duplicate student-question records")

    labels = summary.set_index("Username/ID")["Cheater"]
    if set(labels.dropna().unique()) != {0, 1}:
        raise ValueError(f"{summary_path.name} Cheater values must be exactly 0 and 1")
    if labels.isna().any():
        raise ValueError(f"{summary_path.name} has missing proxy labels")

    output: list[dict] = []
    for student_id, student_rows in raw.groupby("Username/ID", sort=True):
        if student_id not in labels.index:
            raise ValueError(f"No summary label for {cohort}:{student_id}")
        rows = student_rows.copy()
        numeric = ["Time", "Score", "Tab Switch"]
        for column in numeric:
            rows[column] = pd.to_numeric(rows[column], errors="raise")

        visits = [
            _json_list(value, context=f"{cohort}:{student_id}:visits")
            for value in rows["Question-Visit-Timestamp"]
        ]
        submissions = [
            _json_list(value, context=f"{cohort}:{student_id}:submissions")
            for value in rows["Response-Submit-Timestamp"]
        ]
        visit_counts = [len(value) for value in visits]
        revision_counts = [max(0, len(value) - 1) for value in submissions]
        response_changes = 0
        for attempts in submissions:
            previous = None
            for attempt in attempts:
                if not isinstance(attempt, list) or not attempt:
                    raise ValueError(f"Malformed response submission for {cohort}:{student_id}")
                current = attempt[0]
                if previous is not None and current != previous:
                    response_changes += 1
                previous = current

        times = rows["Time"].astype(float)
        scores = rows["Score"].astype(float)
        tabs = rows["Tab Switch"].astype(float)
        feature = {
            "group_id": f"{cohort}:{student_id}",
            "assessment_id": cohort,
            "n_questions": len(rows),
            "score_total": float(scores.sum()),
            "score_rate": float(scores.mean()),
            "time_total_seconds": float(times.sum()),
            "time_mean_seconds": float(times.mean()),
            "time_median_seconds": float(times.median()),
            "time_std_seconds": float(times.std(ddof=0)),
            "time_max_seconds": float(times.max()),
            "tab_switch_total": float(tabs.sum()),
            "questions_with_tab_switch": int((tabs > 0).sum()),
            "tab_switch_question_rate": float((tabs > 0).mean()),
            "tab_switch_max_on_question": float(tabs.max()),
            "question_visits_total": int(sum(visit_counts)),
            "questions_revisited": int(sum(count > 1 for count in visit_counts)),
            "question_visit_mean": float(sum(visit_counts) / len(visit_counts)),
            "questions_with_response_revision": int(sum(count > 0 for count in revision_counts)),
            "response_revision_total": int(sum(revision_counts)),
            "response_change_total": int(response_changes),
            "score_hots_mean": float(
                scores[rows["BT level"].astype(str).str.upper() == "HOTS"].mean()
            ),
            "score_lots_mean": float(
                scores[rows["BT level"].astype(str).str.upper() == "LOTS"].mean()
            ),
            "time_hots_mean_seconds": float(
                times[rows["BT level"].astype(str).str.upper() == "HOTS"].mean()
            ),
            "time_lots_mean_seconds": float(
                times[rows["BT level"].astype(str).str.upper() == "LOTS"].mean()
            ),
            "Cheater": int(labels.loc[student_id]),
        }
        output.append(feature)

    if set(raw["Username/ID"].unique()) != set(labels.index):
        raise ValueError(f"Raw and summary student IDs differ for {cohort}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_dir
    features = []
    features += _features_for_cohort(
        source / "Raw_Dataset1.csv", source / "Dataset1 (1).csv", "assessment_1"
    )
    features += _features_for_cohort(
        source / "Raw_Dataset2.csv", source / "Dataset2.csv", "assessment_2"
    )
    result = pd.DataFrame(features)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    print(
        f"Wrote {len(result)} student-level rows with {len(result.columns)} columns to {args.output}"
    )
    print(
        "Cheater is retained only as an unverified proxy target; do not report metrics as misconduct accuracy."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

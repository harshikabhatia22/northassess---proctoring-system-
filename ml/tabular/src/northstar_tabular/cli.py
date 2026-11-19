"""Command-line entry points for repeatable dataset inspection and evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from northstar_tabular.pipeline import (
    PipelineError,
    inspect_data,
    load_dataset,
    predict,
    train_and_evaluate,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="northstar-tabular")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="validate provenance and summarize the CSV")
    inspect.add_argument("manifest", type=Path)
    inspect.add_argument(
        "--allow-unreviewed-research-data",
        action="store_true",
        help="explicitly permit local research-only inspection despite unresolved provenance",
    )
    train = commands.add_parser(
        "train", help="train baselines and evaluate once on a held-out split"
    )
    train.add_argument("manifest", type=Path)
    train.add_argument("--output", type=Path, default=Path("artifacts/tabular/run"))
    train.add_argument("--seed", type=int, default=42)
    train.add_argument("--test-size", type=float, default=0.2)
    train.add_argument(
        "--allow-unreviewed-research-data",
        action="store_true",
        help="explicitly permit a local exploratory run despite unresolved provenance/labels",
    )
    predict_cmd = commands.add_parser("predict", help="run strict one-row research inference")
    predict_cmd.add_argument("model", type=Path)
    predict_cmd.add_argument(
        "payload", type=Path, help="JSON object containing exact model feature names"
    )
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            dataset = load_dataset(
                args.manifest, allow_unreviewed=args.allow_unreviewed_research_data
            )
            result = inspect_data(dataset)
        elif args.command == "train":
            dataset = load_dataset(
                args.manifest, allow_unreviewed=args.allow_unreviewed_research_data
            )
            result = train_and_evaluate(
                dataset, args.output, seed=args.seed, test_size=args.test_size
            )
        else:
            result = predict(args.model, json.loads(args.payload.read_text(encoding="utf-8")))
        print(json.dumps(result, indent=2, default=str))
        return 0
    except (PipelineError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

"""Command line interface for provenance-gated vision data work."""

from __future__ import annotations

import argparse
import json

from northstar_vision.audit import audit_archive, write_report


def main() -> None:
    parser = argparse.ArgumentParser(prog="northstar-vision")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser(
        "audit", help="inspect a local YOLO-style ZIP without extracting it"
    )
    audit.add_argument("archive")
    audit.add_argument("--output", help="write JSON report to this path")
    train = subparsers.add_parser("train", help="fit and evaluate a grouped HOG/SVM detector")
    train.add_argument("archive")
    train.add_argument("--output-dir", required=True)
    train.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.command == "audit":
        report = audit_archive(args.archive)
        if args.output:
            write_report(report, args.output)
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.command == "train":
        from northstar_vision.training import train_and_evaluate

        train_and_evaluate(args.archive, args.output_dir, args.seed)


if __name__ == "__main__":
    main()

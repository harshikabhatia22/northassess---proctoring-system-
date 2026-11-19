# Phase 3 — Tabular ML pipeline

This package is an original, provenance-gated research pipeline for tabular classification. It does not connect predictions to the exam API or student records. A prediction describes only the model's agreement with a declared dataset label; it does not establish intent, misconduct, attention, honesty, or a policy violation.

## Dataset status

The alternate [Goel online-assessment CSV candidate](datasets/goel-internet-cheating-v1/SOURCE_REVIEW.md) has been used for a local exploratory proxy-label run at the project owner's request. The source repository exposes no explicit data reuse terms, and the paper says ground truth was unavailable. Metrics are agreement with the CSV's unverified `Cheater` field only. Do not distribute its data or artifacts, deploy the model, or describe results as cheating-detection performance. By default, the provenance gate remains in force; this specific run required the explicit `--allow-unreviewed-research-data` option.

The candidate record is [Mendeley Data DOI 10.17632/39xs8th543.1](https://data.mendeley.com/datasets/39xs8th543/1). The record lists CC BY 4.0 and describes 5,500 simulated frame-level rows from 30+ volunteers. Its record description reports 38 attributes, while the reproduction section says 37 features plus labels. It describes labels as manually annotated using observation logs and session context.

The canonical record now exposes the named CSV and two feature-table documents, but its direct file endpoints returned an error body and the official Download All route returned HTTP 500; the public metadata API returned HTTP 401. The record lists CC BY 4.0, but the downloaded archive, file-level notices, exact schema, participant/session identifiers, CSV checksum, and label protocol remain unverified. Its archive listing reports SHA-256 `83d887700e227d0bf622dc1ca7626fe7f7c0de6dd5d9074acdf11ffc0b882e81`; this record-provided digest is not a verified local file hash. `datasets/mendeley-proctoring-v1/manifest.json` records these gaps and intentionally has `provenance_reviewed: false` and a placeholder CSV checksum. The CLI refuses to inspect or train until the local file is acquired and reviewed. Do not mark provenance reviewed just to bypass the check.

No dataset files are stored in this repository. Keep raw files out of Git. Obtain the dataset only from its canonical record, record the retrieval date and SHA-256, inspect all files and their license notices, resolve the attribute-count discrepancy, identify the exact target and group identifiers, and update the manifest. If identity/session grouping or label provenance cannot be established, document that limitation and do not claim cross-person generalization. A row-wise split is allowed only as exploratory and leakage-prone.

For the owner-supplied Goel files, local ignored copies and the derived feature CSV are under `ml/tabular/data/goel-v1/`. Recreate the 111 student-level features with:

```sh
cd ml/tabular
uv run --locked python scripts/prepare_goel_proxy.py --source-dir data/goel-v1/source --output data/goel-v1/features.csv
uv run --locked northstar-tabular inspect data/goel-v1/manifest.json --allow-unreviewed-research-data
uv run --locked northstar-tabular train data/goel-v1/manifest.json --allow-unreviewed-research-data --output ../../artifacts/tabular/goel-v1 --seed 42
uv run --locked northstar-tabular train data/goel-v1/manifest.json --allow-unreviewed-research-data --output ../../artifacts/tabular/goel-v1-reverse --seed 1
```

The explicit override records an owner-authorized local exploratory run while leaving `license_reviewed` and `provenance_reviewed` false. It does not clear the source-license or label-validation gates. Run artifacts are ignored by Git and must not be distributed or connected to the exam product.

## Setup and commands

Use Python 3.11+ and the isolated lockfile:

```sh
cd ml/tabular
uv sync --extra dev
uv run pytest
uv run northstar-tabular inspect datasets/mendeley-proctoring-v1/manifest.json
uv run northstar-tabular train datasets/mendeley-proctoring-v1/manifest.json --output ../../artifacts/tabular/mendeley-v1 --seed 42
```

The last two commands are expected to stop until the manifest and local CSV are fully verified. They do not download data. `inspect` validates the manifest, checksum, CSV, target, features, missingness, duplicates, group field, and possible target-leakage column names. Training creates a deterministic group holdout when `group_column` is verified; otherwise it uses a stratified row holdout and labels that split accordingly. It compares a majority baseline, logistic regression, and random forest. Preprocessing is fitted on training rows only. The single held-out test split is not used for tuning.

Generated run outputs are `evaluation.json`, `MODEL_CARD.md`, and `model.joblib` under the requested ignored artifacts directory. Metrics include precision, recall, F1, ROC-AUC, average precision, Brier score, log loss, confusion matrix, class counts, seed, split type, and data hash. These are measures of agreement with dataset labels only. They are not live-product performance estimates.

The inference CLI requires exactly the model's feature names, rejects extra/missing columns, non-finite numbers, and type mismatches, and returns a research-only annotation prediction. Unknown categorical values are handled by the fitted encoder. No API or UI currently loads this artifact.

## Acceptance and limitations

- The default dataset gate requires verified provenance. This one local run used the explicit owner-authorized exploratory override; this does not clear reuse rights or target-validity requirements for future sharing or deployment.
- Tests use generated fixture rows only to validate code mechanics. Their scores are not project model metrics and are not reported as such.
- Without verified person/session groups, estimates may reflect repeated frames or the scripted collection protocol, not generalization to new students or environments.
- Dataset annotations are not ground truth. The candidate's binary “cheating” framing is not adopted as an operational product concept.
- No subgroup fairness, calibration study, external validation, deployment, automatic decisions, or misconduct detection claim is included.

Scikit-learn preprocessing, pipeline, and evaluation primitives follow the project's pinned environment; see the [official installation guide](https://scikit-learn.org/stable/install) and [evaluation metrics guide](https://scikit-learn.org/stable/modules/model_evaluation.html).

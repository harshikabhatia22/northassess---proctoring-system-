# Dataset candidate review — Goel online-assessment logs

## Source and files

- Public source repository: <https://github.com/anitagoel/Dataset>
- Associated study: Manika Garg and Anita Goel, “Detection of Internet Cheating in Online Assessments Using Cluster Analysis,” DOI <https://doi.org/10.1007/978-981-99-1414-2_7>.
- Four CSVs were supplied locally by the project owner. The raw files are not copied into this repository.
- The repository page lists the CSVs but no explicit dataset reuse license was found. Repository visibility is not treated as a reuse license. Training is blocked until reuse terms are verified.

## Local structural review

| Supplied file | Rows | Columns | Notes |
|---|---:|---:|---|
| `Dataset1 (1).csv` | 60 | 15 | Student-level aggregates; `Cheater` values: 39 zero, 21 one. |
| `Dataset2.csv` | 51 | 15 | Student-level aggregates; `Cheater` values: 37 zero, 14 one. |
| `Raw_Dataset1.csv` | 900 | 9 | Question-level logs; 60 pseudonymous student IDs × 15 questions. |
| `Raw_Dataset2.csv` | 765 | 9 | Question-level logs; 51 pseudonymous student IDs × 15 questions. |

SHA-256 checksums of the supplied files:

- `Dataset1 (1).csv`: `c2ee2b6dab7d22874197814157562231dda1ddbf233c7cf9f115bbe9b002c5c0`
- `Dataset2.csv`: `5587321f9dd181ee2a8b821184ee3f8069fd492fec0a567863a56fbdfa3049f1`
- `Raw_Dataset1.csv`: `e0249a50e6ac148e455f36dfbce9c15926ca09b8801a417d6feb081f5d254781`
- `Raw_Dataset2.csv`: `1c1a7987cac1c8f4db9d88dfc18c516ba0e37d241c5ab4e6defa61cd387f8211`

The raw files contain response, score, time, tab-switch count, and visit/submission timestamps. No missing values or duplicate student-question pairs were found in the supplied raw files. The IDs look pseudonymous (`StudentN`), but timestamps remain detailed. No IP-address column appears in the supplied files.

## Interpretation and limitations

- The study describes 1,665 question records from 111 students across two lab-based online assessments and uses unsupervised K-means clustering. It says the suspected-cheating interpretation is a hypothesis and explicitly notes that ground truth was unavailable.
- The CSVs' `Cheater` column is therefore recorded as an **unverified proxy label**, not verified cheating ground truth. Any metric against it would measure agreement with that proxy only.
- The supplied data concerns online assessment interaction and possible internet use (including tab switching). It is not webcam, gaze, or general-purpose proctoring data.
- The raw IDs are repeated as `Student1`, etc. across the two datasets. It is unknown whether IDs map across assessments; do not merge identities or claim person-level generalization without a source explanation.
- The summary CSV columns do not match the paper's described seven-feature student-level matrix exactly. Column meanings and the creation of the extra `Cheater` field need source documentation.
- The study reports personally identifying fields such as usernames and says IP addresses were recorded in the collection system, although not used for its analysis. The supplied CSVs contain pseudonymous IDs and no IP column; retain local-only handling and avoid publishing raw rows.

## Gate decision

The project owner explicitly authorized a local exploratory run on 2026-11-18. This authorization is recorded in the ignored local manifest; it does not establish a data license or authorize redistribution. The run uses the unverified `Cheater` field only as a proxy target.

The training pipeline remains gated by default. For this one local run only, the `--allow-unreviewed-research-data` flag was used as an explicit opt-in. The unresolved conditions for reuse beyond this local exploratory run are:

1. Explicit reuse terms covering the CSV data must be verified before sharing or redistributing data, features, or artifacts.
2. The meaning and construction of `Cheater` remain undocumented. It is not a ground-truth target and cannot support claims about actual cheating.

## Exploratory proxy-label runs

The raw question logs were transformed into 111 student-level records with 22 numeric behavior/performance features. Pseudonymous group IDs were used only as split metadata and excluded from model features. The two assessments were held out from each other in turn:

| Train cohort | Held-out cohort | Model | Accuracy | Precision | Recall | F1 | ROC-AUC |
|---|---|---|---:|---:|---:|---:|---:|
| Assessment 1 (60 students) | Assessment 2 (51 students) | Logistic regression | 0.980 | 1.000 | 0.929 | 0.963 | 1.000 |
| Assessment 1 (60 students) | Assessment 2 (51 students) | Random forest | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Assessment 2 (51 students) | Assessment 1 (60 students) | Logistic regression | 0.800 | 1.000 | 0.429 | 0.600 | 0.915 |
| Assessment 2 (51 students) | Assessment 1 (60 students) | Random forest | 0.967 | 0.913 | 1.000 | 0.955 | 1.000 |

These numbers measure agreement with the unverified `Cheater` proxy only. The unusually high agreement may reflect that the proxy was assigned from the same behavioral feature space; it is not evidence that the models detect real-world cheating. The cohorts are small, there are only two, and neither run validates deployment or student-level decisions. The local reports and artifacts are under `artifacts/tabular/goel-v1/` and `artifacts/tabular/goel-v1-reverse/` (ignored by Git).

Do not commit the supplied data. Do not publish or deploy these model artifacts. Any future training/evaluation remains research-only and disconnected from student decisions.

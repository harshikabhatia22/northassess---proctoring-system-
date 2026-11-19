# Phase 4 — Computer vision

This package contains an original dataset auditor, a from-scratch HOG + linear-SVM detector, grouped evaluation, and a private versioned FastAPI inference contract. It has no webcam capture and is not connected to attempts or student outcomes.

## Dataset

The local original archive is at ignored path `data/zenodo-students-online-exam-v1/`. The canonical source is [Zenodo DOI 10.5281/zenodo.14606173](https://zenodo.org/records/14606173), record-stated CC BY 4.0. The archive MD5 matches the record; see the [source review](datasets/zenodo-students-online-exam-v1/SOURCE_REVIEW.md), [annotation spec](datasets/zenodo-students-online-exam-v1/ANNOTATION_SPEC.md), and [manifest](datasets/zenodo-students-online-exam-v1/manifest.json).

The supplied train/valid split leaks all 38 filename-derived groups across both subsets. The separate test directory is unlabeled and has five exact duplicate images across existing splits. Training uses the 5,494 labeled train+valid images with a new holdout of eight filename-derived source groups. This is a recording-name split only; the archive contains no verified participant IDs.

## Supplemental object dataset candidate

I found a non-Mendeley [Roboflow Online Proctoring System dataset](https://universe.roboflow.com/online-exam-cheating-detection-kvdul/online-proctoring-system-x27ou-e7abr), version 1. The page lists CC BY 4.0 and six object classes: book, laptop, cell phone, person, headphone, and tv. Its version page reports 25,173 images, but the overview and description report different totals. It is object data, not cheating labels, and it does not document participant/session IDs or human-subject consent. Use it only as supplemental object-detection research data pending archive and license review. See [source review](datasets/roboflow-online-proctoring-v1/SOURCE_REVIEW.md) and [manifest](datasets/roboflow-online-proctoring-v1/manifest.json).

The export is available from the [version 1 download page](https://universe.roboflow.com/online-exam-cheating-detection-kvdul/online-proctoring-system-x27ou-e7abr/dataset/1). The download endpoint timed out here and may require Roboflow sign-in/API access. If you can access it, select YOLOv8 or YOLOv11 export and send the ZIP; I can then audit its actual contents and train an object detector. Do not send API keys in chat.

## Audit and training

The local run used the exact direct dependency pins in `requirements.txt`. On a fresh machine, install them with network access. Run commands from `ml/vision`:

```sh
python3 -m pip install -r requirements.txt
PYTHONPATH=src python3 -m northstar_vision.cli audit data/zenodo-students-online-exam-v1/Dataset_Students_Behavior_Online_Exam_Org.zip --output ../../artifacts/vision/zenodo-students-online-exam-v1/audit.json
PYTHONPATH=src python3 -m northstar_vision.cli train data/zenodo-students-online-exam-v1/Dataset_Students_Behavior_Online_Exam_Org.zip --output-dir ../../artifacts/vision/zenodo-students-online-exam-v1/hog-svm-grouped-seed42-v3 --seed 42
```

For the training command, use the exact filename `Dataset_Students_Behavior_Online_Exam_Org.zip` as in the audit command. The trainer excludes the one zero-area box and the 81 unlabeled test images, fits per-class HOG/SVM detectors from scratch, records the group split, measures per-class AP/precision/recall and CPU latency, and saves `detector.joblib`, `split.json`, `evaluation.json`, and `MODEL_CARD.md` under ignored `artifacts/`.

The first baseline (v1) scored macro mAP@0.5 **0.0675** and mAP@[0.5:0.95] **0.0177**. V2 added horizontal-flip augmentation and a wider scale scan, scoring **0.0712** and **0.0248**. V3 adds hard-negative mining using training groups only; it scored **0.0572** and **0.0201**. At the fixed SVM margin, V3 increased macro precision from **0.0164** (v2) to **0.0409**, while macro recall decreased from **0.5390** to **0.3786**. These are comparisons on the same seed-42 holdout already inspected during v1/v2, so all are exploratory, not fresh validation. V3 is not an overall improvement and remains unsuitable for real exams. Metrics describe visible annotation agreement, not cheating or intent. No pretrained weights are used.

## Inference API

The internal API is `POST /api/v1/detect` with `image/jpeg` or `image/png`, an `X-Internal-API-Key`, and maximums of 4 MiB / 8 megapixels. It emits a versioned model ID, dataset hash, visible-behavior class names, uncalibrated SVM margins, bounding boxes, and latency. The health endpoints are `/health/live` and `/api/v1/health/ready`.

Start locally from `ml/vision` after training:

```sh
export VISION_MODEL_PATH=../../artifacts/vision/zenodo-students-online-exam-v1/hog-svm-grouped-seed42-v3/detector.joblib
export VISION_INTERNAL_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
PYTHONPATH=src python3 -m uvicorn northstar_vision.api:app --host 127.0.0.1 --port 8787
```

Keep the service on a private network and have callers set a five-second timeout. Its bounded inference pool and errors are independent of attempt submission. The model has no calibrated confidence threshold and should remain disabled for live students until validation improves and participant rights are clarified.

## Environment note

The `uv.lock` for this package could not be generated in this environment because DNS access to PyPI is blocked. Direct dependency versions are pinned in `requirements.txt`, but transitive dependencies are not locked. Current observed versions and metrics are recorded in each run's `evaluation.json`. A normal TCP listener was also blocked by the local execution sandbox; the ASGI routes were exercised in-process.

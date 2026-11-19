# Phase 4 vision dataset source review

## Candidate and current evidence

Canonical source: [Zenodo record 14606173](https://zenodo.org/records/14606173), DOI `10.5281/zenodo.14606173`, version 2. The visible record identifies creator Muhanad Alkhalisy, marks the record open, and displays Creative Commons Attribution 4.0 International. The selected original archive is `Dataset_Students_Behavior_Online_Exam_Org.zip` (833.8 MB; record MD5 `78fde2372a5a58efba55ed4d47039429`). The separate augmented archive is 6.4 GB and is not selected.

The archive's MD5 matches the record and ZIP integrity check passes. Its SHA-256 is `ca94adccd9745f819d912435c68197adfe59bca3a0f644b5c36a92f522dffe52`. It contains 5,575 640x640 JPEGs, 5,494 labeled images, 5,511 annotation rows, and the class map in `ANNOTATION_SPEC.md`. Image decoding found no unreadable images. One annotation has a zero-width box; 81 `test` images have no label files. The class-count total is instance count, not number of images.

The archive `data.yaml` paths are placeholders and do not match its actual `train`, `valid`, and `test` folders. All 38 filename-derived source groups occur in both supplied `train` and `valid`, so their split cannot be used as a clean evaluation. The supplied `test` folder is unlabeled and contains five exact images that also appear in train/valid. It will be excluded. The filename groups are provisional recording proxies, not verified participant/session IDs. The linked paper reports a different image count, dimensions, and—in one passage—JSON annotations; its model results are not this project's results.

## Rights and scientific limitations

The record's CC BY 4.0 label permits reuse subject to attribution and license terms. The associated paper says participants should agree before recording and discusses privacy, but it does not provide a clear ethics approval or consent statement confirming these specific images. Keep this as a local research dataset; do not publish sample images or deploy its model to make decisions. Behaviors are visual annotations, not ground truth for cheating, intent, attention, or policy violations. [Associated paper](https://iasj.rdd.edu.iq/journals/uploads/2025/08/09/f44c738b6244ae6597bb37c1576ebb47.pdf).

Single-institution collection and unknown participant/session identifiers may prevent a defensible person-independent split. If identity/session grouping cannot be recovered, report only the precise weaker split performed and do not claim generalization to unseen people.

## Current data disposition

The owner supplied the original archive for Phase 4. Its record MD5 and ZIP integrity checks pass. The manifest remains `provenance_reviewed: false` because image-subject consent and participant/session grouping are unverified. Owner-authorized local exploratory detectors v1, v2, and v3 were trained and evaluated; metrics/model cards are under ignored `artifacts/vision/zenodo-students-online-exam-v1/hog-svm-grouped-seed42/`, `.../hog-svm-grouped-seed42-v2/`, and `.../hog-svm-grouped-seed42-v3/`. V2 and v3 reuse the v1 holdout, so their scores are exploratory comparisons, not independent validation. V3 raised fixed-margin macro precision while lowering macro mAP@0.5 versus v2. None is deployment evidence.

The archive is stored only under ignored local path `ml/vision/data/zenodo-students-online-exam-v1/Dataset_Students_Behavior_Online_Exam_Org.zip`; it is not committed. The 6.4 GB augmented archive is excluded. Audit command:

```sh
cd ml/vision
uv run northstar-vision audit data/zenodo-students-online-exam-v1/Dataset_Students_Behavior_Online_Exam_Org.zip --output ../../artifacts/vision/zenodo-students-online-exam-v1/audit.json
```

Raw images and model artifacts remain in ignored local paths. Do not publish sample images or deploy the model. Any expanded use requires institution/privacy review and better evidence about participant consent and identity/source grouping.

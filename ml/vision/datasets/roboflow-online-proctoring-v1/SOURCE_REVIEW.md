# Roboflow Online Proctoring object dataset review

## Finding

The public [Online Proctoring System project](https://universe.roboflow.com/online-exam-cheating-detection-kvdul/online-proctoring-system-x27ou-e7abr) has a version 1 export in YOLO and other annotation formats. The page lists six object classes: book, laptop, cell phone, person, headphone, and tv. The version page reports 25,173 images, split into 22,440 train, 1,822 validation, and 911 test items. The project overview separately reports 10,213 images and its description says 15,489 images before augmentation. The version reports three augmented outputs per training example. These counts need to be reconciled against the archive.

The version page lists CC BY 4.0. The project description also says licensing terms should be defined in Kaggle settings. Treat the license as source-stated but unresolved until the archive metadata and source-owner terms are checked. Do not redistribute or deploy this data before that review.

## Fit and limits

This is useful only as supplemental object-detection data for objects such as phones and books. It does not label cheating, intent, or suspicious behavior. The public project page does not document participant/session IDs or human-subject consent/ethics approval. It cannot support a participant-independent evaluation. The augmented split may also contain near-duplicate source images across subsets, so duplicate checks are required before using its validation/test split.

The displayed model metrics are publisher-provided site values, not project measurements, and are not reproduced or claimed here.

## Access and next checks

The [version 1 export page](https://universe.roboflow.com/online-exam-cheating-detection-kvdul/online-proctoring-system-x27ou-e7abr/dataset/1) provides YOLOv8, YOLOv11, COCO, and other exports. The download endpoint timed out from the current environment and may require a Roboflow account/API key. No dataset archive has been downloaded, so local size, checksum, labels, and actual license files are not yet verified. Manifest: [`manifest.json`](manifest.json).

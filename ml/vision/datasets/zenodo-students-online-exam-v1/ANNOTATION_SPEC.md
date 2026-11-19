# Provisional annotation specification

**Status: checked against the supplied original archive.**

## Record-described task

The archive's `classes.txt` confirms these detection labels in order:

| ID | Class name |
|---:|---|
| 0 | `eye_movement` |
| 1 | `hand_move` |
| 2 | `mobile_use` |
| 3 | `side_watching` |
| 4 | `mouth_open` |

These are dataset class descriptions, not findings of intent, cheating, attention, or rule violations. The archive also contains a `data.yaml` with placeholder paths that do not resolve inside the ZIP. Its directory names are `train`, `valid`, and an unlabeled `test` folder; the source config's `val` path is not usable as written.

## Expected YOLO detection row

The record says YOLO DarkNet53/COCO style. The provisional expected row is:

```text
<class_id> <x_center> <y_center> <width> <height>
```

Coordinates are expected to be normalized to `[0, 1]`; width and height must be positive; class IDs must be non-negative integers. An empty label file may indicate an image with no annotated instances and must be counted, not silently dropped. Multi-object images may contain multiple rows.

## Acceptance checks before any split or training

- Confirmed: UTF-8 text, five YOLO fields, normalized center/width/height coordinates, and class map above. One annotation has zero width and must be excluded or corrected only with an auditable rule.
- Decode images and confirm each annotation references a real image with consistent dimensions and no corrupt file.
- Report missing labels, unmatched labels, empty labels, duplicate image content, class counts, invalid/out-of-frame boxes, and any non-image files.
- The supplied train/valid sets share all 38 groups derived from the filename prefix before the frame number. These are only candidate source-video groups, not verified participant/session IDs. Any new split must group these prefixes; results cannot establish person-independent generalization.
- The 81 images in the supplied test folder have no labels and five are exact duplicates of train/valid images; do not use that folder for evaluation.
- Decoded-image check: all 5,575 files open as 640x640 JPEGs.
- The associated paper was reviewed. It discusses consent/privacy but does not clearly document participant consent or ethics approval for this image set. A user-authorized local research baseline was run under the record-stated CC BY 4.0 terms; this is not authorization for public image redistribution or production use.
- Freeze the mapping and rules in a versioned spec update and record the spec hash with every model run.

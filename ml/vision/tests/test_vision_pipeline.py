from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from northstar_vision.audit import audit_archive
from northstar_vision.inference import infer_image_bytes
from northstar_vision.training import grouped_holdout, source_group


class VisionPipelineTests(unittest.TestCase):
    def test_audit_reports_missing_labels_and_invalid_boxes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "sample.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("root/classes.txt", "phone\n")
                archive.writestr("root/data.yaml", "train: root/train/images\nval: bad/images\n")
                archive.writestr("root/train/images/one.jpg", b"not-decoded-by-archive-audit")
                archive.writestr(
                    "root/train/labels/one.txt",
                    "0 0.5 0.5 0.2 0.2\n0 0.5 0.5 0 0.2\n",
                )
                archive.writestr("root/valid/images/two.jpg", b"no label")

            report = audit_archive(str(archive_path))

        self.assertEqual(report["image_count"], 2)
        self.assertEqual(report["missing_label_count"], 1)
        self.assertEqual(report["invalid_box_count"], 1)
        self.assertEqual(report["class_names_by_id"], {"0": "phone"})
        self.assertIsNone(report["corrupt_zip_entry"])

    def test_filename_source_group_handles_double_extension(self) -> None:
        self.assertEqual(source_group("root/train/images/satu-4 469.jpg.jpg"), "satu-4")

    def test_group_holdout_has_no_source_overlap_and_all_classes(self) -> None:
        records = []
        for group_id in range(10):
            records.append(
                {
                    "image_path": f"{group_id} frame.jpg",
                    "source_group": f"source-{group_id}",
                    "boxes": [
                        {"class_id": class_id, "box": [0.0, 0.0, 10.0, 10.0]}
                        for class_id in range(5)
                    ],
                }
            )
        split = grouped_holdout(records, seed=17, fraction=0.2)
        self.assertFalse(set(split["train_groups"]) & set(split["test_groups"]))
        self.assertEqual(split["test_images"], 2)

    def test_invalid_inference_payloads_are_rejected(self) -> None:
        for payload, expected in [
            (b"", ValueError),
            (b"not an image", ValueError),
            (b"x" * (4 * 1024 * 1024 + 1), OverflowError),
        ]:
            with self.subTest(error=expected.__name__), self.assertRaises(expected):
                infer_image_bytes({}, payload)


if __name__ == "__main__":
    unittest.main()

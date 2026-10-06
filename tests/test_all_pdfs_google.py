# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import google_drive_ocr
import step3_5_attachments


class AllPdfsGoogleTest(unittest.TestCase):
    def test_local_attachment_stage_never_extracts_pdf(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp_dir:
            root = Path(temp_dir)
            attachments = root / "attachments"
            emails = root / "emails"
            output = root / "attachments_text"
            attachments.mkdir()
            emails.mkdir()
            (attachments / "digital.pdf").write_bytes(b"fake-pdf")

            with patch.object(
                step3_5_attachments,
                "pdf_digital_to_md",
                side_effect=AssertionError("PyMuPDF must not run in the production PDF path"),
            ):
                stats = step3_5_attachments.process_attachments(
                    str(attachments), str(emails), str(output), {}
                )

            self.assertEqual(stats, {"md": 0, "skip": 1, "err": 0})
            self.assertFalse((output / "digital.md").exists())

    def test_local_markdown_does_not_prevent_google_pdf_conversion(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp_dir:
            root = Path(temp_dir)
            attachments = root / "attachments"
            output = root / "attachments_ocr_google"
            local_output = root / "attachments_text"
            attachments.mkdir()
            output.mkdir()
            local_output.mkdir()
            pdf_path = attachments / "digital.pdf"
            pdf_path.write_bytes(b"fake-pdf")
            (local_output / "digital.md").write_text("old local output", encoding="utf-8")

            def fake_convert(file_path, output_md_path, **kwargs):
                Path(output_md_path).write_text("google output", encoding="utf-8")
                return True

            with (
                patch.object(google_drive_ocr, "get_drive_service", return_value=object()),
                patch.object(
                    google_drive_ocr,
                    "convert_file_to_md_gdrive",
                    side_effect=fake_convert,
                ) as convert_mock,
                patch.object(google_drive_ocr.time, "sleep"),
            ):
                stats = google_drive_ocr.batch_convert_all(
                    str(attachments), str(output), attachment_manifest={}
                )

            self.assertEqual(convert_mock.call_count, 1)
            self.assertEqual(stats["converted"], 1)
            self.assertEqual(stats["digital"], 0)
            self.assertTrue((output / "digital.md").exists())


if __name__ == "__main__":
    unittest.main()

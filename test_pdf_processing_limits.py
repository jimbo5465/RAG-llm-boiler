# -*- coding: utf-8 -*-
"""آزمون سیاست حجم/تعداد صفحات بدون درخواست واقعی به گوگل."""
import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
import google_drive_ocr as ocr


class PdfProcessingLimitsTest(unittest.TestCase):
    def run_case(self, pages, size_mb, expected_pages, partial):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            output = Path(directory) / "output.md"
            with pymupdf.open() as document:
                for index in range(pages):
                    page = document.new_page()
                    page.insert_text((72, 72), f"SOURCE PAGE {index + 1} - valid digital document content")
                document.save(source)
            original = source.read_bytes()

            with (
                patch.object(ocr.os.path, "getsize", return_value=int(size_mb * 1024 * 1024)),
                patch.object(ocr, "ocr_single_media_gdrive", side_effect=AssertionError('Healthy digital PDF must remain local')) as upload,
                patch("table_postprocessor.detect_and_format_tables", side_effect=lambda text: text),
            ):
                self.assertTrue(ocr.convert_file_to_md_gdrive(str(source), str(output), service=object()))
            self.assertEqual(upload.call_count, 0)
            self.assertEqual(source.read_bytes(), original)
            text = output.read_text(encoding="utf-8")
            self.assertIn(f"از {pages} صفحه", text)
            report = json.loads((output.parent / 'ocr_quality_report.json').read_text(encoding='utf-8'))[output.name]
            self.assertEqual(report['total'], pages)
            self.assertEqual(report['processed'], expected_pages)
            self.assertEqual(report['partial'], partial)
            self.assertEqual(report['local_pages'], list(range(1, expected_pages + 1)))
            self.assertFalse(output.with_suffix('.prepared.pdf').exists())
            self.assertFalse(output.with_suffix('.preparation.json').exists())
            self.assertFalse((output.parent / '_ocr_diagnostics').exists())
            self.assertEqual("این خروجی متن کامل سند نیست" in text, partial)

    def test_page_limit_independent_of_size(self):
        self.run_case(16, 1, 5, True)

    def test_size_limit_independent_of_page_count(self):
        self.run_case(10, 10.01, 5, True)

    def test_exact_thresholds_process_whole_document(self):
        self.run_case(15, 10, 15, False)

    def test_large_source_is_truncated_before_upload_size_check(self):
        self.run_case(50, 30, 5, True)

    def test_short_large_file_has_no_false_partial_warning(self):
        self.run_case(4, 11, 4, False)


if __name__ == "__main__":
    unittest.main()

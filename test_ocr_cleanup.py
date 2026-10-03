# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf
import google_drive_ocr as ocr
import step4_rag
import pdf_page_pipeline


class CleanupTest(unittest.TestCase):
    def test_error_cleans_prepared_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.pdf', Path(directory) / 'output.md'
            with pymupdf.open() as doc:
                doc.new_page().insert_text((72, 72), 'Valid original document text for testing.')
                doc.save(source)
            before = source.read_bytes()
            with patch.object(pdf_page_pipeline, 'assess_local', return_value=('', {'needs_ocr': True, 'route_reasons': ['test']})), patch.object(ocr, 'ocr_single_media_gdrive', side_effect=RuntimeError('network test')), patch.object(pdf_page_pipeline.time, 'sleep'):
                ocr.convert_file_to_md_gdrive(str(source), str(output), service=object())
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse(output.with_suffix('.prepared.pdf').exists())
            self.assertFalse((output.parent / '_ocr_diagnostics').exists())

    def test_compact_metadata_keeps_failed_page_out_of_rag(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.pdf', Path(directory) / 'output.md'
            with pymupdf.open() as doc:
                for _ in range(2):
                    doc.new_page().insert_text((72, 72), 'Valid original document text for testing.')
                doc.save(source)
            raw = 'RAGPAGE0001BEGIN A complete readable ordinary text for this correspondence page. RAGPAGE0001END'
            with patch.object(pdf_page_pipeline, 'assess_local', side_effect=[
                    ('A complete readable ordinary text for this correspondence page.', {'needs_ocr': False, 'route_reasons': [], 'status': 'PASS', 'characters': 65, 'reasons': []}),
                    ('', {'needs_ocr': True, 'route_reasons': ['empty']})]), patch.object(ocr, 'ocr_single_media_gdrive', return_value=''):
                ocr.convert_file_to_md_gdrive(str(source), str(output), service=object(), max_page_retries=0)
            text = output.read_text(encoding='utf-8')
            self.assertNotIn('روش_آماده‌سازی', text)
            self.assertNotIn('آماده_RAG', text)
            self.assertIn('خروجی ناقص', text)
            chunks = step4_rag.chunk_attachment_file(str(output))
            self.assertTrue(chunks)
            self.assertTrue(all('## صفحه 2' not in body for body, _ in chunks))
            self.assertEqual(json.loads((output.parent / 'ocr_quality_report.json').read_text(encoding='utf-8'))['output.md']['failed_pages'], [2])


if __name__ == '__main__':
    unittest.main()

# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
from PIL import Image

import google_drive_ocr as ocr
import pdf_ocr_quality as quality
import step4_rag
import pdf_page_pipeline


class QualityTest(unittest.TestCase):
    def test_raster_removes_bad_hidden_layer_and_preserves_image(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.pdf', Path(directory) / 'clean.pdf'
            image = Image.new('RGB', (200, 300), 'white')
            with pymupdf.open() as document:
                page = document.new_page(width=200, height=300)
                page.insert_image(page.rect, stream=quality.jpeg_bytes(image))
                page.insert_text((10, 20), 'iiiiiiii bad hidden scanner text')
                document.save(source)
            original = source.read_bytes()
            info = quality.prepare_pdf(source, output, rotation_overrides={1: 90})
            self.assertEqual(info['method'], 'rasterized_pdf')
            with pymupdf.open(output) as cleaned:
                self.assertFalse(cleaned[0].get_text().strip())
                self.assertTrue(cleaned[0].get_images())
                self.assertGreater(cleaned[0].rect.width, cleaned[0].rect.height)
            self.assertEqual(original, source.read_bytes())

    def test_missing_duplicate_and_reordered_markers_fail(self):
        for raw in ['RAGPAGE0001BEGIN content',
                    'RAGPAGE0001END text RAGPAGE0001BEGIN',
                    'RAGPAGE0001BEGIN RAGPAGE0001BEGIN content RAGPAGE0001END']:
            _, report = quality.split_and_check(raw, {'processed': 1})
            self.assertFalse(report['coverage_verified'])
            self.assertEqual(report['status'], 'FAIL')

    def test_normal_text_and_noise_are_distinguished(self):
        self.assertEqual(quality.evaluate_text('This is a complete ordinary sentence with sufficient readable content.')['status'], 'PASS')
        self.assertEqual(quality.evaluate_text('\n'.join(['i', 'b', 'S'] * 40))['status'], 'FAIL')
        self.assertEqual(quality.evaluate_text('DWG LENGTH ACT LENGTH DIFF 23862 23855 7 report for technical equipment')['status'], 'WARNING')

    def test_page_markers_do_not_hide_missing_key_content(self):
        info = {'processed': 1, 'pages': [{'source_anchors': ['Packing List', 'BOLT GAL', 'CASING']}]}
        raw = 'RAGPAGE0001BEGIN This is readable but crucial columns are missing from the output. RAGPAGE0001END'
        _, report = quality.split_and_check(raw, info)
        self.assertTrue(report['coverage_verified'])
        self.assertEqual(report['status'], 'FAIL')
        self.assertFalse(report['rag_ready'])
        result = quality.evaluate_text('This readable report contains its title but lacks the whole equipment section.')
        quality.check_anchors(result, 'CASING DIAGONAL report data and valid readable content', ['CASING', 'DIAGONAL', 'CALIBRATION'])
        self.assertEqual(result['status'], 'FAIL')

    def test_missing_page_does_not_reject_good_neighbour(self):
        info = {'processed': 2}
        raw = 'RAGPAGE0001BEGIN This is the entire readable content of the first document page. RAGPAGE0001END'
        _, report = quality.split_and_check(raw, info)
        self.assertFalse(report['coverage_verified'])
        self.assertEqual(report['pages'][0]['status'], 'PASS')
        self.assertEqual(report['pages'][1]['status'], 'FAIL')

    def test_retry_recovers_only_failed_page_and_keeps_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.pdf', Path(directory) / 'out.md'
            with pymupdf.open() as doc:
                doc.new_page().insert_text((72, 72), 'Valid digital source document for OCR testing')
                doc.save(source)
            with patch.object(pdf_page_pipeline, 'assess_local', return_value=('', {'needs_ocr': True, 'route_reasons': ['test']})), patch.object(ocr, 'ocr_single_media_gdrive', side_effect=[
                'RAGPAGE0001BEGIN i RAGPAGE0001END',
                'This is the complete readable recovered text for the first source page.'
            ]) as calls:
                self.assertTrue(ocr.convert_file_to_md_gdrive(str(source), str(output), service=object(), debug_errors=True))
            self.assertEqual(calls.call_count, 2)
            text = output.read_text(encoding='utf-8')
            self.assertIn('recovered text', text)
            self.assertNotIn('RAGPAGE', text)
            self.assertTrue((output.parent / '_ocr_diagnostics' / 'out' / 'page_0001.txt').exists())

    def test_rag_rejects_failed_quality_and_keeps_partial_context_in_every_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.md'
            header = '---\nپیوست: source.pdf\nتعداد_صفحات_اصلی: 80\nتعداد_صفحات_پردازش‌شده: 5\nصفحات_پردازش‌شده: 1-5\nپردازش_کامل: false\n'
            body = '\n\n'.join(['readable source text ' * 40] * 4)
            path.write_text(header + 'آماده_RAG: false\n---\n' + body, encoding='utf-8')
            self.assertEqual(step4_rag.chunk_attachment_file(str(path)), [])
            path.write_text(header + 'آماده_RAG: true\n---\n' + body, encoding='utf-8')
            chunks = step4_rag.chunk_attachment_file(str(path))
            self.assertGreater(len(chunks), 1)
            self.assertTrue(all('5 از 80 صفحه' in text for text, _ in chunks))

    def test_email_first_accepts_warnings_but_excludes_failed_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'accepted.md'
            path.write_text('---\nپیوست: original.pdf\nکیفیت_OCR: FAIL\nآماده_RAG: true\nسیاست_پذیرش: email_first_v1\nفایل_اصلی: emails/attachments/original.pdf\n---\n'
                            '## صفحه 1\n\n> کیفیت: WARNING جدول ناقص\n\nUseful readable correspondence content.\n\n'
                            '## صفحه 2\n\n> کیفیت: FAIL نویز\n\nTHIS_FAILED_PAGE_MUST_NOT_BE_INDEXED', encoding='utf-8')
            chunks = step4_rag.chunk_attachment_file(str(path))
            self.assertTrue(chunks)
            self.assertTrue(all('THIS_FAILED_PAGE' not in text for text, _ in chunks))
            self.assertTrue(all('emails/attachments/original.pdf' in text for text, _ in chunks))
            self.assertTrue(all(meta['source_role'] == 'supporting_attachment' for _, meta in chunks))
        report = {'pages': [{'number': 1, 'status': 'WARNING', 'characters': 100},
                            {'number': 2, 'status': 'FAIL', 'characters': 0}], 'coverage_verified': False}
        quality.update_status(report)
        self.assertTrue(report['rag_ready'])
        self.assertEqual(report['rag_usable_pages'], [1])
        report['pages'][0]['status'] = 'FAIL'
        quality.update_status(report)
        self.assertFalse(report['rag_ready'])


if __name__ == '__main__':
    unittest.main()

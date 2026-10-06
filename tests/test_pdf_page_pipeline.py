# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
from PIL import Image

import google_drive_ocr as ocr
import pdf_page_pipeline as pipeline
import pdf_ocr_quality as quality


class HybridTest(unittest.TestCase):
    def test_only_bad_page_is_uploaded_at_300dpi_and_inserted_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'source.pdf', root / 'out.md'
            with pymupdf.open() as doc:
                for n in range(3):
                    page = doc.new_page()
                    if n == 1:
                        image = Image.new('RGB', (200, 300), 'white')
                        page.insert_image(page.rect, stream=quality.jpeg_bytes(image))
                    else:
                        page.insert_text((72, 72), f'This is healthy local text for original page {n+1} of the report.')
                doc.save(source)
            before = source.read_bytes()

            def response(media, name, mime, service):
                self.assertEqual(name, 'page_0002_source.pdf')
                self.assertEqual(mime, 'image/jpeg')
                media.stream().seek(0)
                with Image.open(io.BytesIO(media.stream().read())) as image:
                    self.assertEqual(image.width, math.ceil(595 * 300 / 72))
                    self.assertGreater(image.height, 3500)
                # حتی با علامت‌های پشت‌سرهم، پاسخ فقط متعلق به صفحهٔ ۲ است.
                return 'RAGPAGE0002BEGIN RAGPAGE0002END Correctly recovered image text for the SECOND_PAGE correspondence.'

            with patch.object(ocr, 'ocr_single_media_gdrive', side_effect=response) as upload, patch.object(ocr, 'get_drive_service', side_effect=AssertionError('provided service')):
                ocr.convert_file_to_md_gdrive(str(source), str(output), service=object())
            self.assertEqual(upload.call_count, 1)
            text = output.read_text(encoding='utf-8')
            self.assertLess(text.index('original page 1'), text.index('SECOND_PAGE'))
            self.assertLess(text.index('SECOND_PAGE'), text.index('original page 3'))
            self.assertNotIn('RAGPAGE', text)
            self.assertEqual(text.count(quality.OCR_SOURCE_WARNING), 1)
            self.assertIn(quality.OCR_SOURCE_WARNING, text.split('## صفحه 2')[1].split('## صفحه 3')[0])
            self.assertEqual(before, source.read_bytes())
            report = json.loads((root / 'ocr_quality_report.json').read_text(encoding='utf-8'))['out.md']
            self.assertEqual(report['local_pages'], [1, 3])
            self.assertEqual(report['google_pages'], [2])
            self.assertGreater(report['upload_bytes'], 0)
            self.assertFalse((root / '_ocr_diagnostics').exists())
            self.assertFalse(list(root.glob('*.prepared.pdf')))

    def test_all_local_does_not_authenticate(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.pdf', Path(directory) / 'out.md'
            with pymupdf.open() as doc:
                doc.new_page().insert_text((72, 72), 'This is a healthy local report with sufficient readable document text.')
                doc.save(source)
            with patch.object(ocr, 'get_drive_service', side_effect=AssertionError('No Google authentication allowed')), patch.object(ocr, 'ocr_single_media_gdrive', side_effect=AssertionError('No upload allowed')):
                self.assertTrue(ocr.convert_file_to_md_gdrive(str(source), str(output)))
            self.assertNotIn(quality.OCR_SOURCE_WARNING, output.read_text(encoding='utf-8'))

    def test_cached_ocr_warning_is_saved_and_survives_bundling(self):
        import bundle_notebooklm as bundle
        class CacheEngine:
            def lookup(self, path, number):
                return {'method': 'cache', 'text': 'Readable recovered document text with numbers 3700 and 45.67.',
                        'requests': 0}
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.pdf', Path(directory) / 'out.md'
            with pymupdf.open() as doc:
                doc.new_page()
                doc.save(source)
            with patch.object(ocr, 'get_drive_service', side_effect=AssertionError('No auth')):
                ocr.convert_file_to_md_gdrive(str(source), str(output), speed_engine=CacheEngine())
            text = output.read_text(encoding='utf-8')
            self.assertEqual(text.count(quality.OCR_SOURCE_WARNING), 1)
            _, body = bundle.split_header(text)
            merged = bundle.attachment_body({'body': body})
            self.assertEqual(merged.count(quality.OCR_SOURCE_WARNING), 1)
            self.assertIn('3700 and 45.67', merged)

    def test_standalone_image_warning_after_ocr_not_noise_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            for ext in ['jpg', 'png']:
                with self.subTest(ext=ext):
                    source, output = Path(directory) / f'letter.{ext}', Path(directory) / f'{ext}.md'
                    Image.new('RGB', (40, 40), 'white').save(source)
                    with patch.object(ocr, 'ocr_single_media_gdrive', return_value='This is recovered scanned text with numbers 3700. ' * 12):
                        self.assertTrue(ocr.convert_file_to_md_gdrive(str(source), str(output), service=object()))
                    self.assertEqual(output.read_text(encoding='utf-8').count(quality.OCR_SOURCE_WARNING), 1)
                    empty_output = Path(directory) / f'empty_{ext}.md'
                    with patch.object(ocr, 'ocr_single_media_gdrive', return_value='tiny'):
                        self.assertFalse(ocr.convert_file_to_md_gdrive(str(source), str(empty_output), service=object()))
                    self.assertFalse(empty_output.exists())

    def test_persian_reversed_and_image_routed_to_ocr(self):
        class FakePage:
            rect = pymupdf.Rect(0, 0, 595, 842)
            def get_text(self, kind='text', **kwargs):
                words = 'است این شرکت گزارش بررسی درخواست شماره نمونه نتیجه تاریخ'
                text = ' '.join(word[::-1] for word in words.split())
                return {'blocks': []} if kind == 'dict' else text
            def get_image_info(self):
                return []
        _, result = pipeline.assess_local(FakePage())
        self.assertTrue(result['needs_ocr'])
        self.assertIn('واژه‌های فارسی وارونه‌اند', result['route_reasons'])

    def test_normal_persian_is_accepted_without_reversing(self):
        class FakePage:
            rect = pymupdf.Rect(0, 0, 595, 842)
            def get_text(self, kind='text', **kwargs):
                return {'blocks': []} if kind == 'dict' else 'این گزارش برای بررسی نتایج آزمون پیچ و مهره بویلر نیروگاه تهیه شده است.'
            def get_image_info(self):
                return []
        text, result = pipeline.assess_local(FakePage())
        self.assertFalse(result['needs_ocr'])
        self.assertIn('بررسی نتایج', text)

    def test_bad_mapping_empty_repetitions_are_suspect(self):
        class FakePage:
            rect = pymupdf.Rect(0, 0, 595, 842)
            def get_text(self, kind='text', **kwargs):
                return {'blocks': []} if kind == 'dict' else self.text
            def get_image_info(self):
                return []
        page = FakePage()
        for text in ['', 'Some corrupted text (cid:124) and replacement \ufffd in a report.', '\n'.join(['X'] * 30)]:
            page.text = text
            self.assertTrue(pipeline.assess_local(page)[1]['needs_ocr'])

    def test_fragmented_persian_with_some_valid_words_is_not_accepted(self):
        class FakePage:
            rect = pymupdf.Rect(0, 0, 595, 842)
            def get_text(self, kind='text', **kwargs):
                return {'blocks': []} if kind == 'dict' else ('شماارش گز ره ن موآز ارشگز شماستا خو ناهکنند ستا ' * 10 + ' شرکت گزارش ')
            def get_image_info(self):
                return []
        self.assertTrue(pipeline.assess_local(FakePage())[1]['needs_ocr'])

    def test_failure_does_not_shift_later_page_and_debug_is_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.pdf', Path(directory) / 'out.md'
            with pymupdf.open() as doc:
                doc.new_page()
                doc.new_page().insert_text((72, 72), 'This is the healthy LAST_PAGE of the local report document.')
                doc.save(source)
            with patch.object(ocr, 'ocr_single_media_gdrive', side_effect=RuntimeError('simulated error')):
                ocr.convert_file_to_md_gdrive(str(source), str(output), service=object(),
                                             max_page_retries=0, debug_errors=True)
            text = output.read_text(encoding='utf-8')
            self.assertIn('## صفحه 2\n\nThis is the healthy LAST_PAGE', text)
            self.assertTrue((output.parent / '_ocr_diagnostics' / 'out' / 'quality.json').exists())

    def test_reuse_cache_never_uploads_when_cache_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.pdf', Path(directory) / 'out.md'
            with pymupdf.open() as doc:
                doc.new_page()
                doc.save(source)
            with patch.object(ocr, 'get_drive_service', side_effect=AssertionError('No auth in cache mode')), patch.object(ocr, 'ocr_single_media_gdrive', side_effect=AssertionError('No upload in cache mode')):
                ocr.convert_file_to_md_gdrive(str(source), str(output), reuse_raw=True)
            report = json.loads((output.parent / 'ocr_quality_report.json').read_text(encoding='utf-8'))['out.md']
            self.assertEqual(report['requests'], 0)
            self.assertEqual(report['failed_pages'], [1])


if __name__ == '__main__':
    unittest.main()

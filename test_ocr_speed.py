# -*- coding: utf-8 -*-
import io
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image

import google_drive_ocr as google
import pdf_ocr_quality as quality
import pdf_page_pipeline as pipeline
from ocr_speed import (SpeedEngine, SpeedOptions, TextCache, boundary_labels,
                       digest_image, raster_bundle, split_response)


def scanned_route(page):
    result = quality.evaluate_text('')
    result.update(needs_ocr=True, route_reasons=['forced scan for test'])
    return '', result


def source_pdf(path, labels):
    with fitz.open() as doc:
        for label in labels:
            doc.new_page().insert_text((72, 72), f'This is a technical correspondence report for {label}.')
        doc.set_metadata({'title': path.name})
        doc.save(path)


def batch_response(name, contents=None):
    match = re.search(r'ocr_bundle_([A-F0-9]+)_(\d+)pages', name)
    token, count = match[1], int(match[2])
    contents = contents or [f'This is sufficient recovered correspondence text for POSITION_{n}.' for n in range(1, count + 1)]
    return '\n\n'.join('\n'.join((boundary_labels(token, n)[0], text, boundary_labels(token, n)[1]))
                         for n, text in enumerate(contents, 1))


class SpeedTest(unittest.TestCase):
    def test_trailing_space_in_pdf_stem_uses_safe_diagnostics_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'report .pdf', root / 'report .md'
            source_pdf(source, ['VALID_ORIGINAL_PAGE'])
            original = source.read_bytes()
            def response(*args, **kwargs):
                return 'This is sufficient recovered correspondence text for the original page.'
            with patch.object(pipeline, 'assess_local', side_effect=scanned_route), patch.object(google, 'ocr_single_media_gdrive', side_effect=response):
                self.assertTrue(google.convert_file_to_md_gdrive(source, output, service=object(), log_func=lambda _: None))
            self.assertTrue(output.is_file())
            self.assertEqual(original, source.read_bytes())
            self.assertFalse((root / '_ocr_diagnostics').exists())
            self.assertNotEqual(quality.diagnostics_path(root / 'report.md'), quality.diagnostics_path(output))

    def test_exact_pixels_not_names_and_single_digit_change_is_different(self):
        image = Image.new('RGB', (120, 160), 'white')
        same = image.copy()
        self.assertEqual(digest_image(image), digest_image(same))
        same.putpixel((40, 40), (0, 0, 0))
        self.assertNotEqual(digest_image(image), digest_image(same))

    def test_strict_markers_missing_duplicated_reordered_extra_text_fail(self):
        token = 'ABCDEFABCDEF'
        raw = batch_response(f'ocr_bundle_{token}_2pages.pdf')
        self.assertEqual(len(split_response(raw, token, 2)), 2)
        for bad in (raw.replace(boundary_labels(token, 1)[1], ''),
                    raw + boundary_labels(token, 2)[1],
                    raw.replace(boundary_labels(token, 1)[0], boundary_labels(token, 2)[0]),
                    raw + '\nUnattributed extra text',
                    raw.replace('RAGSTART', 'RAGSTXRT', 1)):
            with self.assertRaises(ValueError):
                split_response(bad, token, 2)
        spaced = raw.replace('RAGSTART', 'R A G S T A R T')
        self.assertEqual(len(split_response(spaced, token, 2)), 2)

    def test_raster_bundle_has_no_text_layer_and_no_content_resize(self):
        images = [Image.new('RGB', (1200, 1800), 'white') for _ in range(2)]
        data = raster_bundle(images, 'ABCDEFABCDEF')
        with fitz.open(stream=data, filetype='pdf') as doc:
            self.assertEqual(len(doc), 2)
            self.assertFalse(any(page.get_text() for page in doc))
            self.assertAlmostEqual(doc[0].rect.width, 1200 * 72 / 300)
            self.assertAlmostEqual(doc[0].rect.height, 2100 * 72 / 300)

    def test_cross_pdf_batch_mapping_dedup_cache_and_originals_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / 'renamed_A.pdf', root / 'renamed_B.pdf'
            source_pdf(first, ['SHARED_PAGE', 'SECOND_PAGE'])
            source_pdf(second, ['SHARED_PAGE', 'LAST_PAGE'])
            originals = {p: p.read_bytes() for p in (first, second)}
            calls = []
            def response(media, name, mime, service, **kwargs):
                calls.append(name)
                self.assertEqual(mime, 'application/pdf')
                self.assertFalse(media.resumable())
                self.assertTrue(kwargs['export_only'])
                return batch_response(name)
            engine = SpeedEngine(SpeedOptions(batch_pages=5, fast_transport=True), lambda: object(), response,
                                 cache_dir=root / 'cache', log_func=lambda _: None)
            try:
                with patch.object(pipeline, 'assess_local', side_effect=scanned_route):
                    engine.collect([first, second])
                    self.assertEqual(len(engine.jobs), 3)
                    self.assertEqual(engine.stats['duplicate_pages'], 1)
                    engine.run()
                    for source in (first, second):
                        google.convert_file_to_md_gdrive(source, root / 'out' / (source.stem + '.md'),
                                                         speed_engine=engine, log_func=lambda _: None)
                self.assertEqual(len(calls), 1)
                text_a = (root / 'out' / 'renamed_A.md').read_text(encoding='utf-8')
                text_b = (root / 'out' / 'renamed_B.md').read_text(encoding='utf-8')
                self.assertIn('POSITION_1', text_a)
                self.assertIn('POSITION_2', text_a)
                self.assertIn('POSITION_1', text_b)
                self.assertIn('POSITION_3', text_b)
                self.assertNotIn('POSITION_2', text_b)
                self.assertNotIn('RAGSTART', text_a + text_b)
                self.assertFalse((root / 'out' / '_ocr_diagnostics').exists())
                self.assertFalse(list(root.rglob('*.prepared.pdf')))
            finally:
                engine.close()
            self.assertTrue(all(p.read_bytes() == data for p, data in originals.items()))
            # اجرای بعدی با cache بدون احراز هویت یا حتی رندر تصویر.
            engine = SpeedEngine(SpeedOptions(), lambda: self.fail('cache must not authenticate'),
                                 lambda *a, **k: self.fail('cache must not upload'),
                                 cache_dir=root / 'cache', log_func=lambda _: None)
            try:
                with patch.object(pipeline, 'assess_local', side_effect=scanned_route), patch.object(quality, 'render_page', side_effect=AssertionError('whole-file cache avoids render')):
                    engine.collect([first, second])
                    engine.run()
                self.assertEqual(engine.stats['cache_hits'], 4)
                self.assertEqual(engine.stats['requests'], 0)
            finally:
                engine.close()

    def test_corrupt_boundaries_fall_back_without_mixing_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = [root / 'A.pdf', root / 'B.pdf']
            for n, source in enumerate(sources):
                source_pdf(source, [f'UNIQUE_{n}'])
            def response(media, name, mime, service, **kwargs):
                if mime == 'application/pdf':
                    return 'Markers disappeared; this cannot be assigned to either email.'
                return f'This is recovered original independent correspondence for {name}.'
            engine = SpeedEngine(SpeedOptions(batch_pages=5, cache=False), lambda: object(), response, log_func=lambda _: None)
            try:
                with patch.object(pipeline, 'assess_local', side_effect=scanned_route):
                    engine.collect(sources)
                    engine.run()
                self.assertEqual(engine.stats['requests'], 3)
                self.assertEqual(engine.stats['fallback_pages'], 2)
                for source in sources:
                    result = engine.lookup(source, 1)
                    self.assertIn(source.name, result['text'])
                    self.assertTrue(result['fallback'])
            finally:
                engine.close()

    def test_two_requests_overlap_with_independent_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.pdf'
            source_pdf(source, ['FIRST_UNIQUE', 'SECOND_UNIQUE'])
            barrier = threading.Barrier(2)
            services = []
            def response(media, name, mime, service, **kwargs):
                services.append(service)
                barrier.wait(timeout=10)
                return f'This is the recovered independent original correspondence for {name}.'
            engine = SpeedEngine(SpeedOptions(workers=2, cache=False), lambda: object(), response, log_func=lambda _: None)
            try:
                with patch.object(pipeline, 'assess_local', side_effect=scanned_route):
                    engine.collect([source])
                    engine.run()
                self.assertEqual(engine.stats['requests'], 2)
                self.assertIsNot(services[0], services[1])
                self.assertFalse(engine.stats['degraded_to_serial'])
                self.assertIn('page_0001', engine.lookup(source, 1)['text'])
                self.assertIn('page_0002', engine.lookup(source, 2)['text'])
            finally:
                engine.close()

    def test_failure_bounded_retries_no_poisoned_cache_and_next_page_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.pdf'
            source_pdf(source, ['FIRST_UNIQUE', 'SECOND_UNIQUE'])
            def response(media, name, mime, service, **kwargs):
                if '0001' in name:
                    raise RuntimeError('429 rate limit simulation')
                return 'This is a valid recovered LAST_PAGE correspondence with sufficient text.'
            engine = SpeedEngine(SpeedOptions(), lambda: object(), response, cache_dir=root / 'cache',
                                 log_func=lambda _: None, max_page_retries=1)
            try:
                with patch.object(pipeline, 'assess_local', side_effect=scanned_route), patch('ocr_speed.time.sleep'):
                    engine.collect([source])
                    engine.run()
                    google.convert_file_to_md_gdrive(source, root / 'out' / 'source.md', speed_engine=engine, log_func=lambda _: None)
                self.assertEqual(engine.stats['requests'], 3)
                self.assertTrue(engine.stats['degraded_to_serial'])
                self.assertEqual(engine.cache.db.execute('SELECT COUNT(*) FROM pages').fetchone()[0], 1)
                text = (root / 'out' / 'source.md').read_text(encoding='utf-8')
                section = text.split('## صفحه 2', 1)[1]
                self.assertIn('This is a valid recovered LAST_PAGE', section)
                self.assertIn(quality.OCR_SOURCE_WARNING, section)
                report = json.loads((root / 'out' / 'ocr_quality_report.json').read_text(encoding='utf-8'))['source.md']
                self.assertEqual(report['failed_pages'], [1])
                self.assertEqual(report['requests'], 3)
            finally:
                engine.close()

    def test_group_size_and_real_byte_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.pdf'
            source_pdf(source, [f'UNIQUE_{n}' for n in range(7)])
            engine = SpeedEngine(SpeedOptions(batch_pages=5, cache=False, batch_bytes=100000), None, None, log_func=lambda _: None)
            try:
                with patch.object(pipeline, 'assess_local', side_effect=scanned_route):
                    engine.collect([source])
                groups = list(engine._prepared_groups())
                self.assertEqual(sum(len(group[0]) for group in groups), 7)
                self.assertTrue(all(len(group[0]) <= 5 for group in groups))
                self.assertTrue(all(len(group[0]) == 1 or len(group[2]) <= 100000 for group in groups))
            finally:
                engine.close()

    def test_five_page_cap_and_fifteen_page_source_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'long.pdf'
            source_pdf(source, [f'UNIQUE_{n}' for n in range(16)])
            engine = SpeedEngine(SpeedOptions(batch_pages=5, cache=False), None, None, log_func=lambda _: None)
            try:
                with patch.object(pipeline, 'assess_local', side_effect=scanned_route):
                    engine.collect([source])
                self.assertEqual(len(engine.jobs), 5)
                groups = list(engine._prepared_groups())
                self.assertEqual(len(groups), 1)
                self.assertEqual(len(groups[0][0]), 5)
            finally:
                engine.close()

    def test_transport_timings_and_export_only_skips_docs_api(self):
        from unittest.mock import MagicMock
        from googleapiclient.http import MediaIoBaseUpload
        service = MagicMock()
        service.files.return_value.create.return_value.execute.return_value = {'id': 'temporary_doc'}
        payload = b'This is accepted directly exported OCR correspondence text.'
        class Download:
            def __init__(self, stream, request):
                self.stream = stream
            def next_chunk(self):
                self.stream.write(payload)
                return None, True
        media = MediaIoBaseUpload(io.BytesIO(b'fake_image'), mimetype='image/jpeg', resumable=False)
        metrics = {}
        with patch.object(google, 'build', side_effect=AssertionError('Docs API must not run')), patch.object(google, 'MediaIoBaseDownload', Download):
            text = google.ocr_single_media_gdrive(media, 'page.jpg', 'image/jpeg', service,
                                                 export_only=True, metrics=metrics)
        self.assertEqual(text, payload.decode())
        self.assertIn('upload_convert_seconds', metrics)
        self.assertIn('export_seconds', metrics)
        self.assertIn('delete_seconds', metrics)
        self.assertNotIn('docs_structure_seconds', metrics)
        service.files.return_value.delete.assert_called_once_with(fileId='temporary_doc')

    def test_cache_rejects_failed_and_damaged_text(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = TextCache(directory)
            try:
                cache.put('failed', 'x')
                self.assertIsNone(cache.get('failed'))
                cache.put('good', 'This is sufficient accepted recovered correspondence for caching.')
                cache.db.execute("UPDATE pages SET text='Tampered sufficient text that must not be used' WHERE key='good'")
                cache.db.commit()
                self.assertIsNone(cache.get('good'))
            finally:
                cache.close()


if __name__ == '__main__':
    unittest.main()

# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bundle_notebooklm as b
from pdf_ocr_quality import OCR_SOURCE_WARNING


def email(number, attachment='A-1'):
    return {'id': f'E-{number}', 'source': f'emails/{number}.md', 'message_id': str(number),
            'subject': 'موضوع مستقل', 'date': f'1403/01/{number:02d}',
            'header': 'موضوع: موضوع مستقل\nپیوست‌ها:\n- attachments/a.pdf',
            'body': '# متن مکاتبه\n\nعدد ۳۷۰۰ و 3.14 حفظ شود.',
            'attachments': [attachment] if attachment else []}


def attachments():
    return {'A-1': {'id': 'A-1', 'raw_hash': 'abc', 'header': 'پوشش: ۵ از ۱۷ صفحه',
                    'body': '## صفحه ۱\n\n| مقدار | واحد |\n| --- | --- |\n| 3700 | Nm |',
                    'parents': ['E-1', 'E-2'],
                    'sources': [{'raw': 'attachments/a.pdf', 'markdown': 'text/a.md', 'name': 'a.pdf'}]}}


class BundleTest(unittest.TestCase):
    def test_same_stem_word_and_pdf_use_own_markdown(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(b, 'ROOT', Path(directory)):
            folder = Path(directory) / 'Extracted_Data' / 'sample'
            (folder / 'emails' / 'attachments').mkdir(parents=True)
            (folder / 'attachments_text').mkdir()
            (folder / 'attachments_ocr_google').mkdir()
            for ext in ['docx', 'pdf']:
                (folder / 'emails' / 'attachments' / ('سند.' + ext)).write_bytes(ext.encode())
            (folder / 'emails' / 'mail.md').write_text('---\nموضوع: نامه\nپیوست‌ها:\n- attachments/سند.docx\n- attachments/سند.pdf\n---\nمتن نامه', encoding='utf-8')
            (folder / 'attachments_text' / 'سند.md').write_text('---\nپیوست: سند.docx\n---\nمتن ورد', encoding='utf-8')
            (folder / 'attachments_ocr_google' / 'سند.md').write_text('---\nپیوست: سند.pdf\nفایل_اصلی: emails\\attachments\\سند.pdf\n---\nمتن پی دی اف', encoding='utf-8')
            manifest = {'سند.docx': ['mail.md'], 'سند.pdf': ['mail.md']}
            (folder / 'attachment_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            rows, data, _ = b.load_records(['sample'])
            self.assertEqual(len(data), 2)
            mapping = {a['sources'][0]['name']: a for a in data.values()}
            self.assertEqual(mapping['سند.docx']['body'].strip(), 'متن ورد')
            self.assertEqual(mapping['سند.pdf']['body'].strip(), 'متن پی دی اف')
            text = b.render(rows, data)
            self.assertEqual(text.count('متن ورد'), 1)
            self.assertEqual(text.count('متن پی دی اف'), 1)
            # نبود مشخصات اصل در حالت هم‌نام، مجوز انتساب حدسی نیست.
            (folder / 'attachments_text' / 'سند.md').write_text('متن بدون سربرگ', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'مشخص نیست'):
                b.load_records(['sample'])
            # دو خروجی که واقعاً یک PDF را معرفی کنند همچنان خطا هستند.
            (folder / 'attachments_text' / 'سند.md').write_text('---\nپیوست: سند.pdf\n---\nنسخه دوم', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'دو خروجی متنی'):
                b.load_records(['sample'])

    def test_shared_attachment_once_and_explicit_parents(self):
        text = b.render([email(1), email(2)], attachments(), layout='appendix')
        self.assertEqual(text.count('### شروع پیوست A-1'), 1)
        self.assertIn('E-1، E-2', text)
        self.assertEqual(text.count('## شروع ایمیل'), 2)
        self.assertIn('| 3700 | Nm |', text)
        self.assertIn('۵ از ۱۷ صفحه', text)

    def test_inline_attachment_inside_each_parent_and_no_text_removed(self):
        text = b.render([email(1), email(2)], attachments())
        self.assertEqual(text.count('### شروع پیوست A-1'), 2)
        self.assertEqual(text.count('| 3700 | Nm |'), 2)
        self.assertNotIn(OCR_SOURCE_WARNING, text)
        for number in [1, 2]:
            section = text.split(f'## شروع ایمیل E-{number}', 1)[1].split(f'## پایان ایمیل E-{number}', 1)[0]
            self.assertIn('### شروع پیوست A-1', section)
            self.assertIn(f'ایمیل والد این نسخهٔ پیوست: E-{number}', section)

    def test_source_warning_preserved_without_invention_or_duplication(self):
        a = attachments()['A-1']
        a['body'] = '## صفحه ۱\n' + OCR_SOURCE_WARNING + '\nمتن اول\n## صفحه ۲\nمتن دوم'
        self.assertEqual(b.attachment_body(a).count(OCR_SOURCE_WARNING), 1)
        self.assertIn('متن دوم', b.attachment_body(a))
        data = {'A-1': a}
        for layout in ['inline', 'appendix']:
            self.assertEqual(b.render([email(1)], data, layout).count(OCR_SOURCE_WARNING), 1)
        a['body'] = '## صفحه ۱\nمتن محلی بدون هشدار'
        self.assertNotIn(OCR_SOURCE_WARNING, b.attachment_body(a))

    def test_word_limit_splits_only_between_emails(self):
        rows, data = [email(1), email(2)], attachments()
        limit = max(b.measurements(b.render([e], data))['words'] for e in rows)
        groups = b.plan(rows, data, limit, 1_000_000)
        self.assertEqual([len(g) for g in groups], [1, 1])
        for group in groups:
            self.assertLessEqual(b.measurements(b.render(group, data))['words'], limit)
            self.assertIn('### شروع پیوست A-1', b.render(group, data))

    def test_byte_limit_and_oversize_rejection(self):
        data, rows = attachments(), [email(1), email(2)]
        limit = max(b.measurements(b.render([e], data))['bytes'] for e in rows)
        self.assertEqual(len(b.plan(rows, data, 1_000_000, limit)), 2)
        with self.assertRaises(ValueError):
            b.plan(rows, data, 1, 1_000_000)

    def test_code_fences_and_numbers_untouched(self):
        text = '# عنوان\n```python\n# code\n```\n## صفحه\n۱۲.۳ 45.67'
        output = b.nested(text)
        self.assertIn('### عنوان', output)
        self.assertIn('```python\n# code\n```', output)
        self.assertIn('۱۲.۳ 45.67', output)

    def test_image_without_text_is_not_silently_dropped(self):
        data = attachments()
        data['A-1']['body'] = ''
        text = b.render([email(1)], data)
        self.assertIn('بدون متن استخراج‌شده', text)
        self.assertIn('خالی‌بودن اصل سند یا تصویر', text)

    def test_build_preserves_sources_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(b, 'ROOT', Path(directory)):
            folder = Path(directory) / 'Extracted_Data' / 'sample'
            (folder / 'emails' / 'attachments').mkdir(parents=True)
            (folder / 'attachments_text').mkdir()
            raw = folder / 'emails' / 'attachments' / 'عکس.jpg'
            raw.write_bytes(b'fake image')
            source = folder / 'emails' / 'نامه.md'
            source.write_text('---\nشناسه: message-id\nموضوع: نامه\nتاریخ شمسی: 1403/01/01\nپیوست‌ها:\n- attachments/عکس.jpg\n---\n# متن\nسلام', encoding='utf-8')
            (folder / 'attachment_manifest.json').write_text(json.dumps({'عکس.jpg': ['نامه.md']}), encoding='utf-8')
            before = b.digest(source)
            target = Path(directory) / 'Extracted_Data' / 'bundle'
            report = b.build(['sample'], target)
            self.assertEqual(before, b.digest(source))
            self.assertTrue(report['sources_unchanged'])
            entry = report['bundles'][0]['emails'][0]
            lines = (target / 'notebooklm_001.md').read_text(encoding='utf-8').splitlines()
            self.assertIn('شروع ایمیل', lines[entry['start_line'] - 1])
            self.assertIn('پایان ایمیل', lines[entry['end_line'] - 1])
            with self.assertRaises(ValueError):
                b.build(['sample'], target)

    def test_same_raw_different_ocr_keeps_each_parent_version(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(b, 'ROOT', Path(directory)):
            for dataset, text in [('one', 'First approved OCR version 3700.'),
                                  ('two', 'Second approved OCR version 3800.')]:
                folder = Path(directory) / 'Extracted_Data' / dataset
                (folder / 'emails' / 'attachments').mkdir(parents=True)
                (folder / 'attachments_ocr_google').mkdir()
                (folder / 'emails' / 'attachments' / 'same.pdf').write_bytes(b'identical original')
                (folder / 'emails' / 'mail.md').write_text('---\nموضوع: test\n---\nMessage', encoding='utf-8')
                (folder / 'attachments_ocr_google' / 'same.md').write_text('---\nنوع: متن پیوست\n---\n' + text, encoding='utf-8')
                (folder / 'attachment_manifest.json').write_text(json.dumps({'same.pdf': ['mail.md']}), encoding='utf-8')
            rows, data, _ = b.load_records(['one', 'two'])
            self.assertEqual(len(data), 2)
            self.assertEqual(len({a['raw_id'] for a in data.values()}), 1)
            merged = b.render(rows, data)
            for row in rows:
                section = merged.split('## شروع ایمیل ' + row['id'], 1)[1].split('## پایان ایمیل ' + row['id'], 1)[0]
                expected = 'First approved' if '/one/' in row['source'] else 'Second approved'
                other = 'Second approved' if expected == 'First approved' else 'First approved'
                self.assertIn(expected, section)
                self.assertNotIn(other, section)


if __name__ == '__main__':
    unittest.main()

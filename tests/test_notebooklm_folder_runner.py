# -*- coding: utf-8 -*-
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import bundle_notebooklm as b
from notebooklm_folder_runner import run, validate_paths
from notebooklm_bundler_gui import BundlerWindow


class FolderBundleTest(unittest.TestCase):
    def make_source(self, root):
        source = root / 'inputs' / 'مشکلات متریال CO2'
        (source / 'emails' / 'attachments').mkdir(parents=True)
        (source / 'attachments_text').mkdir()
        (source / 'emails' / 'attachments' / 'سند.pdf').write_bytes(b'source')
        (source / 'attachments_text' / 'سند.md').write_text('متن پیوست مرتبط', encoding='utf-8')
        for number in (2, 1):
            (source / 'emails' / f'{number}.md').write_text(
                f'---\nموضوع: نامه {number}\nتاریخ شمسی: 1403/01/0{number}\nپیوست‌ها:\n- attachments/سند.pdf\n---\nبدنه نامه {number}', encoding='utf-8')
        (source / 'attachment_manifest.json').write_text(json.dumps({'سند.pdf': ['1.md', '2.md']}, ensure_ascii=False), encoding='utf-8')
        return source

    def test_external_persian_folder_naming_order_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_source(root)
            before = {p: b.digest(p) for p in source.rglob('*') if p.is_file()}
            with patch.object(b, 'ROOT', root / 'project'):
                report = run(source, root / 'bundles')
            target = root / 'bundles' / source.name
            text = (target / (source.name + '.md')).read_text(encoding='utf-8')
            self.assertLess(text.index('بدنه نامه 1'), text.index('بدنه نامه 2'))
            self.assertEqual(text.count('متن پیوست مرتبط'), 2)
            self.assertTrue(report['sources_unchanged'])
            self.assertEqual(before, {p: b.digest(p) for p in before})
            with self.assertRaises(ValueError):
                validate_paths(source, root / 'bundles')
            with self.assertRaises(ValueError):
                validate_paths(source, source)

    def test_multiple_parts_keep_parent_units_and_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_source(root)
            with patch.object(b, 'ROOT', root / 'project'):
                rows, attachments, _ = b.load_records([source])
                limit = max(b.measurements(b.render([r], attachments))['words'] for r in rows)
                target = root / 'bundles' / source.name
                report = b.build([source], target, max_words=limit,
                                 filename_prefix=source.name, allow_external_output=True)
            self.assertEqual([v['file'] for v in report['bundles']],
                             [source.name + '_001.md', source.name + '_002.md'])
            for entry in report['bundles']:
                text = (target / entry['file']).read_text(encoding='utf-8')
                self.assertEqual(text.count('## شروع ایمیل'), 1)
                self.assertIn('متن پیوست مرتبط', text)
                self.assertLessEqual(entry['words'], limit)

    def test_window_preview_and_log_copy(self):
        window = tk.Tk()
        window.withdraw()
        app = BundlerWindow(window)
        try:
            app.values['input'].set(str(Path.cwd() / 'Extracted_Data' / 'مشکلات متریال CO2'))
            self.assertIn('مشکلات متریال CO2', app.destination.get())
            app.append('گزارش فارسی')
            app.copy_all_log()
            self.assertEqual(window.clipboard_get(), 'گزارش فارسی\n')
        finally:
            app.close()


if __name__ == '__main__':
    unittest.main()

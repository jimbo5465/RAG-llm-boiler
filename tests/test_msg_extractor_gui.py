# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import tkinter as tk
from types import SimpleNamespace
import unittest
from msg_extractor_gui import ExtractorWindow


class LogCopyTest(unittest.TestCase):
    def setUp(self):
        self.window = tk.Tk()
        self.window.withdraw()
        self.app = ExtractorWindow(self.window)
        self.app.append('گزارش فارسی')
        self.app.append('OCR error 500')
        self.window.update()

    def tearDown(self):
        self.app.close()

    def test_copy_all_and_selection_in_readonly_log(self):
        self.app.copy_all_log()
        self.assertEqual(self.window.clipboard_get(), 'گزارش فارسی\nOCR error 500\n')
        self.app.log.tag_add('sel', '1.0', '1.end')
        self.app.copy_selection()
        self.assertEqual(self.window.clipboard_get(), 'گزارش فارسی')
        self.assertEqual(str(self.app.log['state']), 'disabled')

    def test_shortcuts_with_persian_keyboard(self):
        self.assertEqual(self.app.log_shortcut(SimpleNamespace(keycode=65, keysym='Arabic_sheen')), 'break')
        self.assertEqual(self.app.log_shortcut(SimpleNamespace(keycode=67, keysym='Arabic_zah')), 'break')
        self.assertEqual(self.window.clipboard_get(), self.app.log.get('1.0', 'end-1c'))


if __name__ == '__main__':
    unittest.main()

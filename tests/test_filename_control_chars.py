# -*- coding: utf-8 -*-
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from step3_discovery import sanitize_filename


class FilenameTest(unittest.TestCase):
    def test_windows_control_characters_are_removed_from_filename(self):
        result = sanitize_filename('نامه HP To\tSubject\nSent\rSize\x00Cat.docx')
        self.assertEqual(result, 'نامه HP To_Subject_Sent_Size_Cat.docx')
        self.assertFalse(any(ord(c) < 32 for c in result))

    def test_valid_persian_filename_is_preserved(self):
        self.assertEqual(sanitize_filename('فرمت نامه.docx'), 'فرمت نامه.docx')


if __name__ == '__main__':
    unittest.main()

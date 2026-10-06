# -*- coding: utf-8 -*-
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import step3_5_attachments as attachments


class ArchiveTest(unittest.TestCase):
    def test_zip_collision_parents_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / 'source.zip', 'w') as archive:
                archive.writestr('a/report.txt', 'first')
                archive.writestr('b/report.txt', 'second')
                archive.writestr('../outside.txt', 'safe')
            manifest = {'source.zip': ['one.md', 'two.md']}
            self.assertEqual(attachments.extract_and_flatten_archives(root, manifest), 0)
            results = list(root.glob('*report*.txt'))
            self.assertEqual(len(results), 2)
            self.assertEqual({p.read_text() for p in results}, {'first', 'second'})
            for path in results:
                self.assertEqual(manifest[path.name], ['one.md', 'two.md'])
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            self.assertEqual(attachments.extract_and_flatten_archives(root, manifest), 0)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
            self.assertFalse((root.parent / 'outside.txt').exists())

    def test_actual_rar_with_persian_word_to_markdown(self):
        executable = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'WinRAR/Rar.exe'
        if not executable.exists():
            self.skipTest('RAR fixture creation requires installed Rar.exe')
        import docx
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            source, raw, output = root / 'source', root / 'raw', root / 'text'
            source.mkdir()
            raw.mkdir()
            path = source / 'گزارش.docx'
            document = docx.Document()
            document.add_paragraph('متن فنی آزمون اختلاط آب و روغن')
            document.save(path)
            archive = raw / 'مدارک.RAR'
            subprocess.run([str(executable), 'a', '-idq', '-ep', str(archive), str(path)],
                check=True, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            original = archive.read_bytes()
            manifest = {archive.name: ['email.md']}
            stats = attachments.process_attachments(str(raw), str(root), str(output), manifest)
            self.assertEqual(stats['err'], 0)
            self.assertEqual(stats['md'], 1)
            text = next(output.glob('*.md')).read_text(encoding='utf-8')
            self.assertIn('متن فنی آزمون اختلاط آب و روغن', text)
            self.assertIn('email.md', text)
            self.assertEqual(archive.read_bytes(), original)
            self.assertEqual(len(list(raw.glob('*.tmp'))), 0)

    def test_corrupt_archive_is_reported(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            (root / 'broken.rar').write_bytes(b'not a rar')
            stats = attachments.process_attachments(str(root), str(root), str(root / 'text'), {})
            self.assertEqual(stats['err'], 1)


if __name__ == '__main__':
    unittest.main()

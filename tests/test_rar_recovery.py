# -*- coding: utf-8 -*-
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import recover_rar_attachments as recovery


class RecoveryTest(unittest.TestCase):
    def test_only_missing_rar_files_processed_and_previous_files_preserved(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            dataset = Path(directory)
            raw = dataset / 'emails/attachments'
            raw.mkdir(parents=True)
            (raw / 'source.rar').write_bytes(b'fake')
            (raw / 'old.pdf').write_bytes(b'old')
            email = dataset / 'emails/old.md'
            email.write_text('old email', encoding='utf-8')
            manifest = dataset / 'attachment_manifest.json'
            manifest.write_text(json.dumps({'source.rar': ['old.md']}), encoding='utf-8')
            old_text = dataset / 'attachments_ocr_google/old.md'
            old_text.parent.mkdir()
            old_text.write_text('old text', encoding='utf-8')
            def expand(raw, mapping, paths):
                self.assertEqual([p.name for p in paths], ['source.rar'])
                (raw / 'source_unrar_letter.jpg').write_bytes(b'image')
                mapping['source_unrar_letter.jpg'] = ['old.md']
                return 0
            engine = MagicMock()
            engine.jobs = []
            engine.stats = {}
            with patch.object(recovery.office, 'extract_and_flatten_archives', side_effect=expand), \
                 patch.object(recovery.google, 'get_drive_service', return_value=MagicMock()), \
                 patch.object(recovery.google, 'convert_file_to_md_gdrive', return_value=False) as convert, \
                 patch.object(recovery, 'SpeedEngine', return_value=engine):
                report = recovery.recover(dataset)
            self.assertTrue(report['previous_files_unchanged'])
            self.assertEqual(convert.call_count, 1)
            self.assertIn('source_unrar_letter.jpg', convert.call_args.args[0])
            self.assertFalse(convert.call_args.kwargs['filter_image_names'])
            self.assertEqual(old_text.read_text(), 'old text')
            self.assertEqual(email.read_text(), 'old email')
            self.assertEqual(json.loads(manifest.read_text())['source_unrar_letter.jpg'], ['old.md'])


if __name__ == '__main__':
    unittest.main()

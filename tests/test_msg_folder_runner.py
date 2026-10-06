# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import msg_folder_runner as runner
import offline_msg_pipeline as pipeline
from test_offline_msg_pipeline import FakeMessage


class FolderRunnerTest(unittest.TestCase):
    def test_exact_persian_folder_name_and_nested_input(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            source = root / 'ورودی' / 'بویلر واحد ۲'
            (source / 'nested').mkdir(parents=True)
            (source / 'nested' / 'one.msg').write_bytes(b'message')
            output = root / 'خروجی دلخواه'
            with patch('google_drive_ocr.get_drive_service', return_value=MagicMock()), \
                 patch.object(pipeline, 'process_msg_dataset', return_value=0) as process:
                self.assertEqual(runner.run(source, output), 0)
            target = output / source.name
            self.assertTrue((target / 'run.log').is_file())
            self.assertEqual(process.call_args.kwargs['output_dir'], target)
            self.assertFalse(process.call_args.kwargs['use_rag'])
            self.assertTrue(process.call_args.kwargs['use_ocr'])
            self.assertEqual((source / 'nested' / 'one.msg').read_bytes(), b'message')
            with self.assertRaises(ValueError):
                runner.run(source, output)

    def test_overlap_and_empty_input(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            source = Path(directory) / 'source'
            source.mkdir()
            for destination in [source, source / 'output', source.parent]:
                with self.assertRaises(ValueError):
                    runner.validate_paths(source, destination)
            with self.assertRaises(ValueError):
                runner.run(source, source.parent / 'out')
            self.assertFalse((source.parent / 'out').exists())

    def test_preflight_failure_creates_no_dataset(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            (source / 'one.msg').write_bytes(b'message')
            with patch('google_drive_ocr.get_drive_service', side_effect=RuntimeError('offline')):
                with self.assertRaises(RuntimeError):
                    runner.run(source, root / 'output')
            self.assertFalse((root / 'output').exists())

    def test_pipeline_writes_only_to_selected_destination(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            root = Path(directory)
            source = root / 'input'
            source.mkdir()
            (source / 'one.msg').write_bytes(b'message')
            target = root / 'external-output' / 'input'
            with patch.object(pipeline.extract_msg, 'openMsg', return_value=FakeMessage()), \
                 patch.object(pipeline.step3_5_attachments, 'process_attachments',
                              return_value={'md': 0, 'skip': 1, 'err': 0}):
                code = pipeline.process_msg_dataset(source, 'input', output_dir=target)
            self.assertEqual(code, 0)
            self.assertTrue((target / 'pipeline_summary.json').is_file())
            self.assertEqual(len(list((target / 'emails').glob('*.md'))), 1)


if __name__ == '__main__':
    unittest.main()

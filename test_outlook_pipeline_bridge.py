# -*- coding: utf-8 -*-
"""اختبار اتصال GUI بدون Outlook و بدون درخواست واقعی Google."""
import json
from pathlib import Path
import tempfile
import unittest
import queue
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import outlook_pipeline_bridge as bridge


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(bridge, 'PROJECT_ROOT', self.root).start()
        patch.object(bridge.bundle_notebooklm, 'ROOT', self.root).start()
        self.dataset = bridge.allocate_output('نمونه')
        (self.dataset / 'emails' / 'mail.md').write_text(
            '---\nموضوع: آزمایش\nتاریخ شمسی: 1405/01/01\nپیوست‌ها:\nندارد\n---\n\n# متن مکاتبه\nمتن ایمیل آزمایشی',
            encoding='utf-8')
        (self.dataset / 'attachment_manifest.json').write_text('{}', encoding='utf-8')

    def test_unique_output_and_real_bundle_without_google(self):
        other = bridge.allocate_output('نمونه')
        self.assertNotEqual(other, self.dataset)
        with patch.object(bridge.attachments, 'process_attachments', return_value={'md': 0, 'err': 0}), patch.object(bridge.google, 'batch_convert_all') as ocr:
            result = bridge.finish_dataset(self.dataset, {}, 1, 0, False, lambda _: None)
        ocr.assert_not_called()
        self.assertEqual(result['quality_control']['status'], 'ok')
        self.assertTrue((self.dataset / 'notebooklm' / 'notebooklm_001.md').exists())
        report = json.loads((self.dataset / 'notebooklm' / 'bundle_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(report['layout'], 'inline')
        self.assertEqual(report['max_words'], 200000)

    def test_google_options_and_failure_do_not_claim_success(self):
        with patch.object(bridge.attachments, 'process_attachments', return_value={'md': 0, 'err': 0}), patch.object(bridge.google, 'batch_convert_all', return_value={'errors': 1}) as ocr:
            with self.assertRaises(RuntimeError):
                bridge.finish_dataset(self.dataset, {}, 1, 0, True, lambda _: None)
        options = ocr.call_args.kwargs['speed_options']
        self.assertEqual((options.workers, options.batch_pages, options.cache), (2, 5, True))
        self.assertFalse((self.dataset / 'notebooklm').exists())
        self.assertTrue((self.dataset / 'pipeline_summary.json').exists())

    def test_preflight_closes_service_even_on_failure(self):
        service = MagicMock()
        service.files.return_value.list.return_value.execute.side_effect = RuntimeError('denied')
        with patch.object(bridge.google, 'get_drive_service', return_value=service):
            with self.assertRaises(RuntimeError):
                bridge.preflight_google(lambda _: None)
        service.close.assert_called_once()

    def test_log_stream_keeps_partial_lines(self):
        lines = []
        stream = bridge.LogStream(lines.append)
        stream.write('مرحله')
        stream.write(' اول\nپایان')
        stream.flush()
        self.assertEqual(lines, ['مرحله اول', 'پایان'])

    def test_gui_convert_keeps_outlook_input_in_both_modes(self):
        import app_gui
        class Items(list):
            Count = 2
            def Sort(self, *_):
                pass
        items = Items(SimpleNamespace(Class=43, EntryID=f'entry-{i}',
                      ConversationID='same-thread', Subject='نامه آزمایشی',
                      SenderName='فرستنده', To='گیرنده', CC='', Body='متن نامه',
                      Attachments=None) for i in range(2))
        namespace = MagicMock()
        namespace.GetFolderFromID.return_value = SimpleNamespace(Items=items)
        outlook = MagicMock()
        outlook.GetNamespace.return_value = namespace
        for rollup in (False, True):
            with self.subTest(rollup=rollup):
                gui = app_gui.OutlookExtractorGUI.__new__(app_gui.OutlookExtractorGUI)
                gui.ui_events = queue.Queue()
                gui.log = lambda _: None
                with patch.object(app_gui.pythoncom, 'CoInitialize'), patch.object(app_gui.pythoncom, 'CoUninitialize'), patch.object(app_gui.win32com.client, 'Dispatch', return_value=outlook), patch.object(app_gui.s3, 'safe_extract_shamsi_date', return_value='1405/01/01'), patch.object(app_gui.msg_h, 'process_msg_attachments', return_value=0), patch.object(bridge, 'finish_dataset', return_value={'quality_control': {'status': 'ok'}, 'notebooklm': 'output'}) as finish:
                    gui.run_pipeline('folder-id', 'store-id', 'پوشه', 'Outlook/پوشه', 2, False, rollup)
                namespace.GetFolderFromID.assert_called_with('folder-id', 'store-id')
                self.assertEqual(finish.call_args.args[2:5], (2, 0, False))
                target = Path(finish.call_args.args[0])
                self.assertEqual(len(list((target / 'emails').glob('*.md'))), 1 if rollup else 2)
                events = list(gui.ui_events.queue)
                self.assertIn('done', [event[0] for event in events])
                self.assertNotIn('error', [event[0] for event in events])

    def test_same_name_attachments_keep_different_contents(self):
        import app_gui
        directory = self.dataset / 'emails' / 'attachments'
        mapping = {}
        outputs = []
        for content in (b'first document', b'second document', b'first document'):
            attachment = SimpleNamespace(FileName='same.pdf', Size=len(content),
                SaveAsFile=lambda path, body=content: Path(path).write_bytes(body))
            item = SimpleNamespace(Attachments=SimpleNamespace(Count=1, Item=lambda _: attachment))
            with patch.object(app_gui.s3, 'safe_extract_shamsi_date', return_value='1405/01/01'):
                outputs.append(app_gui.save_item_attachments(item, 1, str(directory), {'.pdf'}, mapping))
        self.assertNotEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])
        self.assertEqual(len(list(directory.iterdir())), 2)
        self.assertEqual((directory / outputs[0][0]).read_bytes(), b'first document')


if __name__ == '__main__':
    unittest.main()

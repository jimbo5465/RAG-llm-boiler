# -*- coding: utf-8 -*-
"""آزمون جابه‌جایی آرشیو و پردازش تدریجی بدون دست‌زدن به خروجی‌های واقعی."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import contextlib
import io
import json
import shutil
import uuid
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape
import collect_knowledge_sources as collector


@contextlib.contextmanager
def test_directory(root):
    directory = root / ('knowledge_test_' + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        assert directory.resolve().parent == root.resolve()
        shutil.rmtree(directory)


class CollectorTests(unittest.TestCase):
    def test_relocated_archive_and_incremental_output(self):
        original_root = collector.ROOT
        with test_directory(original_root) as temporary:
            root = Path(temporary)
            archive = root / 'آرشیو جدید'
            inputs = root / 'گزارش‌های ورودی'
            output = root / 'مقصد متفاوت'
            inputs.mkdir()
            raw = archive / 'Extracted_Data/new_batch/emails/attachments/evidence.pdf'
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b'%PDF-original-evidence')
            aid = 'A-' + collector.digest(raw)[:20] + '-T-123456789abc'
            manifest = archive / 'bundle_manifest.json'
            manifest.write_text(json.dumps({'bundles': [{'emails': [], 'attachments': [{
                'id': aid, 'raw_id': aid.split('-T-')[0], 'raw_hash': collector.digest(raw),
                'sources': [{'raw': raw.relative_to(archive).as_posix()}]}]}]}), encoding='utf-8')
            def make_report(name, extra=''):
                xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                for value in ['عنوان: موضوع مشترک', aid, extra]:
                    xml += '<w:p><w:r><w:t>' + escape(value) + '</w:t></w:r></w:p>'
                xml += '</w:body></w:document>'
                with zipfile.ZipFile(inputs / name, 'w') as doc:
                    doc.writestr('word/document.xml', xml)
            args = ['--input', str(inputs), '--output', str(output), '--archive', str(archive), '--manifest', str(manifest)]
            def run():
                with contextlib.redirect_stdout(io.StringIO()):
                    collector.main(args)
                return json.loads((output / 'collection_manifest.json').read_text(encoding='utf-8'))
            try:
                make_report('first.docx')
                first = run()
                self.assertEqual(len(first['reports']), 1)
                folder = output / first['reports'][0]['folder']
                self.assertEqual((folder / 'evidence.pdf').read_bytes(), raw.read_bytes())
                timestamp = (folder / 'evidence.pdf').stat().st_mtime_ns
                second = run()
                self.assertEqual(second['reports'][0]['status'], 'unchanged')
                self.assertEqual(timestamp, (folder / 'evidence.pdf').stat().st_mtime_ns)
                make_report('second.docx', 'گزارش جدید')
                third = run()
                self.assertEqual(len(third['reports']), 2)
                self.assertEqual(len({r['folder'] for r in third['reports']}), 2)
                make_report('first.docx', 'اصلاح گزارش قبلی')
                fourth = run()
                self.assertEqual(len(fourth['reports']), 3)
                self.assertTrue((folder / 'first.docx').exists())
                raw.write_bytes(b'changed-source')
                fifth = run()
                newest = next(r for r in reversed(fifth['reports']) if r['report'] == 'first.docx')
                self.assertTrue(newest['unresolved'])
                self.assertEqual(newest['files'], [])
            finally:
                collector.ROOT = original_root


if __name__ == '__main__':
    unittest.main()

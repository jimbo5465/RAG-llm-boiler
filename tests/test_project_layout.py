# -*- coding: utf-8 -*-
"""بررسی حفظ مسیر داده‌ها و امکان اجرای ابزارها پس از سازماندهی پروژه."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import ast
import subprocess
import unittest
import project_paths
import collect_knowledge_sources
import knowledge_collector_gui
import step3_5_attachments
import step4_rag
import google_drive_ocr


class LayoutTests(unittest.TestCase):
    def test_data_and_settings_paths_still_point_to_project_root(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(Path(project_paths.PROJECT_ROOT), root)
        self.assertEqual(collect_knowledge_sources.ROOT, root)
        self.assertEqual(knowledge_collector_gui.BASE, root)
        self.assertEqual(Path(step3_5_attachments.BASE), root)
        self.assertEqual(Path(step4_rag.BASE_DIR), root)
        self.assertEqual(Path(google_drive_ocr.BASE_DIR), root)
        self.assertEqual(knowledge_collector_gui.SETTINGS.parent, root)

    def test_all_relocated_python_files_parse(self):
        root = Path(__file__).resolve().parents[1]
        for folder in ('src', 'tools', 'tests', 'packaging'):
            for path in (root / folder).iterdir():
                if path.suffix in ('.py', '.spec'):
                    with self.subTest(path=path.name):
                        ast.parse(path.read_text(encoding='utf-8-sig'))

    def test_cli_tools_load_without_using_network(self):
        root = Path(__file__).resolve().parents[1]
        for relative in ('src/offline_msg_pipeline.py', 'src/bundle_notebooklm.py',
                         'src/collect_knowledge_sources.py', 'src/step4_rag.py',
                         'tools/run_msg_test.py', 'tools/run_pdf_quality_samples.py'):
            with self.subTest(tool=relative):
                process = subprocess.run([sys.executable, str(root / relative), '--help'],
                                         cwd=root, capture_output=True, timeout=30)
                self.assertEqual(process.returncode, 0, process.stderr.decode('utf-8', errors='replace'))


if __name__ == '__main__':
    unittest.main()

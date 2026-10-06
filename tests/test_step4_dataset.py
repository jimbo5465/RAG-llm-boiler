# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tempfile
import unittest
from pathlib import Path

import step4_rag


class Step4DatasetTest(unittest.TestCase):
    def test_dataset_paths_and_ocr_precedence(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp_dir:
            dataset = Path(temp_dir)
            emails = dataset / "emails"
            local_text = dataset / "attachments_text"
            ocr_text = dataset / "attachments_ocr_google"
            emails.mkdir()
            local_text.mkdir()
            ocr_text.mkdir()

            (emails / "mail.md").write_text(
                """---
موضوع: تست
فرستنده: واحد فنی
تاریخ شمسی: 1403/01/01
---

# متن مکاتبه:

این متن ایمیل برای آزمون چانک‌بندی است.
""",
                encoding="utf-8",
            )
            attachment_header = """---
پیوست: report.pdf
نوع: OCR
ایمیل‌های مرتبط (والد):
  - mail.md
---

"""
            (local_text / "report.md").write_text(
                attachment_header + "نسخه محلی گزارش فنی",
                encoding="utf-8",
            )
            (ocr_text / "report.md").write_text(
                attachment_header + "نسخه OCR گزارش فنی که باید انتخاب شود",
                encoding="utf-8",
            )

            step4_rag.configure_dataset(dataset)
            chunks = step4_rag.load_all_documents()
            exported_chunks = step4_rag.export_chunks_jsonl(dataset / "rag_chunks.jsonl")

            combined = "\n".join(text for text, _ in chunks)
            self.assertIn("نسخه OCR گزارش فنی", combined)
            self.assertNotIn("نسخه محلی گزارش فنی", combined)
            attachment_meta = next(
                metadata for _, metadata in chunks if metadata["source_type"] == "attachment"
            )
            self.assertEqual(attachment_meta["parent_email"], "mail.md")
            self.assertEqual(Path(step4_rag.CHROMA_PERSIST_DIR), dataset / "chroma_db")
            self.assertEqual(len(exported_chunks), 2)
            self.assertEqual(len((dataset / "rag_chunks.jsonl").read_text(encoding="utf-8").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()

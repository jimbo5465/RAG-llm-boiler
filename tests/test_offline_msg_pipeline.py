# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import offline_msg_pipeline as pipeline


class FakeAttachment:
    longFilename = "گزارش.txt"
    shortFilename = None
    name = None
    hidden = False
    data = "متن پیوست".encode("utf-8")


class FakeMessage:
    subject = "گزارش تست"
    sender = "فرستنده"
    to = "گیرنده"
    cc = None
    date = datetime(2024, 3, 20, 12, 0)
    receivedTime = None
    body = "با سلام\nاین یک پیام فنی آزمایشی است.\nبا تشکر"
    htmlBody = None
    messageId = "offline-test-id"
    attachments = [FakeAttachment()]

    def close(self):
        pass


class OfflineMsgPipelineTest(unittest.TestCase):
    def test_pipeline_without_outlook(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            (input_dir / "sample.msg").write_bytes(b"fake-msg-for-mocked-parser")

            with (
                patch.object(pipeline, "EXTRACTED_DATA_DIR", str(output_dir)),
                patch.object(pipeline.extract_msg, "openMsg", return_value=FakeMessage()),
                patch.object(
                    pipeline.step3_5_attachments,
                    "process_attachments",
                    return_value={"md": 0, "skip": 1, "err": 0},
                ),
            ):
                exit_code = pipeline.process_msg_dataset(input_dir, "test_dataset")

            self.assertEqual(exit_code, 0)
            dataset_dir = output_dir / "test_dataset"
            markdown_files = list((dataset_dir / "emails").glob("*.md"))
            attachment_files = list((dataset_dir / "emails" / "attachments").glob("*.txt"))
            self.assertEqual(len(markdown_files), 1)
            self.assertEqual(len(attachment_files), 1)
            self.assertIn("این یک پیام فنی آزمایشی است", markdown_files[0].read_text(encoding="utf-8"))
            self.assertTrue((dataset_dir / "attachment_manifest.json").exists())
            self.assertTrue((dataset_dir / "pipeline_summary.json").exists())


if __name__ == "__main__":
    unittest.main()

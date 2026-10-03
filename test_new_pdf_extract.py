# -*- coding: utf-8 -*-
import os
import step3_5_attachments as s35
from project_paths import TEST_INPUT_DIR

pdf_path = os.path.join(TEST_INPUT_DIR, "نشت یابی هلیوم.pdf")
text, meta, kind = s35.pdf_to_md(pdf_path, "نشت یابی هلیوم.pdf")
print("Kind:", kind)
print("Meta:", meta)
print("=== EXTRACTED TEXT SAMPLE ===")
print(text[:1200])

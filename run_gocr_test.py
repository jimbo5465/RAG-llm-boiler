# -*- coding: utf-8 -*-
import os
import google_drive_ocr as g_ocr
from project_paths import TEST_INPUT_DIR, TEST_OUTPUT_DIR

pdf_path = os.path.join(TEST_INPUT_DIR, "36423469 (1).pdf")
out_dir = TEST_OUTPUT_DIR
os.makedirs(out_dir, exist_ok=True)
out_md = os.path.join(out_dir, "google_ocr_output.md")

print("Processing with Google Drive OCR...")
res = g_ocr.convert_pdf_to_md_gdrive(pdf_path, out_md)
print("Saved to:", res)

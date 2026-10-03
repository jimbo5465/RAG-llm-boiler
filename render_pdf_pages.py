# -*- coding: utf-8 -*-
import fitz
import os
from project_paths import TEST_INPUT_DIR, TEST_OUTPUT_DIR

pdf_path = os.path.join(TEST_INPUT_DIR, "36423469 (1).pdf")
doc = fitz.open(pdf_path)
out_dir = TEST_OUTPUT_DIR
os.makedirs(out_dir, exist_ok=True)

for i, page in enumerate(doc):
    pix = page.get_pixmap(dpi=150)
    img_path = os.path.join(out_dir, f"page_{i+1}.png")
    pix.save(img_path)
    print(f"Saved: {img_path}")

# -*- coding: utf-8 -*-
import os
import fitz
import unicodedata
from bidi.algorithm import get_display
from project_paths import TEST_INPUT_DIR

pdf_path = os.path.join(TEST_INPUT_DIR, "نشت یابی هلیوم.pdf")
doc = fitz.open(pdf_path)
print("Page count:", len(doc))

for p_idx, page in enumerate(doc):
    print(f"\n--- PAGE {p_idx+1} ---")
    blocks = page.get_text("blocks")
    # مرتب‌سازی بر اساس مختصات عمودی y0 و سپس y1
    blocks = sorted(blocks, key=lambda b: (b[1], -b[0]))
    for b in blocks:
        text = b[4].strip()
        if not text:
            continue
        # اگر بلاک حاوی فرم‌های معکوس عربی بود
        if any('\uFB50' <= c <= '\uFDFF' or '\uFE70' <= c <= '\uFEFF' for c in text):
            lines = text.splitlines()
            fixed_lines = [unicodedata.normalize('NFKC', get_display(l)) for l in lines]
            text = "\n".join(fixed_lines)
        print("BLOCK:", repr(text[:80]))

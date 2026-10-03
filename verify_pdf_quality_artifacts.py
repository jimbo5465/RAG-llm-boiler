# -*- coding: utf-8 -*-
"""بازبینی بصری تمام صفحات نسخه‌های آماده‌شده و بررسی فایل‌های خروجی."""
import json
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageOps

from run_pdf_quality_samples import NAMES, OUTPUT_DIR

for name in NAMES:
    stem = name[:-4]
    with pymupdf.open(OUTPUT_DIR / (stem + '.prepared.pdf')) as doc:
        canvas = Image.new('RGB', (1200, ((len(doc) + 2) // 3) * 620), '#dddddd')
        for index, page in enumerate(doc):
            pix = page.get_pixmap(dpi=100, colorspace=pymupdf.csRGB)
            image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            image = ImageOps.contain(image, (390, 580))
            x, y = (index % 3) * 400, (index // 3) * 620
            canvas.paste(image, (x, y + 25))
            ImageDraw.Draw(canvas).text((x + 10, y + 5), f'PAGE {index + 1}', fill='black')
        contact = OUTPUT_DIR / '_ocr_diagnostics' / stem / 'all_pages.png'
        canvas.save(contact)
        assert len(doc) == (4 if name == NAMES[0] else 11)
        assert not any(page.get_text().strip() for page in doc)
    output = OUTPUT_DIR / (stem + '.md')
    content = output.read_text(encoding='utf-8')
    assert 'آماده_RAG: true' in content
    assert 'RAGPAGE' not in content
    assert (output.parent / '_ocr_diagnostics' / stem / 'google_raw.txt').exists()
    print(name, 'verified', str(output), flush=True)

for filename in ['pdf_ocr_quality.py', 'google_drive_ocr.py', 'PDF_OCR_WORKFLOW_FA.md']:
    path = Path(__file__).resolve().parent / filename
    print('FILE', path, 'FIRST LINE', path.read_text(encoding='utf-8').splitlines()[0])

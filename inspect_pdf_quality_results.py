# -*- coding: utf-8 -*-
"""خواندن UTF-8 نتایج آزمون؛ بدون تغییر فایل‌های ورودی."""
import argparse
import json
import pymupdf
from run_pdf_quality_samples import NAMES, SOURCE_DIR, OUTPUT_DIR
from pdf_ocr_quality import text_only

parser = argparse.ArgumentParser()
parser.add_argument('--native', action='store_true')
args = parser.parse_args()
for name in NAMES:
    print('\nFILE', name)
    if args.native:
        with pymupdf.open(SOURCE_DIR / name) as document:
            for number, page in enumerate(document, 1):
                print('PAGE', number, repr(page.get_text()))
    else:
        path = OUTPUT_DIR / (name[:-4] + '.md')
        if path.exists():
            print(text_only(path.read_text(encoding='utf-8')))

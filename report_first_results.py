# -*- coding: utf-8 -*-
"""گزارش فقط‌خواندنی خروجی‌های اجرای first."""
import json
from pathlib import Path

root = Path(__file__).resolve().parent
dataset = root / 'Extracted_Data' / 'first'
for folder in ('emails', 'emails/attachments', 'attachments_text', 'attachments_ocr_google'):
    path = dataset / folder
    print(folder, 'files=', sum(p.is_file() for p in path.glob('*')) if path.exists() else 0)
for path in sorted((dataset / 'attachments_ocr_google').glob('*.preparation.json')):
    info = json.loads(path.read_text(encoding='utf-8'))
    print('PREPARED:', path.stem, info['method'], f"{info['processed']}/{info['total']} pages",
          f"{info['size_mb']:.2f} -> {info['upload_bytes']/1024/1024:.2f} MB")
for path in sorted((dataset / 'attachments_ocr_google' / '_ocr_diagnostics').glob('*/quality.json')):
    report = json.loads(path.read_text(encoding='utf-8'))
    print('QUALITY:', path.parent.name, report['status'], 'usable=', report['rag_usable_pages'],
          'pages=', [(p['number'], p['status']) for p in report['pages']])
summary = dataset / 'pipeline_summary.json'
if summary.exists():
    print('SUMMARY:', summary.read_text(encoding='utf-8'))
# تأیید محل و خواندن بخش‌های ویرایش‌شده با UTF-8، بدون نمایش credential.
for name, needle in [('pdf_ocr_quality.py', 'def prepare_pdf'),
                     ('google_drive_ocr.py', 'پاسخ گوگل دریافت شد'),
                     ('run_first_fresh.py', 'shutil.rmtree')]:
    path = root / name
    lines = path.read_text(encoding='utf-8').splitlines()
    print('VERIFIED_FILE:', path, 'HEADER:', lines[0])
    print('VERIFIED_CHANGE:', next(line for line in lines if needle in line))

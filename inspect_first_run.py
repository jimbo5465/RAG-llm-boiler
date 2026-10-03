# -*- coding: utf-8 -*-
"""بررسی فقط‌خواندنی ورودی و خروجی اجرای first."""
from pathlib import Path

root = Path(__file__).resolve().parent
source = root / 'test_inputs' / 'msg' / 'first'
target = root / 'Extracted_Data' / 'first'
messages = sorted(p for p in source.rglob('*') if p.is_file() and p.suffix.lower() == '.msg')
print('INPUT:', source)
print('MSG_COUNT:', len(messages))
print('OUTPUT:', target.resolve())
if target.exists():
    files = [p for p in target.rglob('*') if p.is_file()]
    print('OUTPUT_FILES:', len(files), 'BYTES:', sum(p.stat().st_size for p in files))
    print('OUTPUT_CHILDREN:', ', '.join(p.name for p in target.iterdir()))
for p in messages:
    print('MSG:', p.relative_to(source), p.stat().st_size)

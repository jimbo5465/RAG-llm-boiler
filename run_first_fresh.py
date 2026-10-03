# -*- coding: utf-8 -*-
"""اجرای تازهٔ مجموعهٔ first با پاک‌سازی محدود و گزارش زنده."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'test_inputs' / 'msg' / 'first'
TARGET = ROOT / 'Extracted_Data' / 'first'


def input_snapshot():
    return {str(p.relative_to(SOURCE)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in SOURCE.rglob('*.msg') if p.is_file()}


def validate_target():
    expected_parent = ROOT / 'Extracted_Data'
    if expected_parent.resolve() != expected_parent or TARGET.resolve() != TARGET:
        raise RuntimeError('مسیر خروجی از طریق لینک به محل دیگری هدایت می‌شود؛ پاک‌سازی متوقف شد.')
    if TARGET.parent != expected_parent or TARGET.name != 'first':
        raise RuntimeError('مسیر پاک‌سازی معتبر نیست.')
    if TARGET.exists():
        for p in [TARGET, *TARGET.rglob('*')]:
            if p.is_symlink() or getattr(p.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise RuntimeError(f'لینک یا junction در خروجی پیدا شد: {p}')
            if not p.resolve().is_relative_to(TARGET):
                raise RuntimeError(f'مسیر خارج از خروجی: {p}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    before = input_snapshot()
    validate_target()
    print(f'ورودی: {SOURCE} | تعداد MSG: {len(before)}', flush=True)
    print(f'هدف دقیق پاک‌سازی: {TARGET}', flush=True)
    if not args.execute:
        return 0
    if len(before) != 30:
        raise RuntimeError('برای این اجرا باید دقیقاً ۳۰ ایمیل آماده باشد؛ خروجی قبلی پاک نشد.')
    log_dir = ROOT / 'Extracted_Data' / '_run_logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f'first_{datetime.now():%Y%m%d_%H%M%S}.log'
    with log_path.open('w', encoding='utf-8', buffering=1) as log:
        def report(message):
            line = f'[{datetime.now():%H:%M:%S}] {message}'
            print(line, flush=True)
            log.write(line + '\n')

        report('پیش‌بررسی اتصال و دسترسی Google Drive؛ هنوز خروجی پاک نشده است.')
        import google_drive_ocr
        service = google_drive_ocr.get_drive_service()
        try:
            service.files().list(pageSize=1, fields='files(id)').execute()
        finally:
            service.close()
        report('اتصال گوگل و مجوز دسترسی تأیید شد.')
        if before != input_snapshot():
            raise RuntimeError('ورودی حین پیش‌بررسی تغییر کرده است؛ پاک‌سازی انجام نشد.')
        validate_target()
        if TARGET.exists():
            count = sum(p.is_file() for p in TARGET.rglob('*'))
            shutil.rmtree(TARGET)
            report(f'{count} فایل خروجی قبلی فقط از {TARGET} حذف شد؛ قابل بازیابی توسط برنامه نیست.')
        report('استخراج ۳۰ ایمیل، تبدیل محلی پیوست‌های غیر PDF و سپس Google OCR آغاز شد. ساخت ایندکس embedding در این تست اجرا نمی‌شود.')
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        process = subprocess.Popen(
            [sys.executable, '-u', str(ROOT / 'offline_msg_pipeline.py'),
             '--input', str(SOURCE), '--dataset', 'first', '--ocr', '--force-ocr', '--no-rag'],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', bufsize=1)
        for line in process.stdout:
            report(line.rstrip('\n'))
        code = process.wait()
        unchanged = before == input_snapshot()
        report(f'پایان اجرا؛ کد خروج={code}؛ ایمیل‌های ورودی بدون تغییر={unchanged}')
        report(f'لاگ کامل: {log_path}')
        if not unchanged:
            raise RuntimeError('ورودی‌ها در طول اجرا تغییر کردند؛ بررسی لازم است.')
        return code


if __name__ == '__main__':
    raise SystemExit(main())

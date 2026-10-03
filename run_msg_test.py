# -*- coding: utf-8 -*-
"""اجرای تست مجموعهٔ جدید، بدون پاک‌سازی خروجی قبلی، با لاگ زندهٔ UTF-8."""
import argparse
from datetime import datetime
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def snapshot(source):
    return {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source.rglob('*.msg') if p.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('dataset')
    parser.add_argument('--expected-count', type=int, required=True)
    parser.add_argument('--ocr-workers', type=int, choices=(1, 2), default=2)
    parser.add_argument('--ocr-batch-pages', type=int, choices=range(1, 6), default=5)
    parser.add_argument('--legacy-transport', action='store_true',
                        help='حفظ دریافت ساختار و ارسال resumable برای مقایسه')
    parser.add_argument('--no-ocr-cache', action='store_true')
    args = parser.parse_args()
    if not args.dataset.isascii() or not args.dataset.replace('_', '').replace('-', '').isalnum():
        raise ValueError('نام مجموعه باید ساده و بدون جداکنندهٔ مسیر باشد.')
    source = ROOT / 'test_inputs' / 'msg' / args.dataset
    target = ROOT / 'Extracted_Data' / args.dataset
    if not source.is_dir() or target.exists():
        raise ValueError('ورودی موجود نیست یا خروجی از قبل وجود دارد؛ هیچ فایلی حذف نشد.')
    if not source.resolve().is_relative_to(ROOT) or not target.resolve().is_relative_to(ROOT):
        raise ValueError('مسیر خارج از پروژه است.')
    before = snapshot(source)
    if len(before) != args.expected_count:
        raise ValueError(f'تعداد ورودی {len(before)} است، نه {args.expected_count}.')
    log_dir = ROOT / 'Extracted_Data' / '_run_logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f'{args.dataset}_{datetime.now():%Y%m%d_%H%M%S}.log'
    with log_path.open('w', encoding='utf-8', buffering=1) as log:
        def report(message):
            line = f'[{datetime.now():%H:%M:%S}] {message}'
            print(line, flush=True)
            log.write(line + '\n')

        report(f'ورودی: {source}؛ تعداد ایمیل: {len(before)}؛ خروجی: {target}')
        report('بررسی اتصال و مجوز Google Drive...')
        import google_drive_ocr
        service = google_drive_ocr.get_drive_service()
        try:
            service.files().list(pageSize=1, fields='files(id)').execute()
        finally:
            service.close()
        report('اتصال گوگل تأیید شد. آغاز استخراج و پردازش ترکیبی؛ بدون embedding و بدون نگهداری واسط‌ها.')
        if snapshot(source) != before:
            raise RuntimeError('ورودی هنگام پیش‌بررسی تغییر کرد؛ اجرا شروع نشد.')
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        command = [sys.executable, '-u', str(ROOT / 'offline_msg_pipeline.py'),
                   '--input', str(source), '--dataset', args.dataset, '--ocr', '--no-rag',
                   '--ocr-workers', str(args.ocr_workers), '--ocr-batch-pages', str(args.ocr_batch_pages)]
        if not args.legacy_transport:
            command.append('--ocr-fast-transport')
        if args.no_ocr_cache:
            command.append('--no-ocr-cache')
        report(f'حالت آزمایشی: {args.ocr_workers} مسیر؛ حداکثر {args.ocr_batch_pages} صفحه/بسته؛ کیفیت ۳۰۰ DPI؛ حافظهٔ تکراری‌ها={not args.no_ocr_cache}')
        process = subprocess.Popen(
            command,
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', bufsize=1)
        for line in process.stdout:
            report(line.rstrip('\n'))
        code = process.wait()
        unchanged = snapshot(source) == before
        report(f'پایان اجرا؛ کد خروج={code}؛ ورودی بدون تغییر={unchanged}')
        report(f'لاگ: {log_path}')
        if not unchanged:
            raise RuntimeError('ورودی‌ها حین اجرا تغییر کرده‌اند؛ بررسی لازم است.')
        return code


if __name__ == '__main__':
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""بازیابی فقط Markdown جاافتادهٔ تست third از حافظه؛ هرگونه شبکه ممنوع."""
import argparse
import json
from datetime import datetime
from pathlib import Path

import google_drive_ocr as google
import offline_msg_pipeline as pipeline
from ocr_speed import SpeedEngine, SpeedOptions, digest_file
from project_paths import PROJECT_ROOT


def no_network(*args, **kwargs):
    raise RuntimeError('بازیابی فقط از حافظه مجاز است؛ هیچ درخواست تازه‌ای ارسال نمی‌شود.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh-report', action='store_true',
                        help='فقط تطبیق شمار درخواست‌های اجرای اصلی؛ Markdown موجود بازنویسی نمی‌شود')
    args = parser.parse_args()
    root = Path(PROJECT_ROOT).resolve()
    dataset = root / 'Extracted_Data' / 'third'
    attachments = dataset / 'emails' / 'attachments'
    source = attachments / '14030209_016_1_گزارش شکست فنی واحد کنترل کیفیت پروژه فردوسی .pdf'
    output_dir = dataset / 'attachments_ocr_google'
    output = output_dir / (source.stem + '.md')
    if not source.is_file() or (output.exists() and not args.refresh_report) or not source.resolve().is_relative_to(root):
        raise RuntimeError('مسیر بازیابی معتبر نیست یا خروجی موجود است؛ هیچ فایل موجودی بازنویسی نشد.')
    protected = [*attachments.iterdir(), *(dataset / 'emails').glob('*.md'), *output_dir.glob('*.md')]
    before = {p: digest_file(p) for p in protected if p.is_file()}
    manifest = json.loads((dataset / 'attachment_manifest.json').read_text(encoding='utf-8'))
    summary_path = dataset / 'pipeline_summary.json'
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    if args.refresh_report and (not output.is_file() or
            summary['google_ocr'].get('recovery', {}).get('file') != source.name):
        raise RuntimeError('بازبینی گزارش فقط برای خروجی بازیابی‌شدهٔ همین اجرا مجاز است.')
    engine = SpeedEngine(SpeedOptions(), no_network, no_network)
    try:
        engine.collect([source])
        if engine.jobs:
            raise RuntimeError('حافظهٔ کامل در دسترس نیست؛ برای جلوگیری از درخواست جدید توقف شد.')
        engine.run()
        if not args.refresh_report and not google.convert_file_to_md_gdrive(
                source, output, speed_engine=engine, parent_emails=manifest.get(source.name, [])):
            raise RuntimeError('خروجی بازیابی ذخیره نشد.')
        reports = json.loads((output_dir / 'ocr_quality_report.json').read_text(encoding='utf-8'))
        recovered = reports[output.name]
        if recovered['failed_pages']:
            raise RuntimeError('بازیابی صفحهٔ تأییدنشده دارد؛ گزارش خطا حفظ شد.')
        stats = summary['google_ocr']
        # بازیابی از cache نباید درخواست‌های انجام‌شدهٔ اجرای اصلی را از جمع حذف کند.
        keys = {key for pages in engine.file_maps.values() for key in pages.values()}
        original_calls = [call for call in stats['performance']['calls'] if call['owner'] in keys]
        recovered['requests'] = len(original_calls)
        recovered['upload_bytes'] = sum(call['bytes'] for call in original_calls)
        recovered['recovery_google_requests'] = 0
        recovered['request_accounting'] = 'original_run_including_cache_recovery'
        stats['converted'] = len(list(output_dir.glob('*.md')))
        stats['errors'] = sum(bool(row.get('errors')) for row in reports.values())
        stats['recovery'] = {'file': source.name, 'cache_pages': recovered['cache_pages'],
                             'new_google_requests': 0, 'reason': 'Windows trailing-space diagnostics path',
                             'completed_at_local': datetime.now().isoformat(timespec='seconds')}
        stats['recovery']['original_ocr_requests_attributed'] = len(original_calls)
        summary['quality_control'] = pipeline.build_quality_report(
            dataset, dataset / 'emails', attachments, dataset / 'attachments_text', output_dir,
            manifest, summary['messages_processed'], summary['messages_failed'],
            summary['attachment_conversion'], stats)
        unchanged = all(digest_file(p) == digest for p, digest in before.items())
        if not unchanged:
            raise RuntimeError('فایل حفاظت‌شده تغییر کرده است؛ بازیابی تأیید نشد.')
        stats['recovery']['protected_files_unchanged'] = True
        (output_dir / 'ocr_quality_report.json').write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        log = max((root / 'Extracted_Data' / '_run_logs').glob('third_*.log'), key=lambda p: p.stat().st_mtime)
        with log.open('a', encoding='utf-8') as stream:
            stream.write(f"[{datetime.now():%H:%M:%S}] بازیابی خروجی جاافتاده از حافظه؛ درخواست گوگل=0؛ کیفیت={summary['quality_control']['status']}؛ سایر فایل‌ها بدون تغییر=True\n")
        print('RECOVERED', output)
        print('QUALITY', summary['quality_control']['status'], 'NEW_GOOGLE_REQUESTS=0')
    finally:
        engine.close()


if __name__ == '__main__':
    main()

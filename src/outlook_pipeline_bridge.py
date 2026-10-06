# -*- coding: utf-8 -*-
"""اتصال استخراج Outlook به همان پردازش پیوست‌ها و بسته‌بندی فاز اول."""
import contextlib
import io
import json
from datetime import datetime
from pathlib import Path

from project_paths import PROJECT_ROOT
from ocr_speed import SpeedOptions
import google_drive_ocr as google
import step3_5_attachments as attachments
import bundle_notebooklm
from offline_msg_pipeline import build_quality_report


class LogStream(io.TextIOBase):
    def __init__(self, log):
        self.log = log
        self.pending = ''

    def write(self, text):
        self.pending += text
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            if line.strip():
                self.log(line)
        return len(text)

    def flush(self):
        if self.pending.strip():
            self.log(self.pending)
        self.pending = ''


def allocate_output(folder_name):
    """هیچ اجرای تازه‌ای خروجی اجرای قبلی را بازنویسی نمی‌کند."""
    import step3_discovery
    name = step3_discovery.sanitize_filename(folder_name)[:80] or 'outlook'
    root = Path(PROJECT_ROOT) / 'Extracted_Data'
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    target = root / f'{name}_{stamp}'
    target.mkdir(exist_ok=False)
    for sub in ('emails/attachments', 'attachments_text'):
        (target / sub).mkdir(parents=True)
    return target


def preflight_google(log):
    log('[+] بررسی ورود و دسترسی Google قبل از استخراج...')
    service = google.get_drive_service()
    try:
        service.files().list(pageSize=1, fields='files(id)').execute()
    finally:
        service.close()
    log('[+] دسترسی Google تأیید شد.')


def finish_dataset(dataset, manifest, processed, failed, use_ocr, log):
    dataset = Path(dataset)
    emails = dataset / 'emails'
    raw = emails / 'attachments'
    local = dataset / 'attachments_text'
    ocr = dataset / 'attachments_ocr_google'
    stream = LogStream(log)
    with contextlib.redirect_stdout(stream):
        log('[+] تبدیل محلی پیوست‌های Office...')
        office_stats = attachments.process_attachments(
            att_dir=str(raw), md_dir=str(emails), out_dir=str(local),
            attachment_manifest=manifest)
        (dataset / 'attachment_manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        ocr_stats = {}
        if use_ocr:
            log('[+] PDF: استخراج محلی صفحه‌به‌صفحه؛ Google فقط برای صفحات مشکوک و تصاویر.')
            ocr_stats = google.batch_convert_all(
                str(raw), str(ocr), force_overwrite=False, log_func=log,
                attachment_manifest=manifest, debug_errors=False,
                speed_options=SpeedOptions(workers=2, batch_pages=5,
                                           fast_transport=True, cache=True))
        quality = build_quality_report(dataset, emails, raw, local, ocr,
                                       manifest, processed, failed,
                                       office_stats, ocr_stats)
        summary = {'dataset_dir': str(dataset), 'source': 'Outlook',
                   'messages_processed': processed, 'messages_failed': failed,
                   'attachment_conversion': office_stats,
                   'google_ocr_enabled': use_ocr, 'google_ocr': ocr_stats,
                   'quality_control': quality, 'notebooklm': None}
        summary_path = dataset / 'pipeline_summary.json'
        def save_summary():
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                    encoding='utf-8')
        save_summary()
        if quality['status'] == 'error':
            raise RuntimeError(f'پردازش ناقص است؛ گزارش را بررسی کنید: {summary_path}')
        log('[+] ساخت مجموعه NotebookLM؛ هر پیوست زیر ایمیل والد، سقف ۲۰۰ هزار کلمه و ۵۰ MB...')
        try:
            bundle_notebooklm.build([dataset.name], dataset / 'notebooklm')
            summary['notebooklm'] = str(dataset / 'notebooklm')
        except Exception as error:
            summary['notebooklm_error'] = str(error)
            raise
        finally:
            save_summary()
            stream.flush()
    return summary

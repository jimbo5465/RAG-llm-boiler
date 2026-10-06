# -*- coding: utf-8 -*-
"""بازیابی محلی والدهای ناموجود ناشی از کاراکتر کنترل در نام؛ بدون OCR."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import extract_msg
import offline_msg_pipeline as pipeline
import step3_discovery as discovery
import bundle_notebooklm as bundle


def legacy_name(subject):
    value = re.sub(r'[\\/*?:"<>|]', '_', subject)
    name, ext = os.path.splitext(value.strip())
    if len(name) > 60:
        name = name[:60].rstrip()
    return name + ext


def repair(folder):
    folder = Path(folder).resolve()
    manifest_path = folder / 'attachment_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    names = {p.name for p in (folder / 'emails').glob('*.md')}
    missing = sorted({parent for parents in manifest.values() for parent in parents if parent not in names})
    if not missing:
        print('والد ناموجودی نیست.')
        return
    if any(not re.search(r'[\x00-\x1f]', name) for name in missing):
        raise ValueError('این ابزار فقط خطای نام دارای کاراکتر کنترل را بازیابی می‌کند.')
    summary = json.loads((folder / 'pipeline_summary.json').read_text(encoding='utf-8'))
    input_dir = Path(summary['input_dir'])
    if not input_dir.is_dir():
        raise ValueError('پوشه MSG اصلی در دسترس نیست.')
    before = {p: pipeline.sha256_file(p) for p in folder.rglob('*') if p.is_file()}
    raw_hashes = pipeline.load_existing_attachment_hashes(folder / 'emails' / 'attachments')
    found = {name: [] for name in missing}
    source_hashes = {}
    for source in input_dir.rglob('*.msg'):
        source_hashes[source] = pipeline.sha256_file(source)
        message = extract_msg.openMsg(str(source))
        try:
            subject = getattr(message, 'subject', None) or '(بدون موضوع)'
            subject = discovery.COMPILED_SUBJECT_WARNING_REGEX.sub('', subject).strip() or '(بدون موضوع)'
            dt = pipeline.get_message_datetime(message, source)
            date = discovery.gregorian_to_jalali(dt.year, dt.month, dt.day)
            for old in missing:
                prefix = re.match(r'^(\d{8})_(\d+)_', old)
                if not prefix or prefix[1] != date.replace('/', '') or old != prefix[0] + legacy_name(subject) + '.md':
                    continue
                attachments = []
                for index, attachment in enumerate(message.attachments, 1):
                    data = pipeline.attachment_bytes(attachment)
                    if not data:
                        continue
                    name = pipeline.attachment_name(attachment, index)
                    if pipeline.should_skip_attachment(attachment, name, data):
                        continue
                    stored = raw_hashes.get(pipeline.sha256_bytes(data))
                    if not stored:
                        raise ValueError(f'پیوست اصلی هنوز ذخیره نشده است: {source.name} / {name}')
                    attachments.append(stored)
                expected = {raw for raw, parents in manifest.items() if old in parents}
                if set(attachments) != expected:
                    raise ValueError(f'پیوست‌های منبع با مانیفست یکسان نیستند: {source.name}')
                target_name = prefix[0] + discovery.sanitize_filename(subject) + '.md'
                if target_name in names:
                    raise ValueError('نام بازیابی با ایمیل موجود تداخل دارد.')
                text = pipeline.format_message_markdown(
                    str(getattr(message, 'messageId', None) or source_hashes[source]), subject,
                    (getattr(message, 'sender', None) or 'نامشخص').strip(),
                    (getattr(message, 'to', None) or 'ندارد').strip(),
                    (getattr(message, 'cc', None) or 'ندارد').strip(), date, source.name,
                    attachments, discovery.parse_and_clean_thread(pipeline.get_plain_body(message)) or discovery.PLACEHOLDER_EMPTY_BODY)
                found[old].append((target_name, text, source))
        finally:
            message.close()
    if any(len(items) != 1 for items in found.values()):
        raise ValueError('برای هر والد باید دقیقاً یک MSG با موضوع، تاریخ و پیوست‌های مطابق موجود باشد.')
    mapping = {old: items[0][0] for old, items in found.items()}
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('نام‌های مقصد تداخل دارند.')
    if any(pipeline.sha256_file(p) != h for p, h in before.items()) or any(pipeline.sha256_file(p) != h for p, h in source_hashes.items()):
        raise RuntimeError('منابع حین بررسی تغییر کردند.')
    # ابتدا همه مقصدها و اصلاحات بررسی می‌شوند، سپس پشتیبان و نوشتن انجام می‌شود.
    updated_manifest = {raw: list(dict.fromkeys(mapping.get(p, p) for p in parents)) for raw, parents in manifest.items()}
    updates = {}
    for sub in ['attachments_text', 'attachments_ocr_google']:
        for path in (folder / sub).glob('*.md'):
            text = path.read_text(encoding='utf-8')
            header, body = bundle.split_header(text)
            if not header:
                continue
            new_header = header
            for old, new in mapping.items():
                new_header = new_header.replace('  - ' + old, '  - ' + new)
            if new_header != header:
                # جایگزینی فقط در سربرگ؛ متن سند دقیقاً حفظ می‌شود.
                start = text.index(header)
                updates[path] = text[:start] + new_header + text[start + len(header):]
    backup = folder / '_email_parent_repair_backups' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup.mkdir(parents=True)
    for path in [manifest_path, *updates]:
        target = backup / path.relative_to(folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    for items in found.values():
        name, text, _ = items[0]
        with (folder / 'emails' / name).open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
    for path, text in updates.items():
        path.write_text(text, encoding='utf-8', newline='')
    manifest_path.write_text(json.dumps(updated_manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    rows, attachments, _ = bundle.load_records([folder])
    groups = bundle.plan(rows, attachments, 200_000, 50_000_000)
    unaffected = [p for p in before if p != manifest_path and p not in updates]
    unchanged = all(pipeline.sha256_file(p) == before[p] for p in unaffected)
    if not unchanged:
        raise RuntimeError('فایل غیرمرتبط تغییر کرده است.')
    report = {'recovered_emails': mapping, 'sources': {old: str(items[0][2]) for old, items in found.items()},
              'email_count': len(rows), 'attachment_variants': len(attachments), 'planned_bundles': len(groups),
              'unchanged_other_files': unchanged, 'ocr_performed': False, 'backup': str(backup),
              'note': 'گزارش‌های اجرای اولیه حفظ شدند؛ نتیجه بازیابی در این گزارش ثبت شده است.'}
    (folder / 'email_parent_repair_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-dir', required=True)
    args = parser.parse_args()
    repair(args.dataset_dir)

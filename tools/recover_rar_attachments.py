# -*- coding: utf-8 -*-
"""تکمیل فقط پیوست‌های RAR مجموعه موجود، بدون تکرار استخراج ایمیل‌های اصلی."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import argparse
import contextlib
from datetime import datetime
import hashlib
import json
import re
import shutil

import step3_5_attachments as office
import offline_msg_pipeline as pipeline
import google_drive_ocr as google
from msg_folder_runner import Tee
from ocr_speed import SpeedEngine, SpeedOptions
from project_paths import PROJECT_ROOT


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def extract_messages(paths, dataset, manifest, selected):
    emails, raw = dataset / 'emails', dataset / 'emails/attachments'
    existing_ids = {}
    for path in emails.glob('*.md'):
        match = re.search(r'^شناسه: (.+)$', path.read_text(encoding='utf-8-sig'), re.M)
        if match:
            existing_ids[match[1].strip()] = path.name
    known = {digest(path): path.name for path in raw.iterdir() if path.is_file()}
    queue, seen, errors = list(paths), set(), []
    added = []
    while queue:
        path = queue.pop(0)
        sha = digest(path)
        if sha in seen:
            continue
        seen.add(sha)
        try:
            message = pipeline.extract_msg.openMsg(str(path))
            try:
                identity = str(getattr(message, 'messageId', None) or sha)
                dt = pipeline.get_message_datetime(message, path)
                date = pipeline.step3_discovery.gregorian_to_jalali(dt.year, dt.month, dt.day)
                subject = getattr(message, 'subject', None) or '(بدون موضوع)'
                name = existing_ids.get(identity)
                fresh = name is None
                if fresh:
                    name = f'{date.replace("/", "")}_RAR_{sha[:12]}_{pipeline.step3_discovery.sanitize_filename(subject)[:80]}.md'
                    if (emails / name).exists():
                        raise RuntimeError(f'نام خروجی ایمیل موجود است: {name}')
                stored = []
                for index, attachment in enumerate(message.attachments, 1):
                    data = pipeline.attachment_bytes(attachment)
                    if not data:
                        continue
                    original = pipeline.attachment_name(attachment, index)
                    data_sha = hashlib.sha256(data).hexdigest()
                    filename = known.get(data_sha)
                    if filename is None:
                        destination = pipeline.unique_path(raw, office.fit_archive_filename(raw, f'RAR_{sha[:12]}_{index}_{original}'))
                        destination.write_bytes(data)
                        filename = destination.name
                        known[data_sha] = filename
                    child = raw / filename
                    selected.add(child)
                    parents = manifest.setdefault(filename, [])
                    if name not in parents:
                        parents.append(name)
                    stored.append(filename)
                    if child.suffix.lower() == '.msg':
                        queue.append(child)
                if fresh:
                    text = pipeline.format_message_markdown(identity, subject,
                        getattr(message, 'sender', None) or 'نامشخص',
                        getattr(message, 'to', None) or 'ندارد', getattr(message, 'cc', None) or 'ندارد',
                        date, path.name, stored,
                        pipeline.step3_discovery.parse_and_clean_thread(pipeline.get_plain_body(message)))
                    (emails / name).write_text(text, encoding='utf-8')
                    added.append(name)
                    existing_ids[identity] = name
                    print(f'[+] ایمیل داخل RAR استخراج شد: {name}', flush=True)
            finally:
                message.close()
        except Exception as error:
            errors.append({'file': path.name, 'error': str(error)})
            print(f'[-] خطا در ایمیل داخل RAR: {path.name}: {error}', flush=True)
    return added, errors


def recover(dataset, prepare_only=False):
    dataset = Path(dataset).resolve()
    raw = dataset / 'emails/attachments'
    manifest_path = dataset / 'attachment_manifest.json'
    if not raw.is_dir() or not manifest_path.is_file():
        raise ValueError(f'مجموعه خروجی معتبر نیست: {dataset}')
    archives = [p for p in raw.iterdir() if p.is_file() and p.suffix.lower() == '.rar']
    if not archives:
        print('این مجموعه RAR ندارد.')
        return {}
    original = {str(p.relative_to(dataset)): digest(p) for p in dataset.rglob('*')
                if p.is_file() and (p.suffix.lower() == '.md' or p.parent == raw)}
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    backup = dataset / ('_rar_recovery_backups/' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True)
    shutil.copy2(manifest_path, backup / manifest_path.name)
    missing_parents = [p.name for p in archives if not manifest.get(p.name)]
    if missing_parents:
        raise ValueError(f'ایمیل والد آرشیوها در مانیفست نامشخص است: {missing_parents}')
    errors = office.extract_and_flatten_archives(raw, manifest, archives)
    selected = {p for p in raw.iterdir() if p.is_file()
                and any(p.name.startswith(a.stem + '_unrar_') for a in archives)}
    # ایمیل‌های موجود از اول استخراج نمی‌شوند؛ فقط MSGهای داخل RAR پردازش می‌شوند.
    messages, msg_errors = extract_messages([p for p in selected if p.suffix.lower() == '.msg'],
                                           dataset, manifest, selected)
    save_json(manifest_path, manifest)
    local_dir, ocr_dir = dataset / 'attachments_text', dataset / 'attachments_ocr_google'
    office_files = [p for p in selected if p.suffix.lower() in ('.docx', '.xlsx', '.xls', '.xlsm', '.pptx')
                   and not (local_dir / (p.stem + '.md')).exists()]
    office_stats = office.process_attachments(str(raw), str(dataset / 'emails'), str(local_dir),
                                              manifest, selected_files=office_files)
    targets = sorted(p for p in selected if p.suffix.lower() in google.ALL_SUPPORTED_OCR_EXTENSIONS
                     and not (ocr_dir / (p.stem + '.md')).exists())
    results = []
    engine = SpeedEngine(SpeedOptions(workers=2, batch_pages=1, fast_transport=True, cache=True),
                         None, google.ocr_single_media_gdrive, log_func=print)
    service = None
    try:
        engine.collect([p for p in targets if p.suffix.lower() == '.pdf'] if not prepare_only else [])
        if engine.jobs:
            engine.service_factory = google.worker_service_factory()
        engine.run()
        for index, path in enumerate(targets, 1):
            print(f'[{index}/{len(targets)}] تکمیل RAR: {path.name}', flush=True)
            if prepare_only:
                results.append({'file': path.name, 'status': 'pending_ocr'})
                continue
            output = ocr_dir / (path.stem + '.md')
            try:
                if path.suffix.lower() != '.pdf' and service is None:
                    service = google.get_drive_service()
                success = google.convert_file_to_md_gdrive(str(path), str(output), service=service,
                    parent_emails=manifest.get(path.name, []), speed_engine=engine if path.suffix.lower() == '.pdf' else None,
                    filter_image_names=False)
                results.append({'file': path.name, 'status': 'converted' if success else 'no_text'})
            except Exception as error:
                results.append({'file': path.name, 'status': 'error', 'error': str(error)})
                print(f'[-] {error}', flush=True)
    finally:
        engine.close()
        if service is not None:
            service.close()
        unchanged = all((dataset / p).exists() and digest(dataset / p) == sha for p, sha in original.items())
        quality_file = ocr_dir / 'ocr_quality_report.json'
        pdf_quality = json.loads(quality_file.read_text(encoding='utf-8')) if quality_file.exists() else {}
        selected_pdf_quality = {p.stem + '.md': pdf_quality[p.stem + '.md'] for p in selected
                                if p.stem + '.md' in pdf_quality}
        report = {'dataset': str(dataset), 'archives': [p.name for p in archives],
            'extracted_files': len(selected), 'archive_errors': errors, 'new_emails': messages,
            'msg_errors': msg_errors, 'office': office_stats, 'results': results,
            'pdf_quality': selected_pdf_quality, 'previous_files_unchanged': unchanged,
            'unsupported': [p.name for p in selected if p.suffix.lower() not in
                google.ALL_SUPPORTED_OCR_EXTENSIONS | {'.docx', '.xlsx', '.xls', '.xlsm', '.pptx', '.msg'}],
            'manifest_backup': str(backup), 'performance': engine.stats, 'prepare_only': prepare_only}
        save_json(dataset / 'rar_recovery_report.json', report)
        if not unchanged:
            raise RuntimeError('فایل قدیمی تغییر کرده است؛ گزارش تکمیل را بررسی کنید.')
    print(f'[+] پایان تکمیل: {dataset.name}؛ {len(selected)} فایل؛ فایل‌های قبلی بدون تغییر={unchanged}', flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-dir', type=Path)
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--prepare-only', action='store_true', help='بازکردن و تبدیل Office و MSG، بدون ارسال به گوگل')
    args = parser.parse_args()
    if not args.all and not args.dataset_dir:
        parser.error('--dataset-dir یا --all لازم است')
    if args.dataset_dir and not (args.dataset_dir / 'attachment_manifest.json').is_file():
        parser.error('پوشه انتخاب‌شده مانیفست مجموعه را ندارد.')
    datasets = [args.dataset_dir] if args.dataset_dir else sorted((Path(PROJECT_ROOT) / 'Extracted_Data').iterdir())
    exit_code = 0
    for folder in datasets:
        if not (folder / 'emails/attachments').is_dir():
            continue
        if not any(p.suffix.lower() == '.rar' for p in (folder / 'emails/attachments').iterdir()):
            continue
        log_path = folder / 'rar_recovery.log'
        with log_path.open('a', encoding='utf-8') as log:
            with contextlib.redirect_stdout(Tee(sys.stdout, log)), contextlib.redirect_stderr(Tee(sys.stderr, log)):
                try:
                    report = recover(folder, prepare_only=args.prepare_only)
                    if (report.get('archive_errors') or report.get('msg_errors') or
                        report.get('office', {}).get('err') or
                        any(r['status'] == 'error' for r in report.get('results', [])) or
                        any(r.get('failed_pages') for r in report.get('pdf_quality', {}).values())):
                        exit_code = 2
                except Exception as error:
                    print(f'[-] تکمیل ناموفق: {folder}: {error}', flush=True)
                    exit_code = 1
                    if not args.all:
                        return 1
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())

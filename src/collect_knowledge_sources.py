# -*- coding: utf-8 -*-
"""جمع‌آوری گزارش دانش و اصل مدارک با ردیابی شناسه‌های NotebookLM، بدون شبکه."""
from project_paths import PROJECT_ROOT
import argparse
import hashlib
import json
import os
import re
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(PROJECT_ROOT)
DEFAULT_INPUT = ROOT / 'درس اموخته و ثبت پیشنهادات فنی'
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
REF = re.compile(r'\b(?:E-[0-9a-f]{20}|A-[0-9a-f]{20}(?:-T-[0-9a-f]{12})?)\b', re.I)


def longpath(path):
    value = str(Path(path).resolve())
    return '\\\\?\\' + value if os.name == 'nt' and not value.startswith('\\\\?\\') else value


def digest(path):
    h = hashlib.sha256()
    with open(longpath(path), 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def normalized(text):
    return text.replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ')


def paragraphs(path):
    with zipfile.ZipFile(longpath(path)) as archive:
        tree = ET.fromstring(archive.read('word/document.xml'))
    return [''.join(t.text or '' for t in p.findall('.//w:t', NS)).strip()
            for p in tree.findall('.//w:p', NS)]


def title_for(path, lines):
    for index, line in enumerate(lines):
        match = re.match(r'^عنوان\s*[:：]\s*(.*)', line)
        if match:
            title = match[1].strip() or next((s for s in lines[index + 1:] if s), '')
            if title:
                return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip().rstrip('. ')
    return path.stem.strip().rstrip('. ')


def read_header(path):
    content = path.read_text(encoding='utf-8-sig')
    header = content.split('---', 2)[1] if content.startswith('---') else ''
    fields = {}
    for line in header.splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            fields[key.strip()] = value.strip()
    return fields, content


def load_manifest(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    emails, attachments = {}, {}
    for bundle in data['bundles']:
        for record in bundle['emails']:
            emails[record['id']] = record
        for record in bundle['attachments']:
            attachments[record['id']] = record
    return path, emails, attachments


def display_path(path):
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def resolve_source(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('مسیر منبع در مانیفست خارج از ریشه آرشیو انتخاب‌شده است.')
    return path


def source_manifest(archive, selected=None):
    if selected:
        path = selected.resolve()
        if not path.is_file():
            raise ValueError('فایل نقشه ارجاع انتخاب‌شده وجود ندارد.')
        return path
    candidates = list(archive.rglob('bundle_manifest.json'))
    if len(candidates) != 1:
        raise ValueError('فایل bundle_manifest.json را انتخاب کنید؛ در آرشیو هیچ فایل یا چند فایل با این نام وجود دارد.')
    return candidates[0]


def matching_previous(plan, previous, output):
    expected = {(f['sha256'], tuple(sorted(f['references']))) for f in plan['files']}
    for old in previous:
        if old['report'] != plan['report'] or old['report_sha256'] != plan['report_sha256']:
            continue
        actual = {(f['sha256'], tuple(sorted(f['references']))) for f in old['files']}
        if actual != expected or old.get('unresolved') != plan['unresolved']:
            continue
        folder = output / old['folder']
        try:
            if digest(folder / old['report']) == plan['report_sha256'] and all(
                    digest(folder / f['filename']) == f['sha256'] for f in old['files']):
                return old
        except OSError:
            pass
    return None


def index_messages(paths):
    import extract_msg
    by_id, by_name, errors = defaultdict(list), defaultdict(list), []
    for path in sorted(set(paths), key=str):
        try:
            message = extract_msg.openMsg(str(path))
            try:
                message_id = str(getattr(message, 'messageId', None) or digest(path)).strip()
            finally:
                message.close()
            by_id[message_id].append(path)
            by_name[path.name].append((message_id, path))
        except Exception as error:
            errors.append({'source': display_path(path), 'error': str(error)})
    return by_id, by_name, errors


def main(argv=None):
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--output', type=Path, help='پوشه مقصد دانش')
    parser.add_argument('--archive', type=Path, default=ROOT, help='ریشه آرشیو؛ مبنای مسیرهای مانیفست')
    parser.add_argument('--manifest', type=Path, help='نقشه ارجاع همان بسته بارگذاری‌شده در NotebookLM')
    parser.add_argument('--msg-input', type=Path, help='پوشه اختیاری MSGهای اصلی در صورت جابه‌جایی')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    ROOT = args.archive.resolve()
    if not ROOT.is_dir():
        raise ValueError('ریشه آرشیو وجود ندارد.')
    source_folder = args.input.resolve()
    reports = sorted(p for p in source_folder.glob('*.docx') if not p.name.startswith('~$'))
    if not reports:
        raise SystemExit('هیچ گزارش Word پیدا نشد.')
    output = args.output.resolve() if args.output else source_folder / 'دانش'
    if output == source_folder:
        raise ValueError('پوشه خروجی باید با پوشه گزارش‌های ورودی متفاوت باشد.')
    manifest_path, emails, attachments = load_manifest(source_manifest(ROOT, args.manifest))
    previous_path = output / 'collection_manifest.json'
    previous_summary = json.loads(previous_path.read_text(encoding='utf-8')) if previous_path.exists() else {}
    previous = previous_summary.get('reports', [])
    email_texts = {}
    input_dirs = set()
    for record in emails.values():
        path = resolve_source(record['source'])
        fields, content = read_header(path)
        email_texts[record['id']] = (fields, content)
        dataset = path.parent.parent
        summary_path = dataset / 'pipeline_summary.json'
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            input_dir = Path(summary['input_dir'])
            # مسیر قدیمی فقط اگر هنوز در ریشه انتخاب‌شده باشد خوانده می‌شود.
            if input_dir.is_dir() and input_dir.resolve().is_relative_to(ROOT):
                input_dirs.add(input_dir)
        input_dirs.add(dataset / 'emails/attachments')
    if args.msg_input:
        if not args.msg_input.is_dir():
            raise ValueError('پوشه MSG انتخاب‌شده وجود ندارد.')
        input_dirs.add(args.msg_input.resolve())
    input_dirs.add(ROOT / 'test_inputs/msg')
    msg_paths = [p for folder in input_dirs for p in folder.rglob('*.msg')]
    by_id, by_name, msg_errors = index_messages(msg_paths)
    plans = []
    used_titles = set()
    for report in reports:
        lines = paragraphs(report)
        text = '\n'.join(lines)
        title = title_for(report, lines)
        base_title, number = title, 2
        while title in used_titles:
            title = f'{base_title} ({number})'
            number += 1
        used_titles.add(title)
        refs = sorted(set(REF.findall(text)))
        email_refs = {ref for ref in refs if ref.startswith('E-')}
        attachment_refs = {ref for ref in refs if ref.startswith('A-')}
        notes, missing, selected = [], [], []
        # کدهای دقیق مکاتبات؛ جستجوی لفظی، بدون شباهت معنایی یا انتخاب حدسی.
        codes = sorted(set(re.findall(r'\b(?:TOUS-\d+|S\d+-FERDOWSI)\b', text, re.I)))
        for code in codes:
            hits = {eid for eid, (_, body) in email_texts.items() if code.casefold() in body.casefold()}
            email_refs.update(hits)
            notes.append({'code': code, 'matched_email_ids': sorted(hits), 'method': 'exact_code_in_email'})
            if not hits:
                missing.append({'reference': code, 'reason': 'کد مکاتبه در ایمیل‌های مجموعه یافت نشد.'})
        for eid in sorted(email_refs):
            record = emails.get(eid)
            if not record:
                missing.append({'reference': eid, 'reason': 'شناسه ایمیل در مانیفست یافت نشد.'})
                continue
            fields, _ = email_texts[eid]
            mid = record['message_id'].strip()
            name = fields.get('منبع', '')
            matches = [p for candidate_id, p in by_name.get(name, []) if candidate_id == mid]
            matches = matches or by_id.get(mid, [])
            hashes = {digest(p) for p in matches}
            if len(hashes) == 1:
                selected.append((matches[0], eid, 'ایمیل اصلی MSG'))
            elif not matches:
                missing.append({'reference': eid, 'reason': 'MSG با شناسه پیام مطابق پیدا نشد.', 'source_name': name})
            else:
                missing.append({'reference': eid, 'reason': 'چند MSG با شناسه پیام یکسان و محتوای متفاوت؛ انتخاب خودکار انجام نشد.'})
            # ضمائم ایمیل‌های مورد استناد نیز با نقش جداگانه حفظ می‌شوند.
            for aid in record['attachments']:
                attachment_refs.add(aid)
        for aid in sorted(attachment_refs):
            variants = [attachments[aid]] if aid in attachments else [a for a in attachments.values() if a['raw_id'] == aid]
            if not variants:
                missing.append({'reference': aid, 'reason': 'شناسه پیوست در مانیفست یافت نشد.'})
                continue
            valid_paths = []
            for variant in variants:
                for source in variant['sources']:
                    path = resolve_source(source['raw'])
                    if path.is_file() and digest(path) == variant['raw_hash']:
                        valid_paths.append(path)
            if valid_paths and len({digest(p) for p in valid_paths}) == 1:
                selected.append((valid_paths[0], aid, 'پیوست اصلی مورد استناد' if aid in refs else 'پیوست ایمیل مورد استناد'))
            else:
                missing.append({'reference': aid, 'reason': 'اصل پیوست موجود نیست، هش ناسازگار است یا انتخاب مبهم است.'})
        # نقشه و مدرک فقط با کد کامل دقیق، با حذف فاصله در نام، شناسایی می‌شوند.
        drawing_codes = sorted(set(re.findall(r'\bMD1-[A-Za-z0-9.-]+', text)))
        for code in drawing_codes:
            needle = re.sub(r'\s+', '', code).casefold()
            candidates = []
            for attachment in attachments.values():
                for source in attachment['sources']:
                    name = re.sub(r'\s+', '', Path(source['raw']).stem).casefold()
                    if needle in name:
                        path = resolve_source(source['raw'])
                        if path.is_file() and digest(path) == attachment['raw_hash']:
                            candidates.append(path)
            if candidates and len({digest(p) for p in candidates}) == 1:
                selected.append((candidates[0], code, 'مدرک با کد کامل مطابق'))
            else:
                for path in candidates:
                    selected.append((path, code, 'نسخه متفاوت مدرک با کد مطابق؛ نیازمند تعیین نسخه نهایی'))
                missing.append({'reference': code, 'reason': 'مدرک با کد کامل یافت نشد یا چند نسخه متفاوت دارد.',
                                'candidates': sorted({display_path(p) for p in candidates})})
        # نام یکسانِ محتوای متفاوت نباید بازنویسی شود؛ محتوای یکسان یک بار کپی می‌شود.
        files, hash_entries, names = [], {}, {report.name.casefold()}
        for path, reference, role in selected:
            sha = digest(path)
            if sha in hash_entries:
                entry = hash_entries[sha]
                if reference not in entry['references']:
                    entry['references'].append(reference)
                if role not in entry['roles']:
                    entry['roles'].append(role)
                continue
            name = path.name
            if name.casefold() in names:
                name = f'{path.stem}_{sha[:12]}{path.suffix}'
            names.add(name.casefold())
            entry = {'source': display_path(path), 'filename': name, 'sha256': sha,
                     'references': [reference], 'roles': [role]}
            hash_entries[sha] = entry
            files.append(entry)
        if not refs and not codes and not drawing_codes:
            missing.append({'reference': 'منابع گزارش', 'reason': 'شناسه یا کد قابل تطبیق در گزارش وجود ندارد.'})
        plans.append({'report': report.name, 'report_sha256': digest(report), 'folder': title,
                      'files': files, 'unresolved': missing, 'code_matches': notes})
    reserved_folders = set()
    for plan in plans:
        old = matching_previous(plan, previous, output)
        if old:
            plan['folder'] = old['folder']
            plan['status'] = 'unchanged'
        else:
            base, number = plan['folder'], 2
            while os.path.exists(longpath(output / plan['folder'])) or plan['folder'].casefold() in reserved_folders:
                plan['folder'] = f'{base} ({number})'
                number += 1
            plan['status'] = 'new'
        reserved_folders.add(plan['folder'].casefold())
    retained = [old for old in previous if old['folder'] not in {p['folder'] for p in plans}]
    summary = {'manifest': display_path(manifest_path), 'archive_root': str(ROOT),
               'input_folder': str(source_folder), 'reports': retained + plans,
               'msg_read_errors': msg_errors, 'policy': 'اصل فایل‌ها؛ بدون Markdown و ZIP؛ ضمائم ایمیل‌های ارجاع‌شده نیز محفوظ‌اند.'}
    if not args.dry_run:
        output.mkdir(parents=True, exist_ok=True)
        for plan in plans:
            if plan['status'] == 'unchanged':
                continue
            destination = output / plan['folder']
            os.makedirs(longpath(destination))
            original_report = source_folder / plan['report']
            target_report = destination / plan['report']
            shutil.copy2(longpath(original_report), longpath(target_report))
            if digest(target_report) != plan['report_sha256']:
                raise RuntimeError('کپی گزارش تطابق ندارد.')
            for entry in plan['files']:
                target = destination / entry['filename']
                shutil.copy2(longpath(ROOT / entry['source']), longpath(target))
                if digest(target) != entry['sha256']:
                    raise RuntimeError('کپی منبع تطابق ندارد.')
        temp_manifest = output / 'collection_manifest.json.tmp'
        temp_manifest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        temp_manifest.replace(output / 'collection_manifest.json')
        report_lines = ['# نتیجه جمع‌آوری اصل مدارک دانش', '', 'گزارش Word و منابع اصلی در پوشه هر موضوع قرار دارند. هیچ فایل Markdown منبعی ضمیمه نشده است.', '']
        for plan in summary['reports']:
            report_lines.extend([f"## {plan['folder']}", '', f"تعداد منابع اصلی کپی‌شده: {len(plan['files'])}", ''])
            for entry in plan['files']:
                report_lines.append(f"- {entry['filename']} — {'، '.join(entry['references'])}")
            for item in plan['unresolved']:
                report_lines.append(f"- **نیازمند بررسی:** {item['reference']} — {item['reason']}")
            report_lines.append('')
        (output / 'collection_report.md').write_text('\n'.join(report_lines), encoding='utf-8')
    for plan in plans:
        print(json.dumps({'report': plan['report'], 'status': plan['status'], 'files': len(plan['files']), 'unresolved': plan['unresolved']}, ensure_ascii=False))
    print('OUTPUT', str(output), 'DRY_RUN', args.dry_run)
    print('MSG_READ_ERRORS', len(msg_errors))


if __name__ == '__main__':
    main()

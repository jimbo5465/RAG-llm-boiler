# -*- coding: utf-8 -*-
"""بسته‌بندی محلی Markdown ایمیل‌ها، بدون OCR، خلاصه‌سازی یا تغییر منابع."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from project_paths import PROJECT_ROOT

ROOT = Path(PROJECT_ROOT)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def split_header(text):
    match = re.match(r'\A\ufeff?---\r?\n(.*?)\r?\n---(?:\r?\n|$)', text, re.S)
    if not match:
        return '', text
    return match[1], text[match.end():]


def field(header, key, default=''):
    match = re.search(r'^' + re.escape(key) + r':\s*(.*)$', header, re.M)
    return match[1].strip() if match else default


def nested(text, offset=2):
    """تنها عمق عنوان‌ها تغییر می‌کند؛ کد، جدول، اعداد و متن حفظ می‌شوند."""
    result = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        elif fence is None:
            line = re.sub(r'^(#{1,6})(\s+)', lambda m: '#' * min(6, len(m[1]) + offset) + m[2], line)
        result.append(line)
    return '\n'.join(result).strip()


def relative(path):
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def load_records(datasets):
    emails, attachments, snapshots = [], {}, {}
    for dataset in datasets:
        folder = ROOT / 'Extracted_Data' / dataset
        if not folder.resolve().is_relative_to((ROOT / 'Extracted_Data').resolve()):
            raise ValueError('مسیر مجموعه خارج از Extracted_Data است.')
        manifest_file = folder / 'attachment_manifest.json'
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        snapshots[relative(manifest_file)] = digest(manifest_file)
        files = sorted((folder / 'emails').glob('*.md'))
        if not files:
            raise ValueError(f'ایمیل Markdown یافت نشد: {dataset}')
        names = {p.name for p in files}
        inverse = {name: [] for name in names}
        for raw_name, parents in manifest.items():
            raw = folder / 'emails' / 'attachments' / raw_name
            if raw.name != raw_name or not raw.is_file():
                raise ValueError(f'پیوست مانیفست موجود نیست یا نام نامعتبر است: {raw_name}')
            missing = set(parents) - names
            if missing:
                raise ValueError(f'والد ناموجود: {sorted(missing)}')
            raw_hash = digest(raw)
            snapshots[relative(raw)] = raw_hash
            # نام‌های متفاوت با محتوای خام دقیقاً یکسان، یک پیوست هستند.
            raw_id = 'A-' + raw_hash[:20]
            variants = [d / (raw.stem + '.md') for d in
                        [folder / 'attachments_ocr_google', folder / 'attachments_text']]
            existing = [p for p in variants if p.is_file()]
            if len(existing) > 1:
                raise ValueError(f'دو خروجی متنی برای یک پیوست: {raw_name}')
            md = existing[0] if existing else None
            header, body = split_header(md.read_text(encoding='utf-8')) if md else ('', '')
            if md:
                snapshots[relative(md)] = digest(md)
            # اصل یکسان ممکن است در اجراهای تاریخی OCR متفاوت داشته باشد.
            # هر والد همان نسخهٔ متن و پوشش مجموعهٔ خودش را می‌گیرد؛ انتخاب حدسی نداریم.
            compact_header = '\n'.join(line for line in header.splitlines()
                                       if line.startswith(('نوع:', 'پوشش:', 'یادداشت:')))
            variant_hash = hashlib.sha256((compact_header + '\n' + body.strip()).encode('utf-8')).hexdigest()
            aid = raw_id + '-T-' + variant_hash[:12]
            item = attachments.setdefault(aid, {'id': aid, 'raw_id': raw_id,
                                                'text_variant_sha256': variant_hash,
                                                'raw_hash': raw_hash, 'sources': [],
                                                'body': body, 'header': header, 'parents': []})
            item['sources'].append({'raw': relative(raw), 'markdown': relative(md) if md else None,
                                    'name': raw_name})
            for parent in parents:
                inverse[parent].append(aid)
        for path in files:
            text = path.read_text(encoding='utf-8')
            header, body = split_header(text)
            snapshots[relative(path)] = digest(path)
            eid = 'E-' + hashlib.sha256(relative(path).encode('utf-8')).hexdigest()[:20]
            listed = re.findall(r'^- attachments/(.+)$', header, re.M)
            if any(name not in manifest or path.name not in manifest[name] for name in listed):
                raise ValueError(f'فهرست پیوست ایمیل با مانیفست سازگار نیست: {path.name}')
            row = {'id': eid, 'source': relative(path), 'header': header, 'body': body,
                   'subject': field(header, 'موضوع', path.stem),
                   'date': field(header, 'تاریخ شمسی', 'نامشخص'),
                   'message_id': field(header, 'شناسه'),
                   'attachments': sorted(set(inverse[path.name]))}
            emails.append(row)
            for aid in row['attachments']:
                attachments[aid]['parents'].append(eid)
    emails.sort(key=lambda e: (e['date'], e['source']))
    # فایل متنی بی‌والد نباید بی‌صدا کنار گذاشته شود.
    mapped = {s['markdown'] for a in attachments.values() for s in a['sources'] if s['markdown']}
    for dataset in datasets:
        for sub in ['attachments_text', 'attachments_ocr_google']:
            for path in (ROOT / 'Extracted_Data' / dataset / sub).glob('*.md'):
                if relative(path) not in mapped:
                    raise ValueError(f'Markdown پیوست بدون ارتباط مانیفست: {relative(path)}')
    return emails, attachments, snapshots


def render_appendix(rows, attachments):
    aids = list(dict.fromkeys(a for row in rows for a in row['attachments']))
    parts = ['# آرشیو مکاتبات فنی — بستهٔ ایمیل و پیوست',
             'هر بخش ایمیل مستقل است. بخش پیوست، متن نویسندهٔ ایمیل نیست. '
             'مسیرها برای مراجعهٔ محلی‌اند و دسترسی آنلاین به اصل فایل ایجاد نمی‌کنند. '
             'OCR، به‌ویژه اعداد، جدول‌ها و دست‌نویس، ممکن است خطا داشته باشد.',
             '## فهرست ایمیل‌های این بسته']
    parts.extend(f"- {e['id']} | {e['date']} | {e['subject']}" for e in rows)
    for e in rows:
        parts.extend([f"## شروع ایمیل {e['id']} — {e['subject']}",
                      f"مسیر Markdown اصلی: {e['source']}", '### مشخصات ایمیل'])
        # فهرست قبلی با مسیرهای نسبی نامعتبر در بسته جایگزین می‌شود.
        metadata = e['header'].split('پیوست‌ها:')[0].strip()
        parts.extend([metadata, '### متن و تاریخچهٔ همین ایمیل', nested(e['body']),
                      '### پیوست‌های همین ایمیل'])
        if not e['attachments']:
            parts.append('پیوست ذخیره‌شده‌ای در مانیفست این ایمیل ثبت نشده است.')
        for aid in e['attachments']:
            a = attachments[aid]
            names = '؛ '.join(dict.fromkeys(s['name'] for s in a['sources']))
            status = 'متن در بخش پیوست‌های همین بسته موجود است' if a['body'].strip() else 'بدون متن استخراج‌شده؛ اصل فایل محفوظ است'
            parts.append(f'- {aid}: {names} — {status}.')
        parts.append(f"## پایان ایمیل {e['id']}")
    parts.append('## متن پیوست‌های این بسته')
    for aid in aids:
        a = attachments[aid]
        parents = [e['id'] for e in rows if aid in e['attachments']]
        parts.extend([f'### شروع پیوست {aid}', 'ایمیل‌های مرتبط در همین بسته: ' + '، '.join(parents)])
        for s in a['sources']:
            parts.append('مسیر اصل پیوست: ' + s['raw'])
            if s['markdown']:
                parts.append('مسیر متن استخراج‌شده: ' + s['markdown'])
        # فقط اطلاعات مفید منبع؛ نه امتیاز و روش رندر یا سیاست فنی.
        for line in a['header'].splitlines():
            if line.startswith(('نوع:', 'پوشش:', 'یادداشت:')):
                parts.append(line)
        parts.append(nested(a['body'], 3) if a['body'].strip() else
                     'متن استخراج‌شده موجود نیست. از این وضعیت، خالی‌بودن اصل سند یا تصویر نتیجه‌گیری نشود.')
        parts.append(f'### پایان پیوست {aid}')
    return '\n\n'.join(parts) + '\n'


def attachment_body(item):
    """هشدار همراه منبع حفظ می‌شود؛ ادغام هیچ هشدار کیفیتی اختراع نمی‌کند."""
    return nested(item['body'], 3)


def render(rows, attachments, layout='inline'):
    if layout == 'appendix':
        return render_appendix(rows, attachments)
    if layout != 'inline':
        raise ValueError('چیدمان نامعتبر است.')
    parts = ['# آرشیو مکاتبات فنی — بستهٔ ایمیل و پیوست',
             'هر بخش ایمیل مستقل است. متن پیوست‌ها زیر همان ایمیل آمده است و متن '
             'نویسندهٔ ایمیل نیست. پیوست مشترک با شناسهٔ یکسان تکرار می‌شود؛ این تکرار '
             'به معنی مدرک یا شاهد مستقل جدید نیست. مسیرها برای مراجعهٔ محلی‌اند و '
             'دسترسی آنلاین به اصل فایل ایجاد نمی‌کنند. OCR ممکن است خطا داشته باشد.',
             '## فهرست ایمیل‌های این بسته']
    parts.extend(f"- {e['id']} | {e['date']} | {e['subject']}" for e in rows)
    for e in rows:
        parts.extend([f"## شروع ایمیل {e['id']} — {e['subject']}",
                      f"مسیر Markdown اصلی: {e['source']}", '### مشخصات ایمیل',
                      e['header'].split('پیوست‌ها:')[0].strip(),
                      '### متن و تاریخچهٔ همین ایمیل', nested(e['body']),
                      '### پیوست‌های همین ایمیل'])
        if not e['attachments']:
            parts.append('پیوست ذخیره‌شده‌ای در مانیفست این ایمیل ثبت نشده است.')
        for aid in e['attachments']:
            a = attachments[aid]
            names = '؛ '.join(dict.fromkeys(s['name'] for s in a['sources']))
            parts.extend([f'### شروع پیوست {aid} — {names}',
                          f"ایمیل والد این نسخهٔ پیوست: {e['id']}"])
            if a.get('raw_id'):
                parts.append('شناسهٔ اصل مدرک: ' + a['raw_id'] +
                             '؛ نسخه‌های متنی متفاوت این شناسه، مدرک مستقل نیستند.')
            for s in a['sources']:
                parts.append('مسیر اصل پیوست: ' + s['raw'])
                if s['markdown']:
                    parts.append('مسیر متن استخراج‌شده: ' + s['markdown'])
            parts.extend(line for line in a['header'].splitlines()
                         if line.startswith(('نوع:', 'پوشش:', 'یادداشت:')))
            parts.append(attachment_body(a) if a['body'].strip() else
                         'بدون متن استخراج‌شده؛ اصل فایل محفوظ است. از این وضعیت، '
                         'خالی‌بودن اصل سند یا تصویر نتیجه‌گیری نشود.')
            parts.append(f'### پایان پیوست {aid}')
        parts.append(f"## پایان ایمیل {e['id']}")
    return '\n\n'.join(parts) + '\n'


def measurements(text):
    return {'words': len(text.split()), 'bytes': len(text.encode('utf-8'))}


def plan(rows, attachments, max_words, max_bytes, layout='inline'):
    groups, current = [], []
    for row in rows:
        proposed = current + [row]
        size = measurements(render(proposed, attachments, layout))
        if size['words'] > max_words or size['bytes'] > max_bytes:
            if not current:
                raise ValueError(f"ایمیل و پیوست‌هایش از سقف یک بسته بزرگ‌تر است: {row['source']}")
            groups.append(current)
            current = [row]
            size = measurements(render(current, attachments, layout))
            if size['words'] > max_words or size['bytes'] > max_bytes:
                raise ValueError(f"واحد بیش از سقف؛ بدون شکستن یا حذف: {row['source']}")
        else:
            current = proposed
    if current:
        groups.append(current)
    return groups


def build(datasets, output, max_words=200_000, max_bytes=50_000_000, layout='inline'):
    if not datasets or len(set(datasets)) != len(datasets):
        raise ValueError('مجموعه‌ها باید غیرخالی و غیرتکراری باشند.')
    if not 0 < max_words <= 500_000 or not 0 < max_bytes <= 200_000_000:
        raise ValueError('سقف نامعتبر است.')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('خروجی از قبل موجود است؛ هیچ فایلی بازنویسی یا حذف نشد.')
    if not output.is_relative_to((ROOT / 'Extracted_Data').resolve()):
        raise ValueError('خروجی باید داخل Extracted_Data باشد تا دادهٔ خصوصی وارد گیت نشود.')
    rows, attachments, snapshots = load_records(datasets)
    groups = plan(rows, attachments, max_words, max_bytes, layout)
    rendered = [render(group, attachments, layout) for group in groups]
    if any(digest(ROOT / p) != h for p, h in snapshots.items()):
        raise RuntimeError('منابع هنگام آماده‌سازی تغییر کرده‌اند؛ خروجی نوشته نشد.')
    output.mkdir(parents=True)
    variants = {}
    for a in attachments.values():
        variants.setdefault(a['raw_id'], []).append(a['id'])
    report = {'version': 'notebooklm-bundle-v4', 'datasets': datasets,
              'layout': layout, 'warning_policy': 'preserve_source_only',
              'max_words': max_words, 'max_bytes': max_bytes,
              'word_count_method': 'whitespace approximation; NotebookLM may count differently',
              'emails': len(rows), 'attachments': len(attachments), 'sources_unchanged': True,
              'unique_raw_attachments': len(variants),
              'multiple_text_variants': {k: v for k, v in variants.items() if len(v) > 1},
              'bundles': [], 'source_sha256': snapshots,
              'note': 'فقط Markdown بسته‌ها وارد شود؛ این فایل نقشهٔ محلی است. '
                      'در چیدمان inline متن پیوست زیر هر ایمیل والد تکرار می‌شود؛ '
                      'شناسهٔ یکسان یعنی همان مدرک، نه شاهد مستقل.'}
    for index, (group, text) in enumerate(zip(groups, rendered), 1):
        name = f'notebooklm_{index:03d}.md'
        (output / name).write_text(text, encoding='utf-8', newline='\n')
        aids = list(dict.fromkeys(a for e in group for a in e['attachments']))
        entries = []
        for e in group:
            start = text.index(f"## شروع ایمیل {e['id']}")
            end = text.index(f"## پایان ایمیل {e['id']}")
            entries.append({k: e[k] for k in ['id', 'source', 'message_id', 'attachments']}
                           | {'start_line': text[:start].count('\n') + 1,
                              'end_line': text[:end].count('\n') + 1})
        report['bundles'].append({'file': name, **measurements(text), 'emails': entries,
                                  'attachments': [{k: attachments[a][k] for k in
                                                   ['id', 'raw_id', 'text_variant_sha256',
                                                    'sources', 'parents', 'raw_hash']} for a in aids]})
    report['sources_unchanged'] = all(digest(ROOT / p) == h for p, h in snapshots.items())
    (output / 'bundle_manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not report['sources_unchanged']:
        raise RuntimeError('منابع حین ذخیره تغییر کرده‌اند؛ گزارش را بررسی کنید.')
    print(json.dumps({'output': str(output), 'emails': len(rows), 'attachments': len(attachments),
                      'bundles': [{k: b[k] for k in ['file', 'words', 'bytes']} for b in report['bundles']],
                      'sources_unchanged': True}, ensure_ascii=False, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('datasets', nargs='+')
    parser.add_argument('--output', default='Extracted_Data/notebooklm_second')
    parser.add_argument('--max-words', type=int, default=200_000)
    parser.add_argument('--max-mb', type=float, default=50)
    parser.add_argument('--layout', choices=['inline', 'appendix'], default='inline')
    args = parser.parse_args()
    destination = Path(args.output)
    if not destination.is_absolute():
        destination = ROOT / destination
    build(args.datasets, destination, args.max_words, int(args.max_mb * 1_000_000), args.layout)


if __name__ == '__main__':
    main()

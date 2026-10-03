# -*- coding: utf-8 -*-
"""استخراج ترکیبی صفحه‌به‌صفحه؛ امتیاز سلامت، نه درصد دقت معنایی."""
import io
import json
import os
import re
import time
import unicodedata
from pathlib import Path

import pymupdf as fitz
from googleapiclient.http import MediaIoBaseUpload

import pdf_ocr_quality as quality
from project_paths import PROJECT_ROOT

PERSIAN_WORDS = set('است این آن برای شماره گزارش شرکت درخواست نمونه تاریخ نتیجه نتایج بررسی آزمون مطابق مورد شده صفحه تعداد شرح واحد پیچ مهره بویلر نیروگاه شکست اتصال'.split())
ENGLISH_WORDS = set('the a an and of to in is are for with on by from this that as be at or no report page test inspection material bolt nut casing length weight quantity project sample date number'.split())


def normalize_text(text):
    text = unicodedata.normalize('NFKC', text).replace('ي', 'ی').replace('ك', 'ک')
    # حذف کنترل جهت فقط برای متنی که کنترل کیفیت می‌شود؛ نیم‌فاصله حفظ می‌شود.
    return re.sub('[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', text).strip()


def assess_local(page):
    raw = page.get_text('text', sort=True)
    text = normalize_text(raw)
    result = quality.evaluate_text(text)
    reasons = []
    if result['status'] == 'FAIL':
        reasons.extend(result['reasons'])
    elif 'ساختار متن مشکوک' in result['reasons']:
        reasons.append('ساختار متن محلی مشکوک است')
    if '\ufffd' in raw or '\x00' in raw or re.search(r'\(cid:\d+\)', raw):
        reasons.append('نگاشت نویسه یا فونت خراب است')
    image_area = sum(fitz.Rect(item['bbox']).get_area() for item in page.get_image_info())
    image_ratio = image_area / max(1, page.rect.get_area())
    if image_ratio >= 0.05:
        reasons.append('تصویر قابل توجه در صفحه؛ احتمال متن استخراج‌نشده داخل تصویر')
    # کلمات وارونهٔ متداول، بدون برعکس‌کردن حدسی متن اصلی.
    words = re.findall(r'[\u0600-\u06ff]+', text.replace('\u200c', ''))
    normal = sum(word in PERSIAN_WORDS for word in words)
    reversed_hits = sum(word[::-1] in PERSIAN_WORDS and word not in PERSIAN_WORDS for word in words)
    if reversed_hits >= 3 and reversed_hits > normal:
        reasons.append('واژه‌های فارسی وارونه‌اند')
    if len(words) >= 15 and normal / len(words) < 0.1:
        reasons.append('متن فارسی فاقد نشانهٔ واژگانی کافی؛ نیازمند OCR محافظه‌کارانه')
    latin = re.findall(r'[A-Za-z]{2,}', text)
    if not words and len(latin) >= 15 and not any(word.lower() in ENGLISH_WORDS for word in latin):
        reasons.append('متن لاتین ظاهراً بی‌معنی یا نگاشت مشکوک نویسه‌ها')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 10 and sum(len(re.sub(r'\W', '', line)) <= 2 for line in lines) / len(lines) > 0.4:
        reasons.append('خطوط کوتاه یا حروف جداشدهٔ غیرعادی')
    correction, confident, _ = quality.orientation_hint(page)
    if confident and correction:
        reasons.append('جهت متن محلی غیرعادی است')
    spans = ''.join(span.get('text', '') for block in page.get_text('dict').get('blocks', [])
                    for line in block.get('lines', []) for span in line.get('spans', []))
    if len(normalize_text(spans)) > 100 and len(text) < len(normalize_text(spans)) * 0.8:
        reasons.append('بخشی از متن لایهٔ منبع در استخراج محلی حذف شده است')
    # صفحه‌ای که حتی در لایهٔ منبع تقریباً خالی است، با تصویر بررسی می‌شود.
    if len(re.sub(r'\W', '', text)) < 30:
        reasons.append('متن محلی خالی یا بسیار کم است')
    reasons = list(dict.fromkeys(reasons))
    result.update(needs_ocr=bool(reasons), route_reasons=reasons,
                  image_ratio=round(image_ratio, 3), accuracy_verified=False)
    return text, result


def convert_pdf(source_path, output_path, *, service, service_factory, ocr_media,
                parent_emails=None, log_func=print, rotation_overrides=None,
                max_page_retries=2, reuse_raw=False, speed_engine=None):
    source_path, output_path = Path(source_path), Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics = quality.diagnostics_path(output_path)
    diagnostics.mkdir(parents=True, exist_ok=True)
    owned_service = False
    size_mb = os.path.getsize(source_path) / 1024 / 1024
    report = {'version': 'hybrid-page-v1', 'pages': [], 'requests': 0, 'upload_bytes': 0,
              'retry_requests': 0,
              'local_pages': [], 'google_pages': [], 'cache_pages': [], 'coverage_verified': True,
              'limitations': ['سلامت متن تضمین صحت معنایی، اعداد یا ساختار جدول نیست.']}
    texts = {}
    retries = 0
    last_request = None
    overrides = rotation_overrides or {}
    try:
        with fitz.open(source_path) as doc:
            if not len(doc) or doc.is_encrypted:
                raise ValueError('PDF خالی یا رمزگذاری‌شده است.')
            reasons = []
            if size_mb > quality.SIZE_LIMIT_MB:
                reasons.append('حجم بیشتر از ۱۰ مگابایت')
            if len(doc) > quality.PAGE_LIMIT:
                reasons.append('تعداد صفحات بیشتر از ۱۵ صفحه')
            count = min(quality.PREVIEW_PAGES, len(doc)) if reasons else len(doc)
            report['source'] = {'total': len(doc), 'processed': count, 'partial': count < len(doc),
                                'reason': '؛ '.join(reasons), 'size_mb': size_mb, 'method': 'hybrid_page_by_page'}
            log_func(f'    بررسی محلی {count} از {len(doc)} صفحه؛ وضوح OCR: ۳۰۰ DPI')
            if reasons:
                log_func(f"    محدودیت: {'؛ '.join(reasons)}؛ پردازش {count} صفحهٔ اول")
            for index in range(count):
                number, page = index + 1, doc[index]
                local_text, local = assess_local(page)
                if number in overrides and overrides[number] % 360:
                    local['needs_ocr'] = True
                    local['route_reasons'].append('چرخش صفحه توسط کاربر تعیین شده است')
                if not local['needs_ocr']:
                    entry = dict(local, number=number, method='local', boundaries_verified=True)
                    texts[number] = local_text
                    report['local_pages'].append(number)
                    log_func(f"    صفحه {number}: متن محلی پذیرفته شد؛ {entry['characters']} کاراکتر؛ بدون ارسال")
                else:
                    report['google_pages'].append(number)
                    log_func(f"    صفحه {number}: نیازمند گوگل؛ {'؛ '.join(local['route_reasons'])}")
                    correction, _, _ = quality.orientation_hint(page)
                    correction = overrides.get(number, correction) % 360
                    if correction:
                        log_func(f'    صفحه {number}: اصلاح چرخش {correction} درجه خلاف ساعت')
                    anchors = quality.source_anchors(page)
                    entry = dict(quality.evaluate_text(''), number=number, method='google',
                                 boundaries_verified=True, route_reasons=local['route_reasons'])
                    if speed_engine is not None:
                        try:
                            resolved = speed_engine.lookup(source_path, number)
                            report['requests'] += resolved.get('requests', 0)
                            report['upload_bytes'] += resolved.get('upload_bytes', 0)
                            report['retry_requests'] += int(resolved.get('retried', False))
                            if resolved.get('error'):
                                raise RuntimeError(resolved['error'])
                            clean = normalize_text(quality.text_only(resolved['text']))
                            candidate = quality.evaluate_text(clean)
                            quality.check_anchors(candidate, clean, anchors)
                            entry.update(candidate)
                            entry['method'] = resolved['method']
                            entry['timings'] = resolved.get('timings', {})
                            entry['batch_id'] = resolved.get('batch_id')
                            entry['fallback'] = resolved.get('fallback', False)
                            if entry['method'] in ('cache', 'duplicate'):
                                report['cache_pages'].append(number)
                            if candidate['status'] != 'FAIL':
                                texts[number] = clean
                                entry['status'] = 'WARNING'
                                entry['reasons'].append('متن OCR؛ صحت کامل اعداد و تصویر تأیید نشده است')
                                log_func(f"    صفحه {number}: {entry['method']}؛ در موقعیت اصلی قرار گرفت")
                            else:
                                entry['error'] = 'متن ذخیره‌شده کنترل سلامت منبع جاری را رد کرد.'
                        except Exception as exc:
                            entry.update(status='FAIL', error=str(exc))
                            entry['reasons'].append(str(exc))
                            log_func(f'    صفحه {number}: خروجی تأییدنشده؛ {exc}')
                    # همهٔ صفحات مشکوک یک درخواست اولیه می‌گیرند؛ فقط تکرار محدود است.
                    for attempt in range(0 if speed_engine is not None else 2):
                        if attempt:
                            if retries >= max(0, max_page_retries):
                                entry['reasons'].append('سقف تلاش مجدد سند رسیده است')
                                break
                            retries += 1
                            report['retry_requests'] = retries
                        cache = diagnostics / f"page_{number:04d}{'_retry' if attempt else ''}.txt"
                        media = None
                        try:
                            if reuse_raw:
                                raw = cache.read_text(encoding='utf-8')
                            else:
                                image = quality.render_page(page, number, dpi=300,
                                                            rotation=correction, markers=False)
                                data = quality.jpeg_bytes(image)
                                if len(data) > quality.UPLOAD_GUARD_BYTES:
                                    raise ValueError('تصویر صفحه از محافظ حجم داخلی بیشتر است؛ ارسال نشد.')
                                if service is None:
                                    service = service_factory()
                                    owned_service = True
                                if last_request is not None:
                                    time.sleep(max(0, 1 - (time.monotonic() - last_request)))
                                media = MediaIoBaseUpload(io.BytesIO(data), mimetype='image/jpeg', resumable=True)
                                report['requests'] += 1
                                report['upload_bytes'] += len(data)
                                log_func(f"    ارسال مستقل صفحه {number}{' (تلاش مجدد)' if attempt else ''}: {len(data)/1024/1024:.2f} MB، ۳۰۰ DPI")
                                if len(data) > quality.RECOMMENDED_BYTES:
                                    log_func('    هشدار: تصویر از اندازهٔ توصیه‌شدهٔ ۲ MB بزرگ‌تر است؛ نتیجه تضمین نمی‌شود')
                                try:
                                    raw = ocr_media(media, f'page_{number:04d}_{source_path.name}', 'image/jpeg', service)
                                finally:
                                    last_request = time.monotonic()
                                cache.write_text(raw, encoding='utf-8')
                            clean = normalize_text(quality.text_only(raw))
                            clean = quality.MARKER_RE.sub('', clean).strip()
                            candidate = quality.evaluate_text(clean)
                            quality.check_anchors(candidate, clean, anchors)
                            entry.update(candidate)
                            log_func(f"    پاسخ صفحه {number}: {entry['status']}، {entry['characters']} کاراکتر")
                            if candidate['status'] != 'FAIL':
                                entry.pop('error', None)
                                if candidate['status'] == 'PASS':
                                    entry['status'] = 'WARNING'
                                entry['reasons'].append('متن OCR؛ صحت کامل اعداد و تصویر تأیید نشده است')
                                texts[number] = clean
                                break
                        except Exception as exc:
                            entry.update(status='FAIL', error=str(exc))
                            entry['reasons'].append(f'خطای OCR: {exc}')
                            log_func(f'    خطا در صفحه {number}: {exc}')
                            if reuse_raw:
                                break  # حالت استفادهٔ مجدد هرگز درخواست تازه به گوگل نمی‌فرستد.
                        finally:
                            if media is not None:
                                media.stream().close()
                report['pages'].append(entry)
                quality.update_status(report)
                # گزارش ناقص هم برای وقفه یا خروج اضطراری روی دیسک ثبت می‌شود.
                (diagnostics / 'quality.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        if owned_service and service is not None:
            service.close()
    report['coverage_verified'] = all(entry['status'] != 'FAIL' for entry in report['pages'])
    quality.update_status(report)
    (diagnostics / 'quality.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    header = ['---', f'پیوست: {source_path.name}', 'نوع: متن پیوست',
              f"پوشش: صفحات ۱ تا {count} از {report['source']['total']} صفحه",
              f'فایل_اصلی: {os.path.relpath(source_path.resolve(), PROJECT_ROOT)}']
    if parent_emails:
        header.extend(['ایمیل‌های مرتبط (والد):', *[f'  - {name}' for name in parent_emails]])
    header.append('---')
    notices = []
    if report['source']['partial']:
        notices.append(f"> فقط {count} صفحهٔ اول از {report['source']['total']} صفحه پردازش شده؛ این خروجی متن کامل سند نیست.")
    failures = [entry['number'] for entry in report['pages'] if entry['status'] == 'FAIL']
    if failures:
        notices.append(f"> خروجی ناقص است؛ متن صفحات {'، '.join(map(str, failures))} تأیید نشده است.")
    sections = [f"## صفحه {number}\n\n{texts.get(number, '> متن این صفحه تأیید نشده است؛ به اصل پیوست مراجعه کنید.')}"
                for number in range(1, count + 1)]
    output_path.write_text('\n'.join(header) + '\n\n' + '\n\n'.join(notices + sections), encoding='utf-8')
    log_func(f"    ذخیره شد: {len(report['local_pages'])} صفحه محلی، {len(report['google_pages'])} صفحه مسیر گوگل، {report['requests']} درخواست")
    return True

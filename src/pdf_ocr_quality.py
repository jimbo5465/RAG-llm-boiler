# -*- coding: utf-8 -*-
"""آماده‌سازی PDF برای Google OCR و کنترل کیفیت محافظه‌کارانه.

هیچ امتیاز این ماژول تضمین صحت عدد، ترجمه یا ساختار جدول نیست.
"""
import io
import hashlib
import json
import os
import re
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont

VERSION = "clean-pdf-v1"
RAG_POLICY = "email_first_v1"
SIZE_LIMIT_MB = 10
PAGE_LIMIT = 15
PREVIEW_PAGES = 5
UPLOAD_GUARD_BYTES = 25 * 1024 * 1024  # محافظ داخلی برنامه؛ نه سقف رسمی OCR گوگل
RECOMMENDED_BYTES = 2 * 1024 * 1024
MARKER_RE = re.compile(r"RAGPAGE\s*([0-9]{4})\s*(BEGIN|END)", re.I)
ANCHORS = ['Packing List', 'BOLT GAL', 'CASING', 'INSPECTION RELEASE NOTE',
           'REPORT NO', 'DWG NO', 'DIAGONAL', 'PLUMBNESS', 'CALIBRATION',
           'MATERIAL NO', 'NET WEIGHT', 'QTY', 'MANUFACTURER NAME']


def diagnostics_path(output):
    """Windows نام پوشهٔ پایان‌یافته با فاصله/نقطه را نرمال می‌کند؛ مسیر فرزند شکست می‌خورد."""
    output = Path(output)
    name = output.stem
    trimmed = name.rstrip(' .')
    if trimmed != name:
        name = (trimmed or 'attachment') + '__' + hashlib.sha256(output.name.encode('utf-8')).hexdigest()[:12]
    return output.parent / '_ocr_diagnostics' / name


def compact(text):
    return re.sub(r'[^A-Z0-9]', '', text.upper())


def source_anchors(page):
    native = compact(page.get_text())
    return [anchor for anchor in ANCHORS if compact(anchor) in native]


def check_anchors(result, text, anchors):
    normalized = compact(text_only(text))
    missing = [anchor for anchor in anchors if compact(anchor) not in normalized]
    result['source_anchors'] = anchors
    result['missing_source_anchors'] = missing
    if missing:
        result['reasons'].append('عبارت‌های منبع در OCR پیدا نشد: ' + '، '.join(missing))
        if 'CALIBRATION' in missing or (
                len(missing) >= 2 and len(missing) / max(1, len(anchors)) >= 0.5):
            result['status'] = 'FAIL'
        elif result['status'] != 'FAIL':
            result['status'] = 'WARNING'
    return result


def text_only(text):
    text = re.sub(r"\[image\d+\]:\s*<data:image/[^>]+>", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)|!\[\]\[image\d+\]", "", text)
    return text.strip()


def scan_like(page):
    """تصویر بزرگ، فقدان متن یا نویسهٔ جایگزین: رندر به‌جای اعتماد به لایهٔ متن."""
    area = max(1, page.rect.get_area())
    image_area = sum(fitz.Rect(info["bbox"]).get_area()
                     for info in page.get_image_info())
    text = page.get_text()
    return image_area / area >= 0.5 or len(text.strip()) < 20 or "\ufffd" in text


def orientation_hint(page):
    """استفاده از جهت خطوط بلند لایهٔ متن؛ علائم ریز نقشه رأی نمی‌دهند."""
    votes = {0: 0, 90: 0, 180: 0, 270: 0}
    directions = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            letters = len(re.findall(r"[A-Za-z\u0600-\u06ff]", text))
            if letters < 12:
                continue
            direction = tuple(round(value) for value in line.get("dir", (1, 0)))
            if direction in directions:
                votes[directions[direction]] += letters
    total = sum(votes.values())
    best = max(votes, key=votes.get)
    confident = total >= 80 and votes[best] / max(1, total) >= 0.8
    # PIL.rotate مثبت، خلاف عقربه ساعت است؛ جهت (0,-1) باید ساعتگرد شود.
    correction = (-best) % 360 if confident else 0
    return correction, confident, votes


def render_page(page, number, dpi=300, rotation=0, markers=True):
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if rotation:
        image = image.rotate(rotation, expand=True, fillcolor="white")
    if not markers:
        return image
    margin = max(100, int(dpi * 0.4))
    canvas = Image.new("RGB", (image.width, image.height + 2 * margin), "white")
    canvas.paste(image, (0, margin))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=max(24, int(dpi * 0.12)))
    draw.text((40, 20), f"RAGPAGE{number:04d}BEGIN", fill="black", font=font)
    draw.text((40, image.height + margin + 20), f"RAGPAGE{number:04d}END", fill="black", font=font)
    return canvas


def jpeg_bytes(image, quality=90):
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=quality, optimize=True)
    return stream.getvalue()


def prepare_pdf(source, output, rotation_overrides=None, force_raster=False, log_func=None):
    """اعمال محدودیت قبل از رندر؛ ساخت یک PDF واحد با شناسهٔ صفحه."""
    source, output = Path(source), Path(output)
    overrides = rotation_overrides or {}
    size_mb = os.path.getsize(source) / (1024 * 1024)
    with fitz.open(source) as doc:
        if not len(doc) or doc.is_encrypted:
            raise ValueError("PDF خالی یا رمزگذاری‌شده است.")
        reasons = []
        if size_mb > SIZE_LIMIT_MB:
            reasons.append("حجم فایل بیشتر از ۱۰ مگابایت")
        if len(doc) > PAGE_LIMIT:
            reasons.append("تعداد صفحات بیشتر از ۱۵ صفحه")
        count = min(PREVIEW_PAGES, len(doc)) if reasons else len(doc)
        info = {"version": VERSION, "total": len(doc), "processed": count,
                "partial": count < len(doc), "reason": "؛ ".join(reasons),
                "size_mb": size_mb, "pages": [], "recommended_upload_bytes": RECOMMENDED_BYTES}
        rasterize = force_raster or any(scan_like(doc[i]) for i in range(count))
        info["method"] = "rasterized_pdf" if rasterize else "digital_pdf"
        if log_func:
            log_func(f"    آماده‌سازی: {len(doc)} صفحه، {size_mb:.2f} MB؛ "
                     f"{'تبدیل به عکس ۳۰۰ DPI و PDF تمیز' if rasterize else 'PDF دیجیتال برای ارسال مستقیم به گوگل'}")
            if reasons:
                log_func(f"    محدودیت: {'؛ '.join(reasons)}؛ فقط {count} صفحهٔ اول")
        # فقط برای محافظ حجم داخلی، کیفیت JPEG کم می‌شود؛ تعداد صفحات تغییر نمی‌کند.
        for quality in ([90, 80, 70] if rasterize else [90]):
            with fitz.open() as clean:
                page_infos = []
                for index in range(count):
                    if log_func:
                        log_func(f"    صفحه {index + 1}/{count}: "
                                 f"{'رندر تصویر' if rasterize else 'آماده‌سازی دیجیتال'}، کیفیت JPEG={quality}")
                    page = doc[index]
                    correction, confident, votes = orientation_hint(page)
                    if index + 1 in overrides:
                        correction = overrides[index + 1] % 360
                        confident = True
                    if log_func and rasterize and correction:
                        log_func(f"    صفحه {index + 1}: اصلاح چرخش {correction} درجه خلاف ساعت")
                    record = {"number": index + 1, "rotation_ccw": correction if rasterize else 0,
                              "orientation_checked": confident, "orientation_votes": votes,
                              "source_anchors": source_anchors(page),
                              "source_character_count": len(page.get_text()),
                              "scan_like": scan_like(page)}
                    if rasterize:
                        image = render_page(page, index + 1, rotation=correction)
                        target = clean.new_page(width=image.width * 72 / 300,
                                                height=image.height * 72 / 300)
                        target.insert_image(target.rect, stream=jpeg_bytes(image, quality))
                    else:
                        clean.insert_pdf(doc, from_page=index, to_page=index)
                        target = clean[-1]
                        # افزودن حاشیه بدون پوشاندن محتوای سند دیجیتال.
                        old_rect = target.rect
                        with fitz.open() as wrapper:
                            wrapper.insert_pdf(clean, from_page=len(clean)-1, to_page=len(clean)-1)
                            clean.delete_page(len(clean)-1)
                            target = clean.new_page(width=old_rect.width, height=old_rect.height + 80)
                            target.show_pdf_page(fitz.Rect(0, 40, old_rect.width, old_rect.height + 40), wrapper, 0)
                            target.insert_text((20, 24), f"RAGPAGE{index+1:04d}BEGIN", fontsize=12)
                            target.insert_text((20, old_rect.height + 64), f"RAGPAGE{index+1:04d}END", fontsize=12)
                    page_infos.append(record)
                data = clean.tobytes(garbage=4, deflate=True)
            if log_func:
                log_func(f"    حجم نسخهٔ آماده: {len(data) / 1024 / 1024:.2f} MB "
                         f"(حجم اصلی {size_mb:.2f} MB)")
            if len(data) <= UPLOAD_GUARD_BYTES:
                break
            if log_func:
                log_func("    حجم آماده از محافظ داخلی بیشتر است؛ کاهش کیفیت JPEG برای فشرده‌سازی")
        if len(data) > UPLOAD_GUARD_BYTES:
            raise ValueError("PDF آماده‌شده از محافظ حجم داخلی برنامه بیشتر است؛ ارسال نشد.")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        info.update(pages=page_infos, upload_bytes=len(data), jpeg_quality=quality,
                    above_google_recommended_size=len(data) > RECOMMENDED_BYTES)
        # نسخهٔ تصویری نباید هیچ لایهٔ متن، حتی شناسهٔ برداری، داشته باشد.
        with fitz.open(output) as check:
            if len(check) != count or (rasterize and any(p.get_text().strip() for p in check)):
                raise RuntimeError("اعتبارسنجی PDF آماده‌شده ناموفق بود.")
    return info


OCR_SOURCE_WARNING = (
    '> هشدار اعتبار متن: این متن با OCR از تصویر صفحه استخراج شده است. '
    'کلمات، اعداد و مفهوم ممکن است نادرست منتقل شده باشند؛ خطا در نوشته‌های '
    'دست‌نویس فارسی می‌تواند بسیار شدید باشد. برای نتیجه‌گیری حساس به اصل '
    'پیوست مراجعه کنید. نوع نوشتار و درصد دقت تأیید نشده است.'
)


def evaluate_text(text):
    clean = text_only(text)
    tokens = re.findall(r"\S+", clean)
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    singles = sum(len(re.sub(r"\W", "", line)) <= 1 for line in lines) / max(1, len(lines))
    repeats = len(re.findall(r"([A-Za-z])\1{4,}", clean))
    symbols = sum(char in "^~<>\\{}" for char in clean) / max(1, len(clean))
    reasons = []
    status = "PASS"
    if len(re.sub(r"\W", "", clean)) < 30:
        status = "FAIL"
        reasons.append("متن خالی یا بسیار کم؛ نیازمند بررسی با تصویر")
    if singles > 0.5 and len(lines) > 15 or repeats >= 3 or symbols > 0.12:
        status = "FAIL"
        reasons.append("نویز زیاد، خطوط تک‌حرفی یا تکرار غیرعادی")
    elif singles > 0.25 and len(lines) > 15 or repeats:
        if status != "FAIL":
            status = "WARNING"
        reasons.append("ساختار متن مشکوک")
    # نقشه و جدول مهندسی نیازمند بازبینی انسانی اعداد/ستون‌ها هستند.
    if re.search(r"DWG|LENGTH|DIFF|PACKING|IRN|COLUMNS|MATERIAL|شرح|تعداد|واحد", clean, re.I):
        if status != "FAIL":
            status = "WARNING"
        reasons.append("جدول یا نقشهٔ فنی؛ صحت اعداد و ارتباط ستون‌ها تأیید نشده است")
    return {"status": status, "reasons": reasons, "characters": len(clean),
            "tokens": len(tokens), "single_line_ratio": round(singles, 3),
            "repeated_sequences": repeats, "symbol_ratio": round(symbols, 3),
            "persian_characters": len(re.findall(r"[\u0600-\u06ff]", clean)),
            "accuracy_verified": False}


def split_and_check(raw, info):
    """شناسهٔ آغاز و پایان باید دقیقاً یک بار و به ترتیب دیده شوند."""
    raw = text_only(raw)
    matches = list(MARKER_RE.finditer(raw))
    sequence = [(int(m.group(1)), m.group(2).upper()) for m in matches]
    expected = [(n, kind) for n in range(1, info['processed'] + 1) for kind in ("BEGIN", "END")]
    complete = sequence == expected
    order_valid = sequence == [item for item in expected if item in sequence]
    report = {"version": VERSION, "source": info, "coverage_verified": complete,
              "marker_order_valid": order_valid,
              "observed_markers": sequence, "pages": [],
              "limitations": ["امتیاز کیفیت، صحت اعداد و معنی متن را تضمین نمی‌کند.",
                              "تشخیص کامل زبان تصویر و معنای نقشه در این نسخه انجام نمی‌شود."]}
    segments = {}
    for number in range(1, info['processed'] + 1):
        begins = [m for m in matches if int(m.group(1)) == number and m.group(2).upper() == "BEGIN"]
        ends = [m for m in matches if int(m.group(1)) == number and m.group(2).upper() == "END"]
        if len(begins) == len(ends) == 1 and begins[0].end() < ends[0].start():
            segment = raw[begins[0].end():ends[0].start()].strip()
            segments[number] = segment
            result = evaluate_text(segment)
            anchors = info.get('pages', [{}] * info['processed'])[number-1].get('source_anchors', [])
            check_anchors(result, segment, anchors)
            result['boundaries_verified'] = True
            source_page = info.get('pages', [{}] * info['processed'])[number-1]
            if source_page.get('scan_like'):
                if result['status'] == 'PASS':
                    result['status'] = 'WARNING'
                result['reasons'].append('صفحهٔ اسکن‌شده؛ کامل بودن متن و داده‌های تصویری نیازمند بازبینی است')
            original_length = source_page.get('source_character_count', 0)
            if original_length > 300 and result['characters'] < original_length * 0.4:
                if result['status'] != 'FAIL':
                    result['status'] = 'WARNING'
                result['reasons'].append('متن OCR نسبت به لایهٔ منبع بسیار کم است؛ احتمال حذف محتوا')
        else:
            result = evaluate_text("")
            result['reasons'] = ["مرز صفحه شناسایی نشد؛ پوشش صفحه تأیید نشده است"]
            result['boundaries_verified'] = False
        result['number'] = number
        if not order_valid:
            result['status'] = "FAIL"
            result['reasons'].append("پوشش یا ترتیب کل سند قابل تأیید نیست")
        report['pages'].append(result)
    update_status(report)
    return segments, report


def update_status(report):
    statuses = [page['status'] for page in report['pages']]
    report['status'] = "FAIL" if "FAIL" in statuses else "WARNING" if "WARNING" in statuses else "PASS"
    # تأیید کاربر: پیوست توضیح تکمیلی ایمیل است؛ هشدار جدول مانع استفاده نیست.
    report['rag_policy'] = RAG_POLICY
    report['rag_usable_pages'] = [page['number'] for page in report['pages']
                                  if page['status'] in ('PASS', 'WARNING') and page['characters'] > 0]
    report['rag_ready'] = bool(report['rag_usable_pages'])


def save_report(path, report):
    path = Path(path)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = ["# گزارش کنترل کیفیت OCR", "", f"وضعیت سند: {report['status']}",
            f"پوشش صفحات تأیید شده: {report['coverage_verified']}", "",
            "> این گزارش صحت اعداد و ساختار جدول را تضمین نمی‌کند.", "",
            "| صفحه | وضعیت | علت |", "| --- | --- | --- |"]
    for page in report['pages']:
        rows.append(f"| {page['number']} | {page['status']} | {'؛ '.join(page['reasons']) or 'خرابی واضح پیدا نشد'} |")
    path.with_suffix('.md').write_text('\n'.join(rows), encoding="utf-8")

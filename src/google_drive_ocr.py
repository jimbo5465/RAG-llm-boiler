# -*- coding: utf-8 -*-
"""
ماژول و اسکریپت تبدیل جامع PDF و تصاویر اسکن‌شده به Markdown با استفاده از Google Drive OCR API
- تبدیل تمام PDFها (دیجیتال و اسکن) به متن روان و بدون به‌هم‌ریختگی
- OCR تصاویر نامه‌ها (.jpg, .png, .jpeg) و فیلتر خودکار تصاویر بدون متن/نویز
- بازسازی خودکار ساختار جداول مهندسی (table_postprocessor)
"""
import os
import io
import time
import glob
import re
import sys
import json
import random
import socket
import ssl
import http.client
import httplib2
from googleapiclient.errors import HttpError
from pathlib import Path
import pymupdf as fitz
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload, MediaIoBaseUpload
from project_paths import PROJECT_ROOT
import pdf_ocr_quality as pdf_quality

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

def get_app_base_dirs():
    """یافتن تمام مسیرهای معتبر برنامه و ریشه پروژه"""
    dirs = []
    # ۱. مسیر اسکریپت جاری
    dirs.append(os.path.dirname(os.path.abspath(__file__)))
    # ۲. مسیر فایل اجرایی در صورت اجرای باینری (PyInstaller)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        dirs.append(exe_dir)
        dirs.append(os.path.abspath(os.path.join(exe_dir, "..")))
        dirs.append(os.path.abspath(os.path.join(exe_dir, "..", "..")))
    # ۳. ریشه قابل‌حمل پروژه
    dirs.append(PROJECT_ROOT)
    # ۴. مسیر جاری
    dirs.append(os.getcwd())
    # حذف موارد تکراری با حفظ ترتیب
    uniq_dirs = []
    for d in dirs:
        if d and os.path.isdir(d) and d not in uniq_dirs:
            uniq_dirs.append(d)
    return uniq_dirs

def find_file_in_dirs(filename):
    for d in get_app_base_dirs():
        candidate = os.path.join(d, filename)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(get_app_base_dirs()[0], filename)

BASE_DIR = PROJECT_ROOT
CREDENTIALS_FILE = find_file_in_dirs("credentials.json")
TOKEN_FILE = find_file_in_dirs("token.json")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
DOC_EXTENSIONS = {".pdf", ".doc"}
ALL_SUPPORTED_OCR_EXTENSIONS = DOC_EXTENSIONS.union(IMAGE_EXTENSIONS)

PDF_FULL_PROCESS_MAX_MB = 10
PDF_FULL_PROCESS_MAX_PAGES = 15
PDF_PREVIEW_PAGE_LIMIT = 5


def transient_network_error(error):
    if isinstance(error, ssl.SSLCertVerificationError):
        return False
    if isinstance(error, HttpError):
        status = int(error.resp.status)
        if status == 403:
            try:
                details = json.loads(error.content.decode('utf-8'))
                return any(item.get('reason') in ('rateLimitExceeded', 'userRateLimitExceeded')
                           for item in details.get('error', {}).get('errors', []))
            except (ValueError, AttributeError):
                return False
        return status in (408, 429, 500, 502, 503, 504)
    if isinstance(error, (ConnectionError, TimeoutError, socket.gaierror,
                          ssl.SSLError, http.client.RemoteDisconnected,
                          http.client.IncompleteRead, httplib2.ServerNotFoundError)):
        return True
    return isinstance(error, OSError) and (
        getattr(error, 'winerror', None) in (10053, 10054, 10060, 10061)
        or error.errno in (54, 104, 110, 10053, 10054, 10060, 10061))


def network_retry(action, *, label, log_func=print, metrics=None, max_attempts=4):
    """تلاش مجدد محدود برای خطاهای موقت؛ خطای دسترسی و فایل فوراً گزارش می‌شود."""
    for attempt in range(1, max_attempts + 1):
        try:
            return action()
        except Exception as error:
            if not transient_network_error(error):
                raise
            if attempt == max_attempts:
                log_func(f'    [!] {label}: پس از {max_attempts} تلاش همچنان ناموفق است: {error}')
                raise
            delay = 2 ** attempt + random.uniform(0, 1)
            if isinstance(error, HttpError):
                try:
                    delay = max(delay, float(error.resp.get('retry-after', 0)))
                except (TypeError, ValueError):
                    pass
            delay = min(delay, 60)
            if metrics is not None:
                metrics['network_retries'] = metrics.get('network_retries', 0) + 1
            log_func(f'    [i] {label}: خطای موقت؛ تلاش {attempt + 1}/{max_attempts} پس از {delay:.1f} ثانیه: {error}')
            time.sleep(delay)


def get_drive_service():
    """احراز هویت و دریافت کلاینت Google Drive API"""
    global CREDENTIALS_FILE, TOKEN_FILE
    CREDENTIALS_FILE = find_file_in_dirs("credentials.json")
    TOKEN_FILE = find_file_in_dirs("token.json")

    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except Exception:
                refreshed = False

        if not refreshed:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"فایل credentials.json در هیچ‌کدام از مسیرها یافت نشد: {get_app_base_dirs()}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def is_noise_or_photo_image(file_name):
    """
    تشخیص تصاویر محیطی/تجهیزات و لوگوها جهت عدم ارسال به Google OCR
    """
    fn_lower = file_name.lower()
    # پیشوندهای متداول عکس‌های دوربین/موبایل
    photo_prefixes = ("img_", "img-", "dsc_", "2024", "2023", "2025", "pic_")
    if any(fn_lower.startswith(p) or f"_{p}" in fn_lower for p in photo_prefixes):
        return True
    
    # کلمات کلیدی لوگو، امضا، ایموجی و تصاویر کوچک
    noise_keywords = ("logo", "signature", "avatar", "outlookemoji", "image00")
    if any(k in fn_lower for k in noise_keywords):
        return True

    return False


def convert_gdoc_to_markdown(doc_obj):
    """
    تبدیل مستقیم ساختار سند Google Doc به Markdown با استخراج دقیق جداول
    """
    body = doc_obj.get("body", {})
    content = body.get("content", [])
    md_parts = []

    for elem in content:
        if "paragraph" in elem:
            p = elem["paragraph"]
            style = p.get("paragraphStyle", {}).get("namedStyleType", "")
            bullet = p.get("bullet")
            p_text = ""
            for pe in p.get("elements", []):
                tr = pe.get("textRun", {})
                t = tr.get("content", "")
                p_text += t

            p_text = p_text.rstrip("\r\n")
            if not p_text.strip():
                continue

            if bullet:
                md_parts.append(f"- {p_text.strip()}")
            elif style == "TITLE":
                md_parts.append(f"# {p_text.strip()}")
            elif style == "HEADING_1":
                md_parts.append(f"# {p_text.strip()}")
            elif style == "HEADING_2":
                md_parts.append(f"## {p_text.strip()}")
            elif style == "HEADING_3":
                md_parts.append(f"### {p_text.strip()}")
            else:
                md_parts.append(p_text.strip())

        elif "table" in elem:
            tbl = elem["table"]
            rows = tbl.get("tableRows", [])
            if not rows:
                continue

            table_rows = []
            max_cols = 0
            for r in rows:
                cells = r.get("tableCells", [])
                max_cols = max(max_cols, len(cells))
                row_vals = []
                for c in cells:
                    cell_text = ""
                    for ce in c.get("content", []):
                        if "paragraph" in ce:
                            for pe in ce["paragraph"].get("elements", []):
                                cell_text += pe.get("textRun", {}).get("content", "")
                    cell_clean = re.sub(r"[\r\n]+", " ", cell_text).strip()
                    cell_clean = cell_clean.replace("|", "\\|")
                    row_vals.append(cell_clean)
                table_rows.append(row_vals)

            if table_rows and max_cols > 0:
                md_table_lines = []
                header = table_rows[0] + [""] * (max_cols - len(table_rows[0]))
                md_table_lines.append("| " + " | ".join(header) + " |")
                md_table_lines.append("| " + " | ".join([":---"] * max_cols) + " |")
                for r in table_rows[1:]:
                    padded = r + [""] * (max_cols - len(r))
                    md_table_lines.append("| " + " | ".join(padded) + " |")
                md_parts.append("\n" + "\n".join(md_table_lines) + "\n")

    return "\n\n".join(md_parts)


def ocr_single_media_gdrive(media, file_name, mime_type, service, *,
                           export_only=False, metrics=None, log_func=None):
    """آپلود یک مدیا به عنوان Google Doc، استخراج ساختاریافته جداول و پاک‌سازی فایل از گوگل"""
    file_metadata = {
        "name": file_name,
        "mimeType": "application/vnd.google-apps.document",
    }
    metrics = metrics if metrics is not None else {}
    retry_log = log_func or print
    def retry(stage, action):
        return network_retry(action, label=f'{file_name} — {stage}',
                             log_func=retry_log, metrics=metrics)
    def measured(stage, action):
        started = time.monotonic()
        try:
            return action()
        finally:
            elapsed = round(time.monotonic() - started, 3)
            metrics[stage] = metrics.get(stage, 0) + elapsed
            if log_func:
                log_func(f'    {file_name}: {stage} = {elapsed:.1f} ثانیه')

    # درخواست upload را حفظ می‌کنیم تا resumable از همان نشست ادامه یابد.
    upload_request = service.files().create(body=file_metadata, media_body=media, fields="id")
    uploaded_file = measured('upload_convert_seconds', lambda:
        retry('ارسال و تبدیل', upload_request.execute))
    file_id = uploaded_file.get("id")

    try:
        # ۱. تلاش برای استخراج مستقیم ساختار و جداول از Google Docs API
        try:
            if export_only:
                raise LookupError('مسیر آزمایشی دریافت مستقیم Markdown')
            docs_service = build("docs", "v1", credentials=service._http.credentials)
            try:
                doc_obj = measured('docs_structure_seconds', lambda:
                    retry('دریافت ساختار', lambda: docs_service.documents().get(documentId=file_id).execute()))
            finally:
                docs_service.close()
            doc_content = doc_obj.get("body", {}).get("content", [])
            has_table = any("table" in e for e in doc_content)
            if has_table:
                structured_md = convert_gdoc_to_markdown(doc_obj)
                if structured_md and len(structured_md.strip()) > 30:
                    return structured_md
        except Exception:
            pass  # در صورت عدم دسترسی، استفاده از متد اکسپورت مارک‌داون

        # ۲. متد اکسپورت مستقیم Markdown
        request = service.files().export_media(
            fileId=file_id,
            mimeType="text/markdown",
        )
        raw_md_bytes = io.BytesIO()
        downloader = MediaIoBaseDownload(raw_md_bytes, request)
        done = False
        started = time.monotonic()
        try:
            while not done:
                status, done = retry('دریافت متن', downloader.next_chunk)
        finally:
            metrics['export_seconds'] = round(time.monotonic() - started, 3)
            if log_func:
                log_func(f"    {file_name}: export_seconds = {metrics['export_seconds']:.1f} ثانیه")
        raw_text = raw_md_bytes.getvalue().decode("utf-8", errors="ignore")
        return raw_text
    finally:
        try:
            measured('delete_seconds', lambda:
                retry('پاک‌سازی فایل موقت', lambda: service.files().delete(fileId=file_id).execute()))
        except Exception as exc:
            metrics['cleanup_error'] = str(exc)
            if log_func:
                log_func(f'    هشدار پاک‌سازی گوگل {file_name}: {exc}')


def is_text_garbled_scanner(text):
    """تشخیص متن‌های نامفهوم و خراب دستگاه‌های اسکنر اداری"""
    if not text or not text.strip():
        return True
    persian_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    # اگر متن فارسی تقریباً صفر باشد اما علائم عجیب و حروف تصادفی اسکنر داشته باشد
    if persian_chars < 15 and len(text.strip()) > 40:
        if any(w in text for w in ["Mtttk", "iKt", "ljIAxullC", "OjL)_wj", "liju+ip"]):
            return True
        symbol_count = sum(1 for c in text if c in "^~*_\\/<>{}[]|;")
        if symbol_count / len(text.strip()) > 0.15 and persian_chars < 5:
            return True
    return False


def ocr_pdf_by_rasterization(pdf_path, service, log_func=print):
    """
    رندر صفحات اسناد اسکن‌شده کوتاه به تصویر جهت رفع متن مخرب اسکنر
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    page_texts = []

    for page_num in range(total_pages):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("jpeg")

        media = MediaIoBaseUpload(io.BytesIO(img_bytes), mimetype="image/jpeg", resumable=True)
        temp_name = f"page_{page_num + 1}_{os.path.basename(pdf_path)}"

        try:
            page_raw = ocr_single_media_gdrive(media, temp_name, "image/jpeg", service)
            page_raw_clean = re.sub(r'\[image\d+\]:\s*<data:image/[^>]+>', '', page_raw)
            page_raw_clean = re.sub(r'!\[\]\[image\d+\]', '', page_raw_clean).strip()
            
            if page_raw_clean:
                if total_pages > 1:
                    page_texts.append(f"## صفحه {page_num + 1}\n\n{page_raw_clean}")
                else:
                    page_texts.append(page_raw_clean)
        except Exception as e:
            log_func(f"    [!] خطا در OCR صفحه {page_num + 1}: {e}")

    doc.close()
    return "\n\n---\n\n".join(page_texts)


def convert_file_to_md_gdrive(file_path, output_md_path, service=None, parent_emails=None,
                              log_func=print, rotation_overrides=None, max_page_retries=2,
                              reuse_raw=False, debug_errors=False, speed_engine=None,
                              filter_image_names=True):
    """خروجی کم‌حجم؛ حذف واسط‌ها حتی پس از خطا، با عیب‌یابی اختیاری."""
    output = Path(output_md_path)
    diagnostics = pdf_quality.diagnostics_path(output)
    is_pdf = Path(file_path).suffix.lower() == '.pdf'
    if is_pdf and Path(file_path).resolve() in {
            output.resolve(), output.with_suffix('.prepared.pdf').resolve(),
            output.with_suffix('.preparation.json').resolve()}:
        raise ValueError('مسیر اصل پیوست با مسیر خروجی یا فایل واسط یکسان است.')
    failed = True
    problematic = True
    try:
        result = _convert_file_to_md_gdrive(
            file_path, output_md_path, service, parent_emails, log_func,
            rotation_overrides, max_page_retries, reuse_raw, speed_engine, filter_image_names)
        failed = not result
        if is_pdf and (diagnostics / 'quality.json').exists():
            report = json.loads((diagnostics / 'quality.json').read_text(encoding='utf-8'))
            problematic = report['status'] == 'FAIL' or report.get('retry_requests', 0) > 0
            summary_path = output.parent / 'ocr_quality_report.json'
            summary = json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else {}
            summary[output.name] = {
                'status': report['status'], 'rag_ready': report['rag_ready'],
                'rag_policy': pdf_quality.RAG_POLICY,
                'total': report['source']['total'], 'processed': report['source']['processed'],
                'partial': report['source']['partial'],
                'usable_pages': report['rag_usable_pages'],
                'failed_pages': [p['number'] for p in report['pages'] if p['status'] == 'FAIL'],
                'requests': report.get('requests', 0),
                'local_pages': report.get('local_pages', []),
                'google_pages': report.get('google_pages', []),
                'cache_pages': report.get('cache_pages', []),
                'retry_requests': report.get('retry_requests', 0),
                'upload_bytes': report.get('upload_bytes', 0),
                'page_methods': {str(p['number']): p.get('method', 'google') for p in report['pages']},
                'page_timings': {str(p['number']): p['timings'] for p in report['pages'] if p.get('timings')},
                'batch_ids': {str(p['number']): p['batch_id'] for p in report['pages'] if p.get('batch_id')},
                'fallback_pages': [p['number'] for p in report['pages'] if p.get('fallback')],
                'route_reasons': {str(p['number']): p.get('route_reasons', []) for p in report['pages']
                                 if p.get('route_reasons')},
                'errors': {str(p['number']): p['error'] for p in report['pages'] if p.get('error')},
            }
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        return result
    finally:
        if is_pdf:
            # فقط فایل‌های واسط اختصاصی همین خروجی، نه اصل پیوست.
            for path in (output.with_suffix('.prepared.pdf'), output.with_suffix('.preparation.json')):
                if path.exists():
                    path.unlink()
                    log_func(f'    فایل واسط حذف شد: {path.name}')
            if diagnostics.exists() and not (debug_errors and (failed or problematic)):
                # بدون دنبال‌کردن symlink/junction و بدون حذف مسیر گسترده.
                import stat
                paths = [diagnostics, *diagnostics.rglob('*')]
                if any(p.is_symlink() or getattr(p.lstat(), 'st_file_attributes', 0) &
                       stat.FILE_ATTRIBUTE_REPARSE_POINT for p in paths):
                    raise RuntimeError('پاک‌سازی عیب‌یابی: مسیر لینک‌دار است؛ حذف انجام نشد.')
                for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
                    if path.is_file():
                        path.unlink()
                    else:
                        path.rmdir()
                if diagnostics.parent.exists() and not any(diagnostics.parent.iterdir()):
                    diagnostics.parent.rmdir()
            elif diagnostics.exists():
                log_func(f'    عیب‌یابی مورد مشکل‌دار نگهداری شد: {diagnostics}')


def _convert_file_to_md_gdrive(file_path, output_md_path, service=None, parent_emails=None,
                              log_func=print, rotation_overrides=None, max_page_retries=2,
                              reuse_raw=False, speed_engine=None, filter_image_names=True):
    """
    تبدیل فایل PDF یا تصویر به Markdown از طریق Google Drive OCR با سرعت بالا و پشتیبانی از مانیفست
    """
    if Path(file_path).suffix.lower() == '.pdf':
        from pdf_page_pipeline import convert_pdf
        return convert_pdf(file_path, output_md_path, service=service,
                           service_factory=get_drive_service, ocr_media=ocr_single_media_gdrive,
                           parent_emails=parent_emails, log_func=log_func,
                           rotation_overrides=rotation_overrides, max_page_retries=max_page_retries,
                           reuse_raw=reuse_raw, speed_engine=speed_engine)
    if service is None:
        service = get_drive_service()

    file_name = os.path.basename(file_path)
    ext = os.path.splitext(file_name)[1].lower()
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

    if ext != ".pdf" and file_size_mb > 25:
        raise ValueError(f"حجم فایل ({file_size_mb:.1f} MB) از سقف ۲۵ مگابایت Google Docs بیشتر است.")

    # ۱. پیش‌فیلتر تصاویر محیطی / لوگوها
    if filter_image_names and ext in IMAGE_EXTENSIONS and is_noise_or_photo_image(file_name):
        return False

    raw_text = ""
    pdf_info = None
    quality_report = None

    # ۲. پردازش PDF بر اساس ساختار و سرعت بهینه
    if ext == ".pdf":
        out_path = Path(output_md_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        prepared = out_path.with_suffix('.prepared.pdf')
        pdf_info = pdf_quality.prepare_pdf(file_path, prepared, rotation_overrides=rotation_overrides,
                                           log_func=log_func)
        out_path.with_suffix('.preparation.json').write_text(
            json.dumps(pdf_info, ensure_ascii=False, indent=2), encoding='utf-8')
        log_func(f"    [i] {pdf_info['method']}: {pdf_info['processed']} از {pdf_info['total']} صفحه؛ "
                 f"حجم ارسال {pdf_info['upload_bytes'] / 1024 / 1024:.2f} MB")
        # متن خام خارج از مسیر نهایی Markdown نگهداری می‌شود تا وارد RAG نشود.
        diagnostics = out_path.parent / '_ocr_diagnostics' / out_path.stem
        diagnostics.mkdir(parents=True, exist_ok=True)
        if reuse_raw:
            raw_text = (diagnostics / 'google_raw.txt').read_text(encoding='utf-8')
        else:
            media = MediaFileUpload(str(prepared), mimetype="application/pdf", resumable=True)
            log_func(f"    ارسال به Google OCR: {file_name}؛ منتظر پاسخ گوگل...")
            try:
                raw_text = ocr_single_media_gdrive(media, file_name, "application/pdf", service)
            finally:
                media.stream().close()
            (diagnostics / 'google_raw.txt').write_text(raw_text, encoding='utf-8')
            log_func(f"    پاسخ گوگل دریافت شد: {len(raw_text)} کاراکتر؛ بررسی صفحات...")
        segments, quality_report = pdf_quality.split_and_check(raw_text, pdf_info)
        for entry in quality_report['pages']:
            log_func(f"    نتیجهٔ اولیه صفحه {entry['number']}: {entry['status']}، "
                     f"{entry['characters']} کاراکتر؛ {'؛ '.join(entry['reasons']) or 'خرابی واضح پیدا نشد'}")
        quality_report['requests'] = 0 if reuse_raw else 1
        quality_report['initial_response_reused'] = reuse_raw
        quality_report['retry_limit'] = max_page_retries
        failures = [entry for entry in quality_report['pages'] if entry['status'] == 'FAIL']
        with fitz.open(file_path) as source:
            retry_requests = 0
            for entry in failures:
                number = entry['number']
                retry_path = diagnostics / f'retry_page_{number}.txt'
                cached_retry = reuse_raw and retry_path.exists()
                if not cached_retry and retry_requests >= max(0, max_page_retries):
                    entry['reasons'].append('سقف تلاش مجدد این اجرا رسید؛ نیازمند بررسی دستی')
                    log_func(f"    صفحه {number}: تلاش مجدد انجام نشد؛ سقف {max_page_retries} تلاش رسید")
                    continue
                rotation = pdf_info['pages'][number-1]['rotation_ccw']
                image = pdf_quality.render_page(source[number-1], number, dpi=400,
                                               rotation=rotation, markers=False)
                retry_media = MediaIoBaseUpload(io.BytesIO(pdf_quality.jpeg_bytes(image)),
                                               mimetype='image/jpeg', resumable=True)
                log_func(f"    [i] {'بازبینی نتیجهٔ ذخیره‌شده' if cached_retry else 'تلاش مجدد مستقل'} صفحه {number} در ۴۰۰ DPI")
                try:
                    if cached_retry:
                        retry_text = retry_path.read_text(encoding='utf-8')
                        entry['retry_response_reused'] = True
                    else:
                        retry_requests += 1
                        quality_report['requests'] += 1
                        retry_text = ocr_single_media_gdrive(retry_media, f'retry_page_{number}_{file_name}',
                                                            'image/jpeg', service)
                        retry_path.write_text(retry_text, encoding='utf-8')
                    candidate = pdf_quality.evaluate_text(retry_text)
                    pdf_quality.check_anchors(candidate, retry_text, pdf_info['pages'][number-1]['source_anchors'])
                    entry['retry_status'] = candidate['status']
                    log_func(f"    پاسخ تلاش مجدد صفحه {number}: {candidate['status']}، "
                             f"{candidate['characters']} کاراکتر")
                    if candidate['status'] != 'FAIL':
                        entry.update(candidate, recovered_by_retry=True)
                        segments[number] = pdf_quality.text_only(retry_text)
                except Exception as exc:
                    entry['retry_error'] = str(exc)
                    log_func(f"    [!] تلاش مجدد صفحه {number} ناموفق: {exc}")
                finally:
                    retry_media.stream().close()
        # پوشش سند فقط وقتی تأیید می‌شود که همهٔ مرزها معتبر یا صفحات مستقل بازیابی شده باشند.
        if not quality_report['coverage_verified']:
            quality_report['coverage_verified'] = all(
                entry.get('recovered_by_retry', False) or (
                    quality_report['marker_order_valid'] and entry.get('boundaries_verified', False))
                for entry in quality_report['pages'])
        pdf_quality.update_status(quality_report)
        log_func(f"    نتیجهٔ نهایی: {quality_report['status']}؛ صفحات قابل استفاده "
                 f"{quality_report['rag_usable_pages']}؛ درخواست‌های گوگل {quality_report['requests']}")
        pdf_quality.save_report(diagnostics / 'quality.json', quality_report)
        sections = []
        for entry in quality_report['pages']:
            number = entry['number']
            if entry['status'] == 'FAIL':
                body = '> متن این صفحه تأیید نشده است؛ به اصل پیوست مراجعه کنید.'
            else:
                body = segments.get(number, '')
            sections.append(f"## صفحه {number}\n\n{body}")
        raw_text = '\n\n---\n\n'.join(sections)

    elif ext in (".jpg", ".jpeg"):
        media = MediaFileUpload(file_path, mimetype="image/jpeg", resumable=True)
        try:
            raw_text = ocr_single_media_gdrive(media, file_name, "image/jpeg", service, log_func=log_func)
        finally:
            media.stream().close()
    elif ext == ".png":
        media = MediaFileUpload(file_path, mimetype="image/png", resumable=True)
        try:
            raw_text = ocr_single_media_gdrive(media, file_name, "image/png", service, log_func=log_func)
        finally:
            media.stream().close()
    elif ext == ".doc":
        media = MediaFileUpload(file_path, mimetype="application/msword", resumable=True)
        try:
            raw_text = ocr_single_media_gdrive(media, file_name, "application/msword", service, log_func=log_func)
        finally:
            media.stream().close()
    else:
        media = MediaFileUpload(file_path, mimetype="application/octet-stream", resumable=True)
        try:
            raw_text = ocr_single_media_gdrive(media, file_name, "application/octet-stream", service, log_func=log_func)
        finally:
            media.stream().close()

    if not raw_text or not raw_text.strip():
        return False

    # ۳. اجرای لایه پس‌پردازش و بازسازی ساختار جداول
    if ext == '.pdf':
        # بازسازی حدسی جدول نباید داده‌ای به متن OCR اضافه کند.
        processed_text = raw_text
    else:
        try:
            import table_postprocessor
            processed_text = table_postprocessor.detect_and_format_tables(raw_text)
        except Exception:
            processed_text = raw_text

    # ۴. فیلتر نویز تصاویر: اگر متن مفید کمتر از ۲۰۰ کاراکتر بود فایل ساخته نشود
    clean_text_check = re.sub(r'\[image\d+\]:\s*<data:image/[^>]+>', '', processed_text)
    clean_text_check = re.sub(r'!\[\]\[image\d+\]', '', clean_text_check)
    clean_text_check = re.sub(r'[\s\-_\|\*\#]+', '', clean_text_check).strip()

    if ext in IMAGE_EXTENSIONS and len(clean_text_check) < 200:
        return False

    # ۵. ساخت فرانت‌متر استاندارد با درج والدین
    fm_lines = [
        "---",
        f"پیوست: {file_name}",
        "نوع: متن پیوست",
    ]
    if pdf_info:
        fm_lines.extend([
            f"پوشش: صفحات ۱ تا {pdf_info['processed']} از {pdf_info['total']} صفحه",
        ])
        fm_lines.extend([
            f"فایل_اصلی: {os.path.relpath(os.path.abspath(file_path), PROJECT_ROOT)}",
        ])
    if parent_emails:
        fm_lines.append("ایمیل‌های مرتبط (والد):")
        for p in parent_emails:
            fm_lines.append(f"  - {p}")
    else:
        fm_lines.append("ایمیل‌های مرتبط (والد): نامشخص")
    fm_lines.append("---")

    warning = ""
    if pdf_info and pdf_info['partial']:
        warning = (
            f"> هشدار: این PDF دارای {pdf_info['total']} صفحه است؛ فقط صفحات ۱ تا "
            f"{pdf_info['processed']} پردازش شده‌اند. این خروجی متن کامل سند نیست. "
            f"علت: {pdf_info['reason']}.\n\n"
        )
    if quality_report and quality_report['status'] == 'FAIL':
        failed_pages = '، '.join(str(p['number']) for p in quality_report['pages'] if p['status'] == 'FAIL')
        warning += f"> خروجی ناقص است؛ متن صفحات {failed_pages} تأیید نشده است.\n\n"
    if ext in IMAGE_EXTENSIONS:
        # فقط پس از کنترل متن اصلی؛ هشدار نباید فیلتر نویز را دور بزند.
        warning += pdf_quality.OCR_SOURCE_WARNING + '\n\n'
    final_content = "\n".join(fm_lines) + "\n\n" + warning + processed_text.strip()

    out_parent_dir = os.path.dirname(output_md_path)
    if out_parent_dir:
        os.makedirs(out_parent_dir, exist_ok=True)
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write(final_content)

    return True


def worker_service_factory():
    """ورود/refresh روی main؛ اتصال و نسخهٔ مستقل credentials برای هر worker."""
    base = get_drive_service()
    try:
        info = json.loads(base._http.credentials.to_json())
    finally:
        base.close()
    def factory():
        creds = Credentials.from_authorized_user_info(info, SCOPES)
        client = build('drive', 'v3', credentials=creds)
        # زمان انتظار نامحدود نداشته باشیم؛ OCRهای قبلی تا حدود ۲۰۹ ثانیه بوده‌اند.
        if hasattr(client._http, 'http'):
            client._http.http.timeout = 300
        return client
    return factory


def batch_convert_all(input_dir, output_dir, force_overwrite=False, log_func=print, attachment_manifest=None,
                      debug_errors=False, speed_options=None):
    from ocr_speed import SpeedEngine, SpeedOptions
    options = speed_options or SpeedOptions()
    # کنترل فایل/صفحهٔ تکراری در تمام مجموعه، حتی میان پیوست‌های PDF مختلف.
    sources = [path for path in sorted(Path(input_dir).glob('*'))
               if path.is_file() and path.suffix.lower() == '.pdf'
               and (force_overwrite or not (Path(output_dir) / (path.stem + '.md')).exists())]
    engine = SpeedEngine(options, None, ocr_single_media_gdrive, log_func=log_func)
    try:
        engine.collect(sources)
        if engine.jobs:
            engine.service_factory = worker_service_factory()
        engine.run()
        stats = _batch_convert_all(input_dir, output_dir, force_overwrite, log_func,
                                   attachment_manifest, debug_errors, engine)
        stats['performance'] = engine.stats
        log_func(f"[+] سرعت OCR: {engine.stats['requests']} درخواست واقعی؛ "
                 f"{engine.stats['cache_hits']} صفحه از حافظه؛ {engine.stats['duplicate_pages']} تکراری؛ "
                 f"{engine.stats['fallback_pages']} بازگشت به ارسال مستقل")
        return stats
    finally:
        engine.close()


def _batch_convert_all(input_dir, output_dir, force_overwrite=False, log_func=print, attachment_manifest=None,
                      debug_errors=False, speed_engine=None):
    """تبدیل تمام PDFها و تصاویر اسکن‌شده پیوست‌ها به Markdown با پشتیبانی از مانیفست اشتراک"""
    import json
    if attachment_manifest is None:
        manifest_path = os.path.join(os.path.dirname(input_dir), "attachment_manifest.json")
        if not os.path.exists(manifest_path):
            manifest_path = os.path.join(input_dir, "attachment_manifest.json")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as mf:
                    attachment_manifest = json.load(mf)
            except Exception:
                attachment_manifest = {}
        else:
            attachment_manifest = {}

    all_files = glob.glob(os.path.join(input_dir, "*.*"))
    target_files = [
        f for f in all_files 
        if os.path.splitext(f)[1].lower() in ALL_SUPPORTED_OCR_EXTENSIONS
    ]

    if not target_files:
        log_func("[-] هیچ فایل PDF یا تصویری در مسیر پیوست‌ها یافت نشد.")
        return {"eligible": 0, "converted": 0, "existing": 0, "digital": 0, "noise": 0, "errors": 0}

    log_func(f"[+] تعداد کل اسناد و تصاویر جهت بررسی OCR: {len(target_files)}")
    service = None

    success_count = 0
    skipped_no_text = 0
    existing_count = 0
    digital_count = 0
    error_count = 0

    for idx, fp in enumerate(target_files, 1):
        rel_name = os.path.splitext(os.path.basename(fp))[0]
        ext = os.path.splitext(fp)[1].lower()
        file_name = os.path.basename(fp)
        out_md_path = os.path.join(output_dir, f"{rel_name}.md")

        # پیش‌فیلتر تصاویر محیطی
        if ext in IMAGE_EXTENSIONS and is_noise_or_photo_image(file_name):
            skipped_no_text += 1
            log_func(f"[{idx}/{len(target_files)}] کنار گذاشته شد با فیلتر نام تصویر: {file_name}")
            continue

        if not force_overwrite and os.path.exists(out_md_path):
            log_func(f"[{idx}/{len(target_files)}] قبلاً تبدیل شده: {file_name}")
            existing_count += 1
            continue

        # PDF باید از مسیر کنترل کیفیت ترکیبی بگذرد؛ متن محلی قدیمیِ بررسی‌نشده کافی نیست.
        digital_md_path = os.path.join(os.path.dirname(output_dir), "attachments_text", f"{rel_name}.md")
        if ext != ".pdf" and not force_overwrite and os.path.exists(digital_md_path):
            log_func(f"[{idx}/{len(target_files)}] قبلاً به صورت دیجیتال استخراج شده (بدون نیاز به OCR): {file_name}")
            digital_count += 1
            continue

        log_func(f"[{idx}/{len(target_files)}] در حال بررسی محلی/OCR: {file_name}...")
        parent_emails = attachment_manifest.get(file_name, [])

        try:
            if ext != '.pdf' and service is None:
                service = get_drive_service()
            res = convert_file_to_md_gdrive(
                fp,
                out_md_path,
                service=service,
                parent_emails=parent_emails,
                log_func=log_func,
                debug_errors=debug_errors,
                speed_engine=speed_engine if ext == '.pdf' else None,
            )
            if res:
                log_func(f"  -> ذخیره شد: {os.path.basename(out_md_path)}")
                success_count += 1
                if ext == '.pdf':
                    quality_path = Path(output_dir) / 'ocr_quality_report.json'
                    if quality_path.exists():
                        pdf_report = json.loads(quality_path.read_text(encoding='utf-8')).get(Path(out_md_path).name, {})
                        if not pdf_report.get('google_pages'):
                            digital_count += 1
                        if pdf_report.get('errors'):
                            error_count += 1
            else:
                log_func(f"  [-] تصویر فاقد متن کافی بود (فیلتر نویز شد).")
                skipped_no_text += 1
            time.sleep(1)  # پرهیز از ترافیک بالا روی API
        except Exception as e:
            error_count += 1
            log_func(f"  [!] خطا: {e}")

    log_func(f"[+] پایان پردازش ترکیبی! {success_count} فایل خروجی گرفتند؛ {digital_count} فایل با متن کاملاً محلی "
             f"({skipped_no_text} تصویر فیلتر شد).")
    return {
        "eligible": len(target_files),
        "converted": success_count,
        "existing": existing_count,
        "digital": digital_count,
        "noise": skipped_no_text,
        "errors": error_count,
    }


if __name__ == "__main__":
    import sys
    extracted_data_dir = os.path.join(BASE_DIR, "Extracted_Data")
    target_in = None
    target_out = None
    if os.path.exists(extracted_data_dir):
        subdirs = [os.path.join(extracted_data_dir, d) for d in os.listdir(extracted_data_dir) if os.path.isdir(os.path.join(extracted_data_dir, d))]
        if subdirs:
            latest_dir = subdirs[-1]
            target_in = os.path.join(latest_dir, "emails", "attachments")
            target_out = os.path.join(latest_dir, "attachments_ocr_google")

    in_folder = sys.argv[1] if len(sys.argv) > 1 else target_in
    out_folder = sys.argv[2] if len(sys.argv) > 2 else target_out

    if in_folder and out_folder:
        batch_convert_all(in_folder, out_folder)
    else:
        print("مسیر ورودی/خروجی معتبر یافت نشد.")

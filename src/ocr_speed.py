# -*- coding: utf-8 -*-
"""آزمایش سرعت OCR؛ تطابق دقیق محتوا، بستهٔ کوچک و بازگشت امن به ارسال مستقل.

SQLite فقط متن قابل‌استفاده را نگه می‌دارد؛ تصویر و PDF آماده در حافظه‌اند.
تمام دسترسی‌های PyMuPDF و SQLite روی نخ اصلی است؛ نخ‌ها فقط شبکه انجام می‌دهند.
"""
import hashlib
import io
import json
import re
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont
from googleapiclient.http import MediaIoBaseUpload

import pdf_ocr_quality as quality
from project_paths import PROJECT_ROOT

CACHE_VERSION = 'pixel300-email-first-v1'


@dataclass(frozen=True)
class SpeedOptions:
    workers: int = 1
    batch_pages: int = 1
    fast_transport: bool = False
    cache: bool = True
    batch_bytes: int = quality.RECOMMENDED_BYTES

    def __post_init__(self):
        if self.workers not in (1, 2) or not 1 <= self.batch_pages <= 5:
            raise ValueError('حداکثر دو مسیر هم‌زمان و پنج صفحه در هر بسته مجاز است.')
        if not 0 < self.batch_bytes <= quality.RECOMMENDED_BYTES:
            raise ValueError('هدف حجم بسته باید حداکثر ۲ MB باشد؛ توصیهٔ گوگل، نه سقف قطعی.')


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def digest_image(image):
    digest = hashlib.sha256(f'{CACHE_VERSION}:{image.mode}:{image.size}'.encode('ascii'))
    # اثر انگشت پیکسل‌ها، نه نام، metadata یا JPEG فشرده‌شده.
    digest.update(image.tobytes())
    return digest.hexdigest()


class TextCache:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / 'ocr_cache.sqlite3', timeout=30)
        self.db.execute('CREATE TABLE IF NOT EXISTS pages (key TEXT PRIMARY KEY, text TEXT NOT NULL, checksum TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS files (key TEXT PRIMARY KEY, pages TEXT NOT NULL)')

    def get(self, key):
        row = self.db.execute('SELECT text, checksum FROM pages WHERE key=?', (key,)).fetchone()
        if row and hashlib.sha256(row[0].encode('utf-8')).hexdigest() == row[1]:
            if quality.evaluate_text(row[0])['status'] != 'FAIL':
                return row[0]
        return None

    def put(self, key, text):
        if quality.evaluate_text(text)['status'] == 'FAIL':
            return
        checksum = hashlib.sha256(text.encode('utf-8')).hexdigest()
        self.db.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?)', (key, text, checksum))
        self.db.commit()

    def file_pages(self, key):
        row = self.db.execute('SELECT pages FROM files WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else {}

    def put_file(self, key, pages):
        self.db.execute('INSERT OR REPLACE INTO files VALUES (?,?)', (key, json.dumps(pages)))
        self.db.commit()

    def close(self):
        self.db.close()


def boundary_labels(token, number):
    return f'RAGSTART{token}PAGE{number:04d}', f'RAGEND{token}PAGE{number:04d}'


def marked_image(image, token, number):
    margin = 150
    canvas = Image.new('RGB', (image.width, image.height + margin * 2), 'white')
    canvas.paste(image, (0, margin))
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 36)
    except OSError:
        font = ImageFont.load_default(size=36)
    draw = ImageDraw.Draw(canvas)
    for label, top in zip(boundary_labels(token, number), (35, image.height + margin + 35)):
        # شناسه هیچ بخشی از محتوای اصلی را نمی‌پوشاند؛ برای صفحات باریک هم جا می‌شود.
        bounds = draw.textbbox((0, 0), label, font=font)
        fitted = font
        if bounds[2] + 80 > image.width:
            fitted = ImageFont.load_default(size=max(12, int(36 * (image.width - 80) / bounds[2])))
        draw.text((40, top), label, fill='black', font=fitted)
    return canvas


def raster_bundle(images, token):
    with fitz.open() as doc:
        for number, image in enumerate(images, 1):
            marked = marked_image(image, token, number)
            page = doc.new_page(width=marked.width * 72 / 300, height=marked.height * 72 / 300)
            page.insert_image(page.rect, stream=quality.jpeg_bytes(marked))
            marked.close()
        return doc.tobytes(garbage=4, deflate=True)


def split_response(raw, token, count):
    """هیچ تطبیق فازی یا حدس براساس شمارهٔ صفحات Google Docs مجاز نیست."""
    raw = quality.text_only(raw)
    spans = []
    for number in range(1, count + 1):
        for label in boundary_labels(token, number):
            # فقط فاصله/شکست خط بین حروف مجاز است؛ نویسهٔ غلط پذیرفته نمی‌شود.
            pattern = r'\s*'.join(re.escape(char) for char in label)
            matches = list(re.finditer(pattern, raw, re.I))
            if len(matches) != 1:
                raise ValueError('شناسهٔ مرزی حذف، خراب یا تکراری است.')
            spans.append(matches[0].span())
    if any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1)):
        raise ValueError('ترتیب شناسه‌ها یا مرز صفحات به‌هم ریخته است.')
    outside = raw[:spans[0][0]] + raw[spans[-1][1]:]
    outside += ''.join(raw[spans[i][1]:spans[i + 1][0]] for i in range(1, len(spans) - 1, 2))
    if re.sub(r'[\s#*_`\-]', '', outside):
        raise ValueError('متن خارج از مرزهای قابل‌انتساب وجود دارد.')
    return [raw[spans[i][1]:spans[i + 1][0]].strip(' \r\n#*_`') for i in range(0, len(spans), 2)]


class SpeedEngine:
    def __init__(self, options, service_factory, ocr_media, *, log_func=print,
                 cache_dir=None, max_page_retries=2):
        self.options, self.service_factory, self.ocr_media = options, service_factory, ocr_media
        self.log_lock = threading.Lock()
        def synchronized_log(message):
            with self.log_lock:
                log_func(message)
        self.log = synchronized_log
        self.cache = TextCache(cache_dir or Path(PROJECT_ROOT) / 'Extracted_Data' / '_ocr_cache') if options.cache else None
        self.max_page_retries = max_page_retries
        self.results, self.jobs, self.destinations, self.file_maps = {}, {}, {}, {}
        self.retry_counts = {}
        self.degraded = threading.Event()
        self.serial_lock, self.state_lock = threading.Lock(), threading.Lock()
        self.thread_local = threading.local()
        self.services = []
        self.stats = {'version': 'ocr-speed-v1', 'workers': options.workers,
                      'batch_pages': options.batch_pages, 'dpi': 300,
                      'fast_transport': options.fast_transport, 'requests': 0,
                      'upload_bytes': 0, 'cache_hits': 0, 'duplicate_pages': 0,
                      'fallback_pages': 0, 'calls': [], 'planning_errors': {},
                      'degraded_to_serial': False}

    @staticmethod
    def identity(source, number):
        return str(Path(source).resolve()), number

    def collect(self, sources):
        from pdf_page_pipeline import assess_local
        started = time.monotonic()
        for source in sources:
            source = Path(source)
            try:
                file_key = f'{CACHE_VERSION}:{quality.PAGE_LIMIT}:{quality.SIZE_LIMIT_MB}:{digest_file(source)}'
                known = self.cache.file_pages(file_key) if self.cache else {}
                page_map = {}
                with fitz.open(source) as doc:
                    if not len(doc) or doc.is_encrypted:
                        raise ValueError('PDF خالی یا رمزگذاری‌شده است.')
                    count = min(quality.PREVIEW_PAGES, len(doc)) if len(doc) > quality.PAGE_LIMIT or source.stat().st_size > quality.SIZE_LIMIT_MB * 1024**2 else len(doc)
                    for index in range(count):
                        _, local = assess_local(doc[index])
                        if not local['needs_ocr']:
                            continue
                        number = index + 1
                        key = known.get(str(number))
                        text = self.cache.get(key) if key and self.cache else None
                        if text is None:
                            rotation, _, _ = quality.orientation_hint(doc[index])
                            image = quality.render_page(doc[index], number, dpi=300, rotation=rotation, markers=False)
                            try:
                                key = digest_image(image)
                                size = len(quality.jpeg_bytes(image))
                            finally:
                                image.close()
                            text = self.cache.get(key) if self.cache else None
                        else:
                            size, rotation = 0, 0
                        page_map[str(number)] = key
                        identity = self.identity(source, number)
                        if text is not None:
                            self.results[identity] = {'text': text, 'method': 'cache', 'requests': 0, 'upload_bytes': 0}
                            self.stats['cache_hits'] += 1
                            self.log(f'    حافظهٔ OCR: {source.name} صفحه {number}؛ بدون ارسال')
                            continue
                        self.destinations.setdefault(key, []).append(identity)
                        if key in self.jobs:
                            self.stats['duplicate_pages'] += 1
                            self.log(f'    صفحهٔ تکراری در همین اجرا: {source.name} صفحه {number}')
                            continue
                        self.jobs[key] = {'key': key, 'source': str(source), 'number': number,
                                          'rotation': rotation, 'size': size,
                                          'anchors': quality.source_anchors(doc[index])}
                self.file_maps[file_key] = page_map
            except Exception as exc:
                self.stats['planning_errors'][str(source)] = str(exc)
                self.log(f'    خطای بررسی {source.name}: {exc}')
        self.stats['planning_seconds'] = round(time.monotonic() - started, 3)

    def _service(self):
        if not hasattr(self.thread_local, 'service'):
            self.thread_local.service = self.service_factory()
            with self.state_lock:
                self.services.append(self.thread_local.service)
        return self.thread_local.service

    def _call(self, data, mime, name, owner):
        if len(data) > quality.UPLOAD_GUARD_BYTES:
            raise ValueError('مدیای آماده از محافظ داخلی حجم بیشتر است؛ ارسال نشد.')
        fast = self.options.fast_transport and not self.degraded.is_set()
        metrics = {'name': name, 'bytes': len(data), 'mime': mime, 'owner': owner,
                   'transport': 'multipart_export_only' if fast else 'resumable_structured'}
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime,
                                  resumable=not fast)
        started = time.monotonic()
        with self.state_lock:
            self.stats['requests'] += 1
            self.stats['upload_bytes'] += len(data)
        self.log(f'    ارسال {name}: {len(data)/1024**2:.2f} MB؛ {mime}؛ ۳۰۰ DPI')
        if len(data) > quality.RECOMMENDED_BYTES:
            self.log('    هشدار: صفحهٔ منفرد از حجم توصیه‌شدهٔ ۲ MB بزرگ‌تر است؛ DPI کاهش نیافت.')
        def execute():
            return self.ocr_media(media, name, mime, self._service(),
                                  export_only=fast,
                                  metrics=metrics, log_func=self.log)
        try:
            if self.degraded.is_set():
                with self.serial_lock:
                    return execute()
            return execute()
        except Exception as exc:
            self.degraded.set()
            metrics['error'] = str(exc)
            self.log(f'    خطای شبکه/OCR؛ ادامهٔ درخواست‌های جدید به صورت ترتیبی: {exc}')
            raise
        finally:
            media.stream().close()
            metrics['total_seconds'] = round(time.monotonic() - started, 3)
            with self.state_lock:
                self.stats['calls'].append(metrics)

    @staticmethod
    def _usable(text, job):
        from pdf_page_pipeline import normalize_text
        clean = normalize_text(quality.text_only(text))
        clean = quality.MARKER_RE.sub('', clean).strip()
        result = quality.evaluate_text(clean)
        quality.check_anchors(result, clean, job['anchors'])
        if result['status'] == 'FAIL':
            raise ValueError('متن OCR کنترل سلامت صفحه را رد کرد: ' + '؛ '.join(result['reasons']))
        return clean

    def _single(self, job, data, *, fallback=False):
        error = None
        for attempt in range(2):
            if attempt:
                with self.state_lock:
                    used = self.retry_counts.get(job['source'], 0)
                    if used >= self.max_page_retries:
                        break
                    self.retry_counts[job['source']] = used + 1
                time.sleep(2)  # تلاش مجدد محدود؛ نه حلقهٔ بی‌پایان یا ارسال سیل‌آسا.
            try:
                raw = self._call(data, 'image/jpeg', f"page_{job['number']:04d}_{Path(job['source']).name}", job['key'])
                return {'text': self._usable(raw, job), 'method': 'google_single',
                        'fallback': fallback, 'retried': bool(attempt)}
            except Exception as exc:
                error = str(exc)
        return {'text': '', 'method': 'google_single', 'error': error or 'سقف تلاش مجدد', 'fallback': fallback}

    def _network_group(self, jobs, single_data, bundle, token):
        if len(jobs) == 1:
            return {jobs[0]['key']: self._single(jobs[0], single_data[0])}
        try:
            raw = self._call(bundle, 'application/pdf', f'ocr_bundle_{token}_{len(jobs)}pages.pdf', jobs[0]['key'])
            parts = split_response(raw, token, len(jobs))
        except Exception as exc:
            self.log(f'    بسته تأیید نشد ({exc})؛ ارسال مستقل {len(jobs)} صفحه، بدون جاگذاری حدسی')
            parts = [None] * len(jobs)
        results = {}
        for job, data, text in zip(jobs, single_data, parts):
            try:
                if text is None:
                    raise ValueError('مرز نامعتبر')
                results[job['key']] = {'text': self._usable(text, job), 'method': 'google_batch', 'batch_id': token}
            except ValueError:
                with self.state_lock:
                    self.stats['fallback_pages'] += 1
                results[job['key']] = self._single(job, data, fallback=True)
        return results

    def _prepared_groups(self):
        # جریان محدود: رندر اصلی در main، حداکثر دو بستهٔ درحال ارسال در حافظه.
        jobs, images, size = [], [], 0
        def package(items, pictures):
            token = uuid.uuid4().hex[:12].upper()
            singles = [quality.jpeg_bytes(image) for image in pictures]
            bundle = raster_bundle(pictures, token) if len(items) > 1 else b''
            if len(items) > 1 and len(bundle) > self.options.batch_bytes:
                middle = len(items) // 2
                yield from package(items[:middle], pictures[:middle])
                yield from package(items[middle:], pictures[middle:])
            else:
                yield items, singles, bundle, token
        try:
            for job in self.jobs.values():
                if jobs and (len(jobs) >= self.options.batch_pages or size + job['size'] > self.options.batch_bytes * 0.9):
                    yield from package(jobs, images)
                    for image in images:
                        image.close()
                    jobs, images, size = [], [], 0
                with fitz.open(job['source']) as doc:
                    image = quality.render_page(doc[job['number'] - 1], job['number'], dpi=300,
                                                rotation=job['rotation'], markers=False)
                if digest_image(image) != job['key']:
                    image.close()
                    raise RuntimeError('PDF هنگام اجرا تغییر کرد؛ ارسال تصویر متفاوت متوقف شد.')
                jobs.append(job)
                images.append(image)
                size += job['size']
            if jobs:
                yield from package(jobs, images)
        finally:
            for image in images:
                image.close()

    def _store_results(self, results):
        for key, result in results.items():
            calls = [call for call in self.stats['calls'] if call['owner'] == key]
            result['requests'] = len(calls)
            result['upload_bytes'] = sum(call['bytes'] for call in calls)
            result['timings'] = {stage: round(sum(call.get(stage, 0) for call in calls), 3)
                                 for stage in ('upload_convert_seconds', 'docs_structure_seconds',
                                               'export_seconds', 'delete_seconds', 'total_seconds')}
            if self.cache and result.get('text'):
                self.cache.put(key, result['text'])
            for index, identity in enumerate(self.destinations[key]):
                entry = dict(result)
                if index:
                    entry['method'] = 'duplicate'
                    entry.update(requests=0, upload_bytes=0, timings={})
                self.results[identity] = entry
                self.log(f"    نتیجه: {Path(identity[0]).name} صفحه {identity[1]}؛ {entry['method']}؛ {'FAIL' if entry.get('error') else 'قابل‌استفاده'}")

    def run(self):
        started = time.monotonic()
        self.log(f"    آزمایش سرعت: {len(self.jobs)} صفحهٔ یکتا؛ حداکثر {self.options.workers} مسیر و {self.options.batch_pages} صفحه در بسته")
        groups = self._prepared_groups()
        try:
            with ThreadPoolExecutor(max_workers=self.options.workers) as pool:
                pending = set()
                exhausted = False
                while pending or not exhausted:
                    while not exhausted and len(pending) < self.options.workers:
                        try:
                            group = next(groups)
                        except StopIteration:
                            exhausted = True
                            break
                        pending.add(pool.submit(self._network_group, *group))
                    if pending:
                        done, pending = wait(pending, return_when=FIRST_COMPLETED)
                        for future in done:
                            self._store_results(future.result())
            if self.cache:
                for key, pages in self.file_maps.items():
                    self.cache.put_file(key, pages)
        finally:
            groups.close()
            for service in self.services:
                if hasattr(service, 'close'):
                    try:
                        service.close()
                    except Exception as exc:
                        self.log(f'    هشدار بستن اتصال: {exc}')
            self.stats['network_wall_seconds'] = round(time.monotonic() - started, 3)
            self.stats['degraded_to_serial'] = self.degraded.is_set()
            self.stats['retry_requests'] = sum(self.retry_counts.values())

    def lookup(self, source, number):
        result = self.results.get(self.identity(source, number))
        if result is None:
            raise RuntimeError('صفحه در نقشهٔ اجرای OCR موجود نیست؛ جاگذاری حدسی ممنوع است.')
        return result

    def close(self):
        if self.cache:
            self.cache.close()

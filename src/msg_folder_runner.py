# -*- coding: utf-8 -*-
"""اجرای روال MSG روی مسیرهای دلخواه؛ نام خروجی دقیقاً نام پوشه ورودی است."""
import argparse
import contextlib
from datetime import datetime
import hashlib
from pathlib import Path
import sys


def snapshot(source):
    result = {}
    for path in source.rglob('*'):
        if path.is_file() and path.suffix.lower() == '.msg':
            h = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(block)
            result[str(path.relative_to(source))] = h.hexdigest()
    return result


def validate_paths(source, output_root):
    source = Path(source).expanduser().resolve()
    output_root = Path(output_root).expanduser().resolve()
    if not source.is_dir() or not source.name:
        raise ValueError('پوشه ورودی معتبر نیست؛ یک پوشه دارای نام انتخاب کنید.')
    target = output_root / source.name
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('پوشه مجموعه خروجی و ورودی نباید داخل یکدیگر باشند.')
    if output_root.exists() and not output_root.is_dir():
        raise ValueError('ریشه خروجی باید پوشه باشد.')
    if target.exists():
        raise ValueError(f'خروجی از قبل وجود دارد؛ ریشه خروجی دیگری انتخاب کنید: {target}')
    return source, target


class Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, value):
        self.console.write(value)
        self.log.write(value)
        self.flush()
        return len(value)

    def flush(self):
        self.console.flush()
        self.log.flush()


def run(source, output_root):
    source, target = validate_paths(source, output_root)
    before = snapshot(source)
    if not before:
        raise ValueError('هیچ فایل MSG در پوشه ورودی و زیرپوشه‌های آن پیدا نشد.')
    print(f'ورودی: {source}\nتعداد MSG: {len(before)}\nخروجی: {target}', flush=True)
    print('بررسی اتصال Google Drive…', flush=True)
    import google_drive_ocr
    from offline_msg_pipeline import process_msg_dataset
    from ocr_speed import SpeedOptions
    service = google_drive_ocr.get_drive_service()
    try:
        service.files().list(pageSize=1, fields='files(id)').execute()
    finally:
        service.close()
    if snapshot(source) != before:
        raise RuntimeError('ورودی در زمان بررسی تغییر کرد؛ اجرا شروع نشد.')
    # ساخت انحصاری پوشه پس از پیش‌بررسی؛ اجرای هم‌زمان هم بازنویسی نمی‌کند.
    target.mkdir(parents=True, exist_ok=False)
    log_path = target / 'run.log'
    with log_path.open('w', encoding='utf-8') as log:
        with contextlib.redirect_stdout(Tee(sys.stdout, log)), contextlib.redirect_stderr(Tee(sys.stderr, log)):
            print(f'شروع: {datetime.now().isoformat()}\nورودی: {source}\nخروجی: {target}\nتعداد MSG: {len(before)}')
            try:
                code = process_msg_dataset(source, source.name, use_ocr=True, use_rag=False,
                    output_dir=target, ocr_speed_options=SpeedOptions(
                        workers=2, batch_pages=5, fast_transport=True, cache=True))
            finally:
                unchanged = snapshot(source) == before
                print(f'ورودی بدون تغییر: {unchanged}\nلاگ: {log_path}')
            if not unchanged:
                raise RuntimeError('ورودی‌ها حین اجرا تغییر کرده‌اند؛ بررسی لازم است.')
            print(f'پایان؛ کد خروج: {code}')
            return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output-root', required=True)
    args = parser.parse_args()
    try:
        return run(args.input, args.output_root)
    except Exception as error:
        print(f'توقف اجرا: {error}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

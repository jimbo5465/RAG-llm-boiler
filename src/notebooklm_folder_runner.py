# -*- coding: utf-8 -*-
"""تجمیع محلی یک پوشه خروجی ایمیل با نام همان مجموعه."""
import argparse
from pathlib import Path
from bundle_notebooklm import build


def validate_paths(source, output_root):
    source = Path(source).expanduser().resolve()
    root = Path(output_root).expanduser().resolve()
    if not source.is_dir() or not source.name:
        raise ValueError('پوشه ورودی معتبر نیست.')
    if not (source / 'attachment_manifest.json').is_file() or not (source / 'emails').is_dir():
        raise ValueError('پوشه خود مجموعه را انتخاب کنید؛ باید emails و attachment_manifest.json داشته باشد.')
    destination = root / source.name
    if destination.exists():
        raise ValueError('پوشه خروجی هم‌نام از قبل موجود است؛ ریشه خروجی دیگری انتخاب کنید.')
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('پوشه خروجی و ورودی نباید داخل یکدیگر باشند.')
    if root.exists() and not root.is_dir():
        raise ValueError('ریشه خروجی باید پوشه باشد.')
    return source, destination


def run(source, output_root):
    source, destination = validate_paths(source, output_root)
    print(f'خواندن ایمیل‌ها و متن پیوست‌ها: {source}', flush=True)
    print(f'مسیر نهایی: {destination}', flush=True)
    report = build([source], destination, filename_prefix=source.name,
                   allow_external_output=True)
    print('تجمیع تمام شد؛ منابع اصلی حفظ شدند.', flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output-root', required=True)
    args = parser.parse_args()
    try:
        run(args.input, args.output_root)
    except Exception as error:
        print(f'خطا: {error}', flush=True)
        raise SystemExit(1)

# -*- coding: utf-8 -*-
"""آزمون قابل تکرار دو نمونه؛ خروجی‌های قبلی دست‌نخورده می‌مانند."""
import argparse
import hashlib
import json
from pathlib import Path

import pymupdf
import google_drive_ocr as ocr
import pdf_ocr_quality as quality

ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / 'Extracted_Data' / 'first' / 'emails' / 'attachments'
OUTPUT_DIR = ROOT / 'Extracted_Data' / 'first' / 'pdf_quality_test_v1'
NAMES = ['14021130_011_1_5321.pdf', '14021205_012_1_2024-02-24 (1).pdf']


def run(prepare_only=False, reuse_raw=False):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    service = None
    for name in NAMES:
        source = SOURCE_DIR / name
        prepared = OUTPUT_DIR / (source.stem + '.prepared.pdf')
        output = OUTPUT_DIR / (source.stem + '.md')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        print(f'\n[+] {name}', flush=True)
        try:
            if prepare_only:
                info = quality.prepare_pdf(source, prepared)
                prepared.with_suffix('.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(info, ensure_ascii=False, indent=2), flush=True)
                with pymupdf.open(prepared) as document:
                    # صفحات نماینده برای بازبینی بصری: فارسی، چرخش و نقشه.
                    for number in ([1, 3, 4] if len(document) == 4 else [1, 2, 4, 7, 11]):
                        document[number-1].get_pixmap(dpi=100).save(
                            str(OUTPUT_DIR / f'{source.stem}.preview-{number}.png'))
                results.append({'file': name, 'prepared': info, 'source_unchanged': hashlib.sha256(source.read_bytes()).hexdigest() == digest})
            else:
                ocr.convert_file_to_md_gdrive(str(source), str(output), service=service,
                                             max_page_retries=2, reuse_raw=reuse_raw, debug_errors=True)
                report = json.loads((OUTPUT_DIR / 'ocr_quality_report.json').read_text(encoding='utf-8'))[output.name]
                results.append({'file': name, 'status': report['status'],
                                'requests': report['requests'], 'local_pages': report['local_pages'],
                                'google_pages': report['google_pages'], 'failed_pages': report['failed_pages'],
                                'source_unchanged': hashlib.sha256(source.read_bytes()).hexdigest() == digest})
                print(json.dumps(results[-1], ensure_ascii=False, indent=2), flush=True)
        except Exception as exc:
            results.append({'file': name, 'error': str(exc)})
            print(f'[!] {exc}', flush=True)
        (OUTPUT_DIR / ('preparation_summary.json' if prepare_only else 'recheck_summary.json' if reuse_raw else 'test_summary.json')).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return 1 if any('error' in result for result in results) else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--reuse-raw', action='store_true')
    args = parser.parse_args()
    raise SystemExit(run(args.prepare_only, args.reuse_raw))

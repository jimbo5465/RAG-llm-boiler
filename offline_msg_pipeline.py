# -*- coding: utf-8 -*-
"""خط لوله آفلاین پردازش فایل‌های Outlook MSG بدون نیاز به نصب Outlook."""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import extract_msg
from bs4 import BeautifulSoup

import google_drive_ocr
import step3_5_attachments
import step3_discovery
import step4_rag
from project_paths import EXTRACTED_DATA_DIR, MSG_INPUT_DIR


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


VALID_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".xlsm", ".pptx",
    ".rar", ".zip", ".dwg", ".jpg", ".jpeg", ".png", ".bmp",
    ".tif", ".tiff", ".msg", ".txt", ".csv",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
IMAGE_MIN_SIZE_BYTES = 40 * 1024


def parse_args():
    parser = argparse.ArgumentParser(
        description="پردازش آفلاین فایل‌های MSG و پیوست‌های آن‌ها بدون Outlook"
    )
    parser.add_argument(
        "--input",
        default=MSG_INPUT_DIR,
        help="پوشه ورودی MSG (پیش‌فرض: test_inputs/msg)",
    )
    parser.add_argument(
        "--dataset",
        default="offline_msg",
        help="نام مجموعه خروجی زیر Extracted_Data",
    )
    ocr_group = parser.add_mutually_exclusive_group()
    ocr_group.add_argument(
        "--ocr",
        dest="ocr",
        action="store_true",
        help="اجرای Google OCR (رفتار پیش‌فرض)",
    )
    ocr_group.add_argument(
        "--no-ocr",
        dest="ocr",
        action="store_false",
        help="غیرفعال‌کردن Google OCR فقط برای اجرای محلی/عیب‌یابی",
    )
    parser.set_defaults(ocr=True)
    parser.add_argument('--ocr-debug', action='store_true',
                        help='نگهداری پاسخ خام فقط برای OCRهای مشکل‌دار')
    parser.add_argument('--ocr-workers', type=int, choices=(1, 2), default=1,
                        help='تعداد مسیر شبکهٔ OCR؛ دو مسیر آزمایشی است')
    parser.add_argument('--ocr-batch-pages', type=int, choices=range(1, 6), default=1,
                        help='حداکثر صفحات هر بستهٔ آزمایشی، همراه با کنترل حجم')
    parser.add_argument('--ocr-fast-transport', action='store_true',
                        help='آزمایش ارسال تک‌درخواستی و دریافت مستقیم Markdown')
    parser.add_argument('--no-ocr-cache', action='store_true',
                        help='عدم استفاده از حافظهٔ متن OCR برای آزمون مقایسه‌ای')
    parser.add_argument(
        "--force-ocr",
        action="store_true",
        help="بازنویسی خروجی‌های OCR موجود (همراه با --ocr)",
    )
    rag_group = parser.add_mutually_exclusive_group()
    rag_group.add_argument(
        "--rag",
        dest="rag",
        action="store_true",
        help="ساخت یا بازسازی ایندکس RAG (رفتار پیش‌فرض)",
    )
    rag_group.add_argument(
        "--no-rag",
        dest="rag",
        action="store_false",
        help="توقف پس از استخراج و OCR بدون ساخت ایندکس RAG",
    )
    parser.set_defaults(rag=True)
    return parser.parse_args()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_path(directory, filename):
    candidate = directory / filename
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def get_message_datetime(message, source_path):
    for value in (getattr(message, "date", None), getattr(message, "receivedTime", None)):
        if isinstance(value, datetime):
            return value
    return datetime.fromtimestamp(source_path.stat().st_mtime)


def get_plain_body(message):
    body = getattr(message, "body", None)
    if body:
        return str(body)

    html_body = getattr(message, "htmlBody", None)
    if html_body:
        if isinstance(html_body, bytes):
            html_body = html_body.decode("utf-8", errors="replace")
        return BeautifulSoup(str(html_body), "html.parser").get_text("\n")
    return ""


def attachment_bytes(attachment):
    data = getattr(attachment, "data", None)
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if hasattr(data, "export"):
        import io

        buffer = io.BytesIO()
        data.export(buffer)
        return buffer.getvalue()
    return None


def attachment_name(attachment, index):
    name = (
        getattr(attachment, "longFilename", None)
        or getattr(attachment, "shortFilename", None)
        or getattr(attachment, "name", None)
        or f"attachment_{index}.bin"
    )
    name = str(name).replace("\x00", "").strip()
    return step3_discovery.sanitize_filename(name) or f"attachment_{index}.bin"


def should_skip_attachment(attachment, filename, data):
    extension = Path(filename).suffix.lower()
    if extension not in VALID_ATTACHMENT_EXTENSIONS:
        return True
    if getattr(attachment, "hidden", False) and extension in IMAGE_EXTENSIONS:
        return True
    if extension in IMAGE_EXTENSIONS:
        lowered = filename.lower()
        looks_inline = any(word in lowered for word in ("image", "signature", "logo"))
        if looks_inline and len(data) < IMAGE_MIN_SIZE_BYTES:
            return True
    return False


def load_existing_attachment_hashes(attachments_dir):
    result = {}
    for path in attachments_dir.iterdir():
        if path.is_file():
            try:
                result[sha256_file(path)] = path.name
            except OSError:
                continue
    return result


def format_message_markdown(
    message_id,
    subject,
    sender,
    recipients,
    cc,
    shamsi_date,
    source_name,
    attachments,
    clean_body,
):
    attachment_lines = (
        "\n".join(f"- attachments/{name}" for name in attachments)
        if attachments
        else "ندارد"
    )
    return f"""---
شناسه: {message_id}
موضوع: {subject}
فرستنده: {sender}
گیرنده اصلی (To): {recipients}
رونوشت (Cc): {cc}
تاریخ شمسی: {shamsi_date}
منبع: {source_name}
تعداد پیوست‌های معتبر ذخیره شده: {len(attachments)}
پیوست‌ها:
{attachment_lines}
---

# متن مکاتبه:

{clean_body}
"""


def build_quality_report(
    dataset_dir,
    emails_dir,
    attachments_dir,
    attachments_text_dir,
    ocr_dir,
    attachment_manifest,
    processed_count,
    failed_count,
    attachment_stats,
    ocr_stats,
):
    """کنترل پوشش و سازگاری خروجی‌ها پیش از ایندکس‌گذاری RAG."""
    email_names = {path.name for path in emails_dir.glob("*.md")}
    raw_attachments = {path.name for path in attachments_dir.iterdir() if path.is_file()}
    local_outputs = {path.stem for path in attachments_text_dir.glob("*.md")}
    ocr_outputs = {path.stem for path in ocr_dir.glob("*.md")} if ocr_dir.exists() else set()
    covered_stems = local_outputs | ocr_outputs

    expected_text_extensions = {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".pptx",
        ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff",
    }
    def has_required_text_output(name):
        path = Path(name)
        if path.suffix.lower() == ".pdf":
            # خروجی محلی قدیمی برای PDF کافی نیست؛ PDF باید خروجی Google داشته باشد.
            return path.stem in ocr_outputs
        return path.stem in covered_stems

    uncovered = sorted(
        name
        for name in raw_attachments
        if Path(name).suffix.lower() in expected_text_extensions
        and not has_required_text_output(name)
    )

    broken_manifest_attachments = sorted(
        name for name in attachment_manifest if name not in raw_attachments
    )
    broken_manifest_parents = []
    for attachment_name, parents in attachment_manifest.items():
        for parent in parents:
            if parent not in email_names:
                broken_manifest_parents.append(
                    {"attachment": attachment_name, "missing_parent": parent}
                )

    errors = []
    warnings = []
    if failed_count:
        errors.append(f"{failed_count} فایل MSG ناموفق بود.")
    if attachment_stats.get("err", 0):
        errors.append(f"{attachment_stats['err']} پیوست در تبدیل محلی خطا داشت.")
    if ocr_stats.get("errors", 0):
        errors.append(f"{ocr_stats['errors']} فایل در Google OCR خطا داشت.")
    if broken_manifest_attachments:
        errors.append("مانیفست به پیوست‌هایی اشاره می‌کند که وجود ندارند.")
    if broken_manifest_parents:
        errors.append("مانیفست به ایمیل‌های والد ناموجود اشاره می‌کند.")
    if uncovered:
        warnings.append(
            "برخی پیوست‌های متن‌پذیر خروجی متنی ندارند؛ ممکن است تصویر نویزی یا سند پشتیبانی‌نشده باشند."
        )

    status = "error" if errors else ("warning" if warnings else "ok")
    report = {
        "status": status,
        "messages_processed_this_run": processed_count,
        "email_markdown_files": len(email_names),
        "raw_attachments": len(raw_attachments),
        "local_text_outputs": len(local_outputs),
        "google_ocr_outputs": len(ocr_outputs),
        "uncovered_text_candidates": uncovered,
        "broken_manifest_attachments": broken_manifest_attachments,
        "broken_manifest_parents": broken_manifest_parents,
        "errors": errors,
        "warnings": warnings,
    }
    (dataset_dir / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def process_msg_dataset(
    input_dir,
    dataset_name,
    use_ocr=False,
    force_ocr=False,
    use_rag=False,
    ocr_debug=False,
    ocr_speed_options=None,
):
    input_dir = Path(input_dir).expanduser().resolve()
    if not input_dir.is_dir():
        raise FileNotFoundError(f"پوشه ورودی وجود ندارد: {input_dir}")

    dataset_safe = step3_discovery.sanitize_filename(dataset_name).strip(" .")
    if not dataset_safe:
        raise ValueError("نام مجموعه خروجی معتبر نیست.")

    dataset_dir = Path(EXTRACTED_DATA_DIR) / dataset_safe
    emails_dir = dataset_dir / "emails"
    attachments_dir = emails_dir / "attachments"
    attachments_text_dir = dataset_dir / "attachments_text"
    ocr_dir = dataset_dir / "attachments_ocr_google"

    for directory in (emails_dir, attachments_dir, attachments_text_dir):
        directory.mkdir(parents=True, exist_ok=True)

    top_level_messages = sorted(input_dir.rglob("*.msg"), key=lambda path: str(path).lower())
    if not top_level_messages:
        raise FileNotFoundError(f"هیچ فایل MSG در پوشه ورودی پیدا نشد: {input_dir}")

    print(f"[+] پوشه ورودی: {input_dir}")
    print(f"[+] تعداد فایل‌های MSG اولیه: {len(top_level_messages)}")
    print(f"[+] مجموعه خروجی: {dataset_dir}")

    attachment_manifest = {}
    manifest_path = dataset_dir / "attachment_manifest.json"
    if manifest_path.exists():
        try:
            attachment_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            attachment_manifest = {}

    hash_to_attachment = load_existing_attachment_hashes(attachments_dir)
    queue = [(path, None) for path in top_level_messages]
    queued_hashes = {sha256_file(path) for path in top_level_messages}
    processed_hashes = set()
    processed_count = 0
    failed_count = 0
    saved_attachment_count = 0

    while queue:
        source_path, parent_email = queue.pop(0)
        source_hash = sha256_file(source_path)
        if source_hash in processed_hashes:
            continue
        processed_hashes.add(source_hash)
        email_index = processed_count + 1

        try:
            message = extract_msg.openMsg(str(source_path))
            try:
                subject = getattr(message, "subject", None) or "(بدون موضوع)"
                subject = step3_discovery.COMPILED_SUBJECT_WARNING_REGEX.sub("", subject).strip()
                subject = subject or "(بدون موضوع)"
                sender = (getattr(message, "sender", None) or "نامشخص").strip()
                recipients = (getattr(message, "to", None) or "ندارد").strip()
                cc = (getattr(message, "cc", None) or "ندارد").strip()
                message_dt = get_message_datetime(message, source_path)
                shamsi_date = step3_discovery.gregorian_to_jalali(
                    message_dt.year, message_dt.month, message_dt.day
                )
                date_prefix = shamsi_date.replace("/", "")
                safe_subject = step3_discovery.sanitize_filename(subject)
                email_filename = f"{date_prefix}_{email_index:03d}_{safe_subject}.md"
                email_path = emails_dir / email_filename

                saved_for_email = []
                for attachment_index, attachment in enumerate(message.attachments, 1):
                    raw_data = attachment_bytes(attachment)
                    if not raw_data:
                        print(f"  [!] پیوست {attachment_index} قابل خواندن نبود: {source_path.name}")
                        continue

                    original_name = attachment_name(attachment, attachment_index)
                    if should_skip_attachment(attachment, original_name, raw_data):
                        continue

                    data_hash = sha256_bytes(raw_data)
                    existing_name = hash_to_attachment.get(data_hash)
                    if existing_name:
                        stored_name = existing_name
                    else:
                        stored_name = (
                            f"{date_prefix}_{email_index:03d}_{attachment_index}_"
                            f"{original_name}"
                        )
                        target_path = unique_path(attachments_dir, stored_name)
                        target_path.write_bytes(raw_data)
                        stored_name = target_path.name
                        hash_to_attachment[data_hash] = stored_name
                        saved_attachment_count += 1

                    saved_for_email.append(stored_name)
                    parents = attachment_manifest.setdefault(stored_name, [])
                    if email_filename not in parents:
                        parents.append(email_filename)

                    if Path(stored_name).suffix.lower() == ".msg" and data_hash not in queued_hashes:
                        queued_hashes.add(data_hash)
                        queue.append((attachments_dir / stored_name, email_filename))

                body = get_plain_body(message)
                clean_body = step3_discovery.parse_and_clean_thread(body)
                if not clean_body:
                    clean_body = step3_discovery.PLACEHOLDER_EMPTY_BODY

                message_id = getattr(message, "messageId", None) or source_hash
                markdown = format_message_markdown(
                    message_id=str(message_id),
                    subject=subject,
                    sender=sender,
                    recipients=recipients,
                    cc=cc,
                    shamsi_date=shamsi_date,
                    source_name=source_path.name,
                    attachments=saved_for_email,
                    clean_body=clean_body,
                )
                email_path.write_text(markdown, encoding="utf-8")
                processed_count += 1
                parent_note = f" | پیوستِ {parent_email}" if parent_email else ""
                print(f"[{processed_count}] استخراج شد: {source_path.name}{parent_note}")
            finally:
                message.close()
        except Exception as error:
            failed_count += 1
            print(f"[-] خطا در پردازش {source_path.name}: {error}")

    manifest_path.write_text(
        json.dumps(attachment_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("[+] تبدیل آفلاین پیوست‌ها شروع شد...")
    attachment_stats = step3_5_attachments.process_attachments(
        att_dir=str(attachments_dir),
        md_dir=str(emails_dir),
        out_dir=str(attachments_text_dir),
        attachment_manifest=attachment_manifest,
    )

    ocr_stats = {
        "eligible": 0,
        "converted": 0,
        "existing": 0,
        "digital": 0,
        "noise": 0,
        "errors": 0,
    }
    if use_ocr:
        print("[+] Google OCR شروع شد...")
        ocr_stats = google_drive_ocr.batch_convert_all(
            str(attachments_dir),
            str(ocr_dir),
            force_overwrite=force_ocr,
            attachment_manifest=attachment_manifest,
            debug_errors=ocr_debug,
            speed_options=ocr_speed_options,
        ) or ocr_stats

    print("[+] کنترل کیفیت خروجی‌ها شروع شد...")
    quality_report = build_quality_report(
        dataset_dir=dataset_dir,
        emails_dir=emails_dir,
        attachments_dir=attachments_dir,
        attachments_text_dir=attachments_text_dir,
        ocr_dir=ocr_dir,
        attachment_manifest=attachment_manifest,
        processed_count=processed_count,
        failed_count=failed_count,
        attachment_stats=attachment_stats,
        ocr_stats=ocr_stats,
    )
    print(f"[+] وضعیت کنترل کیفیت: {quality_report['status']}")

    rag_summary = {
        "enabled": use_rag,
        "status": "disabled",
        "prepared_chunks": 0,
        "indexed_chunks": 0,
        "error": None,
    }
    if use_rag:
        print("[+] چانک‌بندی، Embedding و ساخت ایندکس RAG شروع شد...")
        try:
            step4_rag.configure_dataset(str(dataset_dir))
            chunks = step4_rag.export_chunks_jsonl(
                str(dataset_dir / "rag_chunks.jsonl")
            )
            rag_summary["prepared_chunks"] = len(chunks)
            collection = step4_rag.build_index(rebuild=True, chunks=chunks)
            if collection is None:
                raise RuntimeError("ساخت ایندکس RAG ناموفق بود.")
            rag_summary.update(
                {"status": "ok", "indexed_chunks": collection.count(), "error": None}
            )
        except Exception as error:
            rag_summary.update(
                {"status": "error", "chunks": 0, "error": str(error)}
            )
            print(f"[-] خطا در ساخت RAG: {error}")

    summary = {
        "input_dir": str(input_dir),
        "dataset_dir": str(dataset_dir),
        "messages_processed": processed_count,
        "messages_failed": failed_count,
        "attachments_saved": saved_attachment_count,
        "attachment_conversion": attachment_stats,
        "google_ocr_enabled": use_ocr,
        "google_ocr": ocr_stats,
        "quality_control": quality_report,
        "rag": rag_summary,
    }
    (dataset_dir / "pipeline_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=" * 60)
    print(f"[+] ایمیل پردازش‌شده: {processed_count}")
    print(f"[+] ایمیل ناموفق: {failed_count}")
    print(f"[+] پیوست یکتای ذخیره‌شده: {saved_attachment_count}")
    print(f"[+] وضعیت کنترل کیفیت: {quality_report['status']}")
    print(
        f"[+] وضعیت RAG: {rag_summary['status']} | "
        f"چانک آماده: {rag_summary['prepared_chunks']} | "
        f"ایندکس‌شده: {rag_summary['indexed_chunks']}"
    )
    print(f"[+] خروجی: {dataset_dir}")
    print("=" * 60)
    if failed_count or quality_report["status"] == "error" or rag_summary["status"] == "error":
        return 2
    return 0


def main():
    args = parse_args()
    from ocr_speed import SpeedOptions
    try:
        return process_msg_dataset(
            input_dir=args.input,
            dataset_name=args.dataset,
            use_ocr=args.ocr,
            force_ocr=args.force_ocr,
            use_rag=args.rag,
            ocr_debug=args.ocr_debug,
            ocr_speed_options=SpeedOptions(workers=args.ocr_workers,
                batch_pages=args.ocr_batch_pages, fast_transport=args.ocr_fast_transport,
                cache=not args.no_ocr_cache),
        )
    except Exception as error:
        print(f"[-] توقف خط لوله: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

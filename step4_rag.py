# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
"""
Step 4 — RAG لوکال آرشیو دانش بویلر نیروگاه فردوسی

ویژگی‌ها:
1. Indexing (ایندکس‌گذاری):
   - خواندن ایمیل‌های Extracted_Sample/ و تفکیک هر پیام thread به عنوان یک چانک با متادیتای کامل (تاریخ، فرستنده، موضوع، والد)
   - خواندن متون پیوست‌ها از Extracted_Sample_text/attachments_text/ و قطعه‌بندی هوشمند (پرهیز از اسکن‌های خالی)
   - امبدینگ چندزبانه لوکال (پیش‌فرض: paraphrase-multilingual-MiniLM-L12-v2 یا BAAI/bge-m3)
   - ذخیره‌سازی و پایداری در پایگاه داده برداری لوکال ChromaDB

2. Retrieval & Citation (بازیابی و استناد):
   - جستجوی معنایی بر اساس پرسش کاربر
   - نمایش قطعات مرتبط به همراه متادیتای استناد (فرستنده، تاریخ شمسی، موضوع، فایل منبع)
   - حالت تعاملی (Interactive CLI) برای پرسش و پاسخ
"""

import os
import glob
import argparse
import json
import re
import sys

# تنظیم مسیرهای اصلی
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EMAIL_DIR = os.path.join(BASE_DIR, "Extracted_Sample")
ATTACHMENT_TEXT_DIR = os.path.join(BASE_DIR, "Extracted_Sample_text", "attachments_text")
ATTACHMENT_TEXT_DIRS = [ATTACHMENT_TEXT_DIR]
CHROMA_PERSIST_DIR = os.path.join(BASE_DIR, "chroma_db")

# مدل امبدینگ پیش‌فرض سبک و باکیفیت برای زبان فارسی و انگلیسی روی CPU
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
COLLECTION_NAME = "boiler_knowledge_base"


def configure_dataset(dataset_dir):
    """تنظیم مسیرهای RAG برای یک مجموعه خروجی Extracted_Data."""
    global EMAIL_DIR, ATTACHMENT_TEXT_DIR, ATTACHMENT_TEXT_DIRS, CHROMA_PERSIST_DIR
    dataset_dir = os.path.abspath(dataset_dir)
    EMAIL_DIR = os.path.join(dataset_dir, "emails")
    ATTACHMENT_TEXT_DIR = os.path.join(dataset_dir, "attachments_text")
    ATTACHMENT_TEXT_DIRS = [
        ATTACHMENT_TEXT_DIR,
        os.path.join(dataset_dir, "attachments_ocr_google"),
    ]
    CHROMA_PERSIST_DIR = os.path.join(dataset_dir, "chroma_db")
    return dataset_dir


def parse_yaml_frontmatter(content):
    """استخراج متادیتا از هدر YAML ابتدای فایل"""
    metadata = {}
    if not content.startswith("---"):
        return metadata, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return metadata, content

    header = parts[1]
    body = parts[2].strip()

    current_key = None
    for line in header.strip().split("\n"):
        stripped = line.strip()
        if stripped.startswith("- ") and current_key:
            value = stripped[2:].strip()
            if value:
                previous = metadata.get(current_key, "")
                metadata[current_key] = f"{previous} | {value}".strip(" |")
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            current_key = key.strip()
            metadata[current_key] = val.strip()

    return metadata, body


def chunk_email_file(file_path):
    """
    تفکیک هر ایمیل به چانک‌های مجزا به تفکیک پیام‌های داخل Thread
    هر چانک هدر متادیتا را همراه دارد تا کانتکست حفظ شود.
    """
    filename = os.path.basename(file_path)
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    meta, body = parse_yaml_frontmatter(content)
    subject = meta.get("موضوع", filename)
    sender = meta.get("فرستنده", "نامشخص")
    date_shamsi = meta.get("تاریخ شمسی", "")
    folder_path = meta.get("مسیر پوشه", "")

    chunks = []

    # تفکیک پیام‌ها بر اساس جداکننده‌های مرسوم
    sections = re.split(r"(?:### 📩 آخرین پیام \(پاسخ جاری\):|### 📜 پیام در تاریخچه مکاتبات:|\n---\n)", body)

    msg_idx = 1
    for sec in sections:
        clean_sec = sec.strip()
        if not clean_sec or len(clean_sec) < 15:
            continue

        # استخراج متادیتای درون پیام در صورت وجود هدر From/Sent
        sub_sender = sender
        sub_date = date_shamsi
        
        from_match = re.search(r">?\s*From:\s*([^\n\r]+)", clean_sec, re.IGNORECASE)
        if from_match:
            sub_sender = from_match.group(1).strip()
            
        sent_match = re.search(r">?\s*Sent:\s*([^\n\r]+)", clean_sec, re.IGNORECASE)
        if sent_match:
            sub_date = sent_match.group(1).strip()

        chunk_text = (
            f"موضوع: {subject}\n"
            f"فرستنده: {sub_sender}\n"
            f"تاریخ: {sub_date}\n"
            f"فایل والد: {filename}\n\n"
            f"متن پیام:\n{clean_sec}"
        )

        chunk_meta = {
            "source_type": "email",
            "source_file": filename,
            "subject": subject,
            "sender": sub_sender,
            "date_shamsi": sub_date,
            "folder": folder_path,
            "chunk_id": f"{filename}_msg_{msg_idx}"
        }

        chunks.append((chunk_text, chunk_meta))
        msg_idx += 1

    return chunks


def chunk_attachment_file(file_path):
    """
    خواندن و چانک‌بندی متون پیوست‌ها
    نادیده‌گرفتن فایل‌های فاقد متن قابل استخراج
    """
    filename = os.path.basename(file_path)
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # نادیده گرفتن اسکن‌های بدون متن
    if "بدون متن قابل استخراج" in content or "نیاز به OCR" in content:
        return []

    meta, body = parse_yaml_frontmatter(content)
    report_path = os.path.join(os.path.dirname(file_path), 'ocr_quality_report.json')
    if os.path.exists(report_path):
        with open(report_path, encoding='utf-8') as source:
            report = json.load(source).get(filename)
        if report:
            meta.update({'سیاست_پذیرش': report['rag_policy'],
                         'آماده_RAG': str(report['rag_ready']).lower(),
                         'کیفیت_OCR': report['status'],
                         'تعداد_صفحات_اصلی': str(report['total']),
                         'تعداد_صفحات_پردازش‌شده': str(report['processed']),
                         'صفحات_پردازش‌شده': f"1-{report['processed']}",
                         'پردازش_کامل': str(not report['partial']).lower()})
    att_name = meta.get("پیوست", filename)
    email_first = meta.get("سیاست_پذیرش") == "email_first_v1"
    if meta.get("آماده_RAG", "").lower() == "false" or (
            meta.get("کیفیت_OCR") == "FAIL" and not email_first):
        print(f"[i] پیوست نیازمند بررسی کیفیت است و وارد RAG نشد: {filename}")
        return []
    if email_first:
        # متن خوانای سایر صفحات حفظ می‌شود؛ پیام جایگزین صفحهٔ مردود ایندکس نمی‌شود.
        sections = re.split(r"(?=^## صفحه \d+\s*$)", body, flags=re.M)
        body = '\n\n'.join(section for section in sections
                            if not re.search(r"^> کیفیت: FAIL\b|^> متن این صفحه تأیید نشده است", section, flags=re.M))
    parent_doc = meta.get("ایمیل‌های مرتبط (والد)") or meta.get("والد", "نامشخص")
    att_type = meta.get("نوع", "نامشخص")
    processing_context = ""
    if "تعداد_صفحات_اصلی" in meta:
        processing_context = (
            f"پوشش سند: {meta.get('تعداد_صفحات_پردازش‌شده')} از {meta['تعداد_صفحات_اصلی']} صفحه؛ "
            f"صفحات {meta.get('صفحات_پردازش‌شده')}؛ پردازش کامل: {meta.get('پردازش_کامل')}\n"
        )
    if email_first:
        processing_context += (
            "نقش پیوست: توضیح تکمیلی؛ متن ایمیل منبع اصلی زمینهٔ مکاتبه است.\n"
            "متن OCR ممکن است ناقص باشد؛ برای جزئیات دقیق به فایل اصلی مراجعه کنید.\n"
            f"فایل اصلی: {meta.get('فایل_اصلی', att_name)}\n"
        )

    chunks = []
    
    # اگر متن خیلی بلند باشد، بر اساس پاراگراف یا سایز چانک می‌کنیم (حداکثر ~1200 کاراکتر)
    paragraphs = body.split("\n\n")
    current_chunk = []
    current_len = 0
    part_idx = 1

    for p in paragraphs:
        p_clean = p.strip()
        if not p_clean:
            continue
        
        if current_len + len(p_clean) > 1200 and current_chunk:
            combined_text = "\n\n".join(current_chunk)
            chunk_text = (
                f"پیوست: {att_name} (نوع: {att_type})\n"
                f"ایمیل مرتبط: {parent_doc}\n\n"
                f"{processing_context}"
                f"محتوا:\n{combined_text}"
            )
            chunk_meta = {
                "source_type": "attachment",
                "source_file": filename,
                "attachment_name": att_name,
                "parent_email": parent_doc,
                "type": att_type,
                "source_role": "supporting_attachment",
                "original_attachment": meta.get("فایل_اصلی", att_name),
                "ocr_quality": meta.get("کیفیت_OCR", "نامشخص"),
                "chunk_id": f"{filename}_part_{part_idx}"
            }
            chunks.append((chunk_text, chunk_meta))
            part_idx += 1
            current_chunk = [p_clean]
            current_len = len(p_clean)
        else:
            current_chunk.append(p_clean)
            current_len += len(p_clean)

    if current_chunk:
        combined_text = "\n\n".join(current_chunk)
        chunk_text = (
            f"پیوست: {att_name} (نوع: {att_type})\n"
            f"ایمیل مرتبط: {parent_doc}\n\n"
            f"{processing_context}"
            f"محتوا:\n{combined_text}"
        )
        chunk_meta = {
            "source_type": "attachment",
            "source_file": filename,
            "attachment_name": att_name,
            "parent_email": parent_doc,
            "type": att_type,
            "source_role": "supporting_attachment",
            "original_attachment": meta.get("فایل_اصلی", att_name),
            "ocr_quality": meta.get("کیفیت_OCR", "نامشخص"),
            "chunk_id": f"{filename}_part_{part_idx}"
        }
        chunks.append((chunk_text, chunk_meta))

    return chunks


def load_all_documents():
    """گردآوری و چانک‌بندی تمامی ایمیل‌ها و پیوست‌های متنی"""
    all_chunks = []

    # 1. بارگذاری ایمیل‌ها
    email_files = glob.glob(os.path.join(EMAIL_DIR, "*.md"))
    print(f"[*] در حال خواندن {len(email_files)} فایل ایمیل از {EMAIL_DIR}...")
    for ef in email_files:
        try:
            chunks = chunk_email_file(ef)
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"[!] خطا در پردازش ایمیل {ef}: {e}")

    # 2. بارگذاری پیوست‌ها؛ در صورت وجود هر دو نسخه، OCR بر نسخه محلی اولویت دارد.
    attachment_files = {}
    for text_dir in ATTACHMENT_TEXT_DIRS:
        if not os.path.exists(text_dir):
            continue
        for path in glob.glob(os.path.join(text_dir, "*.md")):
            attachment_files[os.path.basename(path)] = path

    print(f"[*] در حال خواندن {len(attachment_files)} فایل پیوست متنی/OCR...")
    for af in sorted(attachment_files.values()):
        try:
            chunks = chunk_attachment_file(af)
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"[!] خطا در پردازش پیوست {af}: {e}")

    print(f"[+] مجموعاً {len(all_chunks)} چانک آماده ایندکس‌سازی شد.")
    return all_chunks


def export_chunks_jsonl(output_path=None):
    """ذخیره چانک‌ها و متادیتا در JSONL، مستقل از ChromaDB."""
    chunks = load_all_documents()
    if output_path is None:
        output_path = os.path.join(os.path.dirname(EMAIL_DIR), "rag_chunks.jsonl")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as target:
        for text, metadata in chunks:
            target.write(
                json.dumps(
                    {"text": text, "metadata": metadata},
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"[+] تعداد {len(chunks)} چانک در {output_path} ذخیره شد.")
    return chunks


def build_index(rebuild=False, chunks=None):
    """ساخت یا به‌روزرسانی ایندکس در ChromaDB"""
    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        print("[!] خطای وابستگی: لطفاً ابتدا کتابخانه‌های لازم را نصب کنید:")
        print("    pip install chromadb sentence-transformers")
        return None

    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)

    # استفاده از SentenceTransformerEmbeddingFunction لوکال
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=DEFAULT_EMBEDDING_MODEL
    )

    if rebuild:
        try:
            client.delete_collection(COLLECTION_NAME)
            print(f"[*] کالکشن قبلی '{COLLECTION_NAME}' حذف شد.")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"}
    )

    count = collection.count()
    if count > 0 and not rebuild:
        print(f"[i] ایندکس از قبل موجود است ({count} سند در ChromaDB). برای بازسازی از آرگومان --rebuild استفاده کنید.")
        return collection

    if chunks is None:
        chunks = load_all_documents()
    if not chunks:
        print("[!] هیچ محتوایی برای ایندکس پیدا نشد.")
        return collection

    # اضافه کردن به صورت Batch برای بهینه‌سازی حافظه و پردازش
    batch_size = 64
    total = len(chunks)
    print(f"[*] در حال امبدینگ و درج {total} چانک در پایگاه داده Chroma...")

    for i in range(0, total, batch_size):
        batch = chunks[i:i + batch_size]
        docs = [item[0] for item in batch]
        metas = [item[1] for item in batch]
        ids = [item[1]["chunk_id"] for item in batch]

        # جلوگیری از خطای شناسه‌های تکراری
        unique_ids = []
        seen = set()
        for idx_val, cid in enumerate(ids):
            final_id = cid
            dup_c = 1
            while final_id in seen:
                final_id = f"{cid}_{dup_c}"
                dup_c += 1
            seen.add(final_id)
            unique_ids.append(final_id)

        collection.add(
            documents=docs,
            metadatas=metas,
            ids=unique_ids
        )
        print(f"  -> پیشرفت: {min(i + batch_size, total)}/{total}")

    print("[+] ایندکس با موفقیت ساخته شد و ذخیره گردید.")
    return collection


def query_knowledge_base(query_text, n_results=4):
    """جستجوی معنایی و ارائه نتایج با استناد کامل"""
    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        print("[!] خطا: chromadb یا sentence-transformers نصب نیست.")
        return

    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=DEFAULT_EMBEDDING_MODEL
    )

    try:
        collection = client.get_collection(name=COLLECTION_NAME, embedding_function=embed_fn)
    except Exception:
        print("[!] ایندکسی یافت نشد. لطفاً ابتدا اسکریپت را برای ساخت ایندکس اجرا کنید:")
        print("    python step4_rag.py --index")
        return

    results = collection.query(
        query_texts=[query_text],
        n_results=n_results
    )

    print("\n" + "=" * 70)
    print(f"🔍 پرسش: {query_text}")
    print("=" * 70)

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    if not docs:
        print("❌ نتیجه‌ای یافت نشد.")
        return

    for idx, (doc, meta, dist) in enumerate(zip(docs, metas, distances), 1):
        similarity = 1.0 - dist if dist is not None else 0.0
        src_type = "📩 ایمیل" if meta.get("source_type") == "email" else "📎 پیوست"
        print(f"\n--- [ نتیجه {idx} ] | نوع: {src_type} | تشابه معنایی: {similarity:.2%} ---")
        if meta.get("source_type") == "email":
            print(f"📌 موضوع: {meta.get('subject', 'نامشخص')}")
            print(f"👤 فرستنده: {meta.get('sender', 'نامشخص')} | 📅 تاریخ: {meta.get('date_shamsi', 'نامشخص')}")
            print(f"📁 فایل: {meta.get('source_file')}")
        else:
            print(f"📎 نام پیوست: {meta.get('attachment_name', 'نامشخص')} (نوع: {meta.get('type')})")
            print(f"🔗 ایمیل مادر: {meta.get('parent_email', 'نامشخص')}")

        print("\n📄 بخش بازیابی‌شده:")
        print(doc)
        print("-" * 70)


def interactive_cli():
    """حلقه پرسش و پاسخ تعاملی در ترمینال"""
    print("==================================================================")
    print("🤖 سامانه جستجو و RAG آرشیو فنی بویلر فردوسی (لوکال - CPU)")
    print("   برای خروج عبارت 'exit' یا 'q' را وارد کنید.")
    print("==================================================================")
    
    while True:
        try:
            query = input("\n❓ سوال یا کلیدواژه جستجو را وارد کنید: ").strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit", "q"):
                print("خروج از سامانه.")
                break
            query_knowledge_base(query, n_results=3)
        except (KeyboardInterrupt, EOFError):
            print("\nپایان.")
            break


def parse_cli_args():
    parser = argparse.ArgumentParser(description="ساخت و جست‌وجوی RAG آرشیو فنی")
    parser.add_argument(
        "--dataset-dir",
        help="مسیر مجموعه خروجی، برای مثال Extracted_Data\\offline_msg",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--index", "-i", action="store_true", help="ساخت ایندکس در صورت نبود")
    action.add_argument("--rebuild", "-r", action="store_true", help="بازسازی کامل ایندکس")
    action.add_argument("--export-chunks", action="store_true", help="فقط ساخت rag_chunks.jsonl")
    action.add_argument("--query", "-q", nargs="+", help="جست‌وجوی معنایی")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_cli_args()
    if args.dataset_dir:
        configure_dataset(args.dataset_dir)

    if args.index:
        build_index(rebuild=False)
    elif args.rebuild:
        build_index(rebuild=True)
    elif args.export_chunks:
        export_chunks_jsonl()
    elif args.query:
        query_knowledge_base(" ".join(args.query))
    else:
        if not os.path.exists(CHROMA_PERSIST_DIR):
            print("[*] پایگاه داده یافت نشد؛ در حال ساخت ایندکس اولیه...")
            build_index(rebuild=False)
        interactive_cli()

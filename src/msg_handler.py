# -*- coding: utf-8 -*-
"""
ماژول اختصاصی پردازش و استخراج ایمیل‌های پیوست‌شده (.msg)
- خواندن فایل‌های .msg ذخیره‌شده در پوشه attachments
- استخراج فرستنده، گیرنده، تاریخ شمسی، موضوع، بدنه پیام
- ذخیره Markdown در پوشه emails/
- استخراج پیوست‌های درونی به پوشه attachments/ با نام‌گذاری یکتا
"""
import os
import re
import glob
import win32com.client
import step3_discovery as s3

def process_msg_attachments(att_dir, emails_dir, attachment_manifest=None, log_func=print):
    """
    بررسی تمام فایل‌های .msg در پوشه attachments:
    - ایجاد Markdown در emails_dir
    - استخراج پیوست‌های داخلی به att_dir
    - بروزرسانی attachment_manifest
    """
    if attachment_manifest is None:
        attachment_manifest = {}

    msg_files = glob.glob(os.path.join(att_dir, "*.msg"))
    if not msg_files:
        return 0

    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
    except Exception as e:
        log_func(f"[-] خطا در اتصال به Outlook برای پردازش MSG: {e}")
        return 0

    processed_msg_count = 0

    valid_extensions = {
        ".pdf", ".docx", ".doc", ".xlsx", ".xls",
        ".pptx", ".rar", ".zip", ".dwg", ".jpg", ".jpeg", ".png", ".msg"
    }

    for msg_path in msg_files:
        msg_filename = os.path.basename(msg_path)
        msg_stem, _ = os.path.splitext(msg_filename)

        # والد اولیه فایل msg
        parent_emails = attachment_manifest.get(msg_filename, [])
        parent_str = ", ".join(parent_emails) if parent_emails else "نامشخص"

        try:
            # باز کردن فایل .msg از طریق تمپلیت در Outlook
            abs_path = os.path.abspath(msg_path)
            msg_item = outlook.CreateItemFromTemplate(abs_path)

            subj = msg_item.Subject if msg_item.Subject else "(بدون موضوع)"
            subj = s3.COMPILED_SUBJECT_WARNING_REGEX.sub("", subj).strip()
            if not subj:
                subj = "(بدون موضوع)"

            sender = msg_item.SenderName if msg_item.SenderName else "نامشخص"
            to_rec = msg_item.To if msg_item.To else "ندارد"
            cc_rec = msg_item.CC if msg_item.CC else "ندارد"
            shamsi_date = s3.safe_extract_shamsi_date(msg_item)
            date_prefix = shamsi_date.replace("/", "")

            # استخراج پیوست‌های داخلی این پیام
            inner_attachments = []
            if msg_item.Attachments.Count > 0:
                for a_idx in range(1, msg_item.Attachments.Count + 1):
                    att = msg_item.Attachments.Item(a_idx)
                    orig_fn = att.FileName
                    ext = os.path.splitext(orig_fn)[1].lower()

                    if ext not in valid_extensions:
                        continue

                    # فیلتر تصاویر کوچک
                    if ext in {".jpg", ".jpeg", ".png"}:
                        if any(k in orig_fn.lower() for k in ["image", "signature", "logo", "outlookemoji"]):
                            if att.Size < 40 * 1024:
                                continue

                    clean_att_name = s3.sanitize_filename(orig_fn)
                    uniq_inner_name = f"{msg_stem}_att{a_idx}_{clean_att_name}"
                    inner_path = os.path.join(att_dir, uniq_inner_name)

                    try:
                        att.SaveAsFile(inner_path)
                        inner_attachments.append(uniq_inner_name)
                    except Exception as save_err:
                        log_func(f"  [!] خطا در ذخیره پیوست داخلی {orig_fn}: {save_err}")

            clean_body = s3.parse_and_clean_thread(msg_item.Body)
            att_list_str = "\n".join([f"- attachments/{f}" for f in inner_attachments]) if inner_attachments else "ندارد"

            md_content = f"""---
نوع سند: ایمیل پیوست‌شده (Embedded MSG)
ایمیل والد: {parent_str}
فایل منبع: {msg_filename}
موضوع: {subj.strip()}
فرستنده: {sender.strip()}
گیرنده اصلی (To): {to_rec.strip()}
رونوشت (Cc): {cc_rec.strip()}
تاریخ شمسی: {shamsi_date}
تعداد پیوست‌های داخلی: {len(inner_attachments)}
پیوست‌ها:
{att_list_str}
---

# متن ایمیل پیوست‌شده:

{clean_body}
"""
            safe_subj = s3.sanitize_filename(subj)
            safe_subj_name, _ = os.path.splitext(safe_subj)
            out_email_name = f"{msg_stem}_EMBEDDED_{safe_subj_name[:40]}.md"
            out_email_path = os.path.join(emails_dir, out_email_name)

            with open(out_email_path, "w", encoding="utf-8") as out_f:
                out_f.write(md_content)

            # ثبت ارتباط پیوست‌های درونی با این ایمیل جدید
            for inner_att in inner_attachments:
                if inner_att not in attachment_manifest:
                    attachment_manifest[inner_att] = []
                attachment_manifest[inner_att].append(out_email_name)

            processed_msg_count += 1
            log_func(f"  [+] استخراج ایمیل پیوست‌شده: {msg_filename} -> {out_email_name}")

        except Exception as e:
            log_func(f"  [-] خطا در پردازش فایل MSG {msg_filename}: {e}")

    return processed_msg_count

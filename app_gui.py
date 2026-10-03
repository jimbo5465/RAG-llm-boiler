# -*- coding: utf-8 -*-
"""
رابط کاربری انتخاب و استخراج خودکار پوشه‌های Outlook و تبدیل پیوست‌ها
"""
import os
import sys
import threading
import hashlib
import json
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import pythoncom
import win32com.client
import win32timezone

# ایمپورت توابع پردازش از اسکریپت‌های موجود
import step3_discovery as s3
import step3_5_attachments as s35
import google_drive_ocr as g_ocr
import msg_handler as msg_h
from project_paths import PROJECT_ROOT

VALID_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".pptx",
    ".rar",
    ".zip",
    ".dwg",
    ".jpg",
    ".jpeg",
    ".png",
    ".msg",
}


def save_item_attachments(item, email_idx, att_dir, valid_extensions, hash_to_filename, log_func=print):
    """ذخیره و یکتاسازی پیوست‌های یک آیتم با هش SHA-256"""
    saved_attachments = []
    if getattr(item, "Attachments", None) and item.Attachments.Count > 0:
        for a_idx in range(1, item.Attachments.Count + 1):
            temp_att_path = None
            try:
                att = item.Attachments.Item(a_idx)
                orig_fn = att.FileName
                ext = os.path.splitext(orig_fn)[1].lower()

                if ext not in valid_extensions:
                    continue

                if ext in {".jpg", ".jpeg", ".png"}:
                    if any(k in orig_fn.lower() for k in ["image", "signature", "logo", "outlookemoji"]):
                        if att.Size < 40 * 1024:
                            continue

                clean_att_name = s3.sanitize_filename(orig_fn)
                temp_att_fn = f"temp_{email_idx}_{a_idx}_{clean_att_name}"
                temp_att_path = os.path.join(att_dir, temp_att_fn)

                att.SaveAsFile(temp_att_path)
                with open(temp_att_path, "rb") as bf:
                    att_bytes = bf.read()
                file_hash = hashlib.sha256(att_bytes).hexdigest()

                if file_hash in hash_to_filename:
                    existing_fn = hash_to_filename[file_hash]
                    if os.path.exists(temp_att_path):
                        os.remove(temp_att_path)
                    saved_attachments.append(existing_fn)
                else:
                    shamsi_date = s3.safe_extract_shamsi_date(item)
                    date_prefix = shamsi_date.replace("/", "")
                    uniq_att_fn = f"{date_prefix}_{email_idx:03d}_{a_idx}_{clean_att_name}"
                    final_att_path = os.path.join(att_dir, uniq_att_fn)
                    if os.path.exists(final_att_path):
                        os.remove(final_att_path)
                    os.rename(temp_att_path, final_att_path)

                    hash_to_filename[file_hash] = uniq_att_fn
                    saved_attachments.append(uniq_att_fn)
            except Exception as e:
                if temp_att_path and os.path.exists(temp_att_path):
                    try:
                        os.remove(temp_att_path)
                    except Exception:
                        pass
                log_func(f"  [!] خطا در پردازش پیوست {getattr(att, 'FileName', '') if 'att' in locals() else ''}: {e}")
    return saved_attachments


class OutlookExtractorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("مدیریت و استخراج آرشیو ایمیل Outlook")
        self.root.geometry("850x650")

        self.outlook = None
        self.namespace = None
        self.root_archives = None
        self.node_map = {}  # mapping tree node -> folder COM object

        self.setup_ui()
        self.init_outlook()

    def setup_ui(self):
        # Frame بالا - درخت پوشه‌ها
        top_frame = ttk.LabelFrame(self.root, text="پوشه‌های آرشیو Outlook")
        top_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.tree = ttk.Treeview(top_frame)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(top_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self.on_folder_select)

        # Frame کنترل و گزینه‌ها
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill=tk.X, padx=10, pady=5)

        self.lbl_selected = ttk.Label(ctrl_frame, text="پوشه انتخاب‌شده: هیچ‌کدام", font=("Segoe UI", 9, "bold"))
        self.lbl_selected.pack(side=tk.LEFT, padx=5)

        ttk.Label(ctrl_frame, text="حداکثر پیام:").pack(side=tk.LEFT, padx=5)
        self.ent_limit = ttk.Entry(ctrl_frame, width=6)
        self.ent_limit.insert(0, "150")
        self.ent_limit.pack(side=tk.LEFT, padx=5)

        self.var_rollup = tk.BooleanVar(value=True)
        self.chk_rollup = ttk.Checkbutton(
            ctrl_frame,
            text="تجمیع زنجیره مکاتبات (Rollup)",
            variable=self.var_rollup,
            onvalue=True,
            offvalue=False,
        )
        self.chk_rollup.pack(side=tk.LEFT, padx=6)

        self.var_ocr = tk.BooleanVar(value=True)
        self.chk_ocr = ttk.Checkbutton(
            ctrl_frame,
            text="تبدیل PDFها با Google OCR",
            variable=self.var_ocr,
            onvalue=True,
            offvalue=False,
        )
        self.chk_ocr.pack(side=tk.LEFT, padx=6)

        self.btn_run = ttk.Button(
            ctrl_frame,
            text="شروع استخراج و تبدیل کامل",
            command=self.start_processing_thread,
            state=tk.DISABLED,
        )
        self.btn_run.pack(side=tk.RIGHT, padx=5)

        # Frame لاگ و خروجی متنی
        log_frame = ttk.LabelFrame(self.root, text="گزارش عملیات")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.txt_log = scrolledtext.ScrolledText(log_frame, height=12, state=tk.DISABLED, font=("Consolas", 9))
        self.txt_log.pack(fill=tk.BOTH, expand=True)

    def log(self, text):
        self.txt_log.config(state=tk.NORMAL)
        self.txt_log.insert(tk.END, text + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state=tk.DISABLED)

    def init_outlook(self):
        try:
            self.outlook = win32com.client.Dispatch("Outlook.Application")
            self.namespace = self.outlook.GetNamespace("MAPI")

            # پیدا کردن Archive
            for f in self.namespace.Folders:
                if "archive" in f.Name.lower():
                    self.root_archives = f
                    break

            if not self.root_archives and self.namespace.Folders.Count > 0:
                self.root_archives = self.namespace.Folders.Item(1)

            if self.root_archives:
                root_id = self.tree.insert("", "end", text=self.root_archives.Name, open=True)
                self.node_map[root_id] = self.root_archives
                self.populate_tree(root_id, self.root_archives)
            else:
                self.log("[-] هیچ ریشه ایمیلی در Outlook یافت نشد.")
        except Exception as e:
            self.log(f"[-] خطا در اتصال به Outlook: {e}")

    def populate_tree(self, parent_id, folder_obj):
        try:
            for sub_folder in folder_obj.Folders:
                sub_id = self.tree.insert(
                    parent_id,
                    "end",
                    text=f"{sub_folder.Name} ({sub_folder.Items.Count})",
                    open=False,
                )
                self.node_map[sub_id] = sub_folder
                if sub_folder.Folders.Count > 0:
                    self.populate_tree(sub_id, sub_folder)
        except Exception:
            pass

    def on_folder_select(self, event):
        selected_item = self.tree.selection()
        if not selected_item:
            return
        node_id = selected_item[0]
        folder = self.node_map.get(node_id)
        if folder:
            self.lbl_selected.config(text=f"پوشه انتخاب‌شده: {folder.Name} ({folder.Items.Count} پیام)")
            self.btn_run.config(state=tk.NORMAL)
        else:
            self.btn_run.config(state=tk.DISABLED)

    def start_processing_thread(self):
        selected_item = self.tree.selection()
        if not selected_item:
            return
        folder = self.node_map.get(selected_item[0])
        if not folder:
            return

        try:
            limit = int(self.ent_limit.get().strip())
        except ValueError:
            limit = 150

        entry_id = folder.EntryID
        store_id = folder.StoreID
        folder_name = folder.Name
        folder_path_str = folder.FolderPath
        use_ocr = bool(self.var_ocr.get())
        use_rollup = bool(self.var_rollup.get())

        self.btn_run.config(state=tk.DISABLED)
        thread = threading.Thread(
            target=self.run_pipeline,
            args=(entry_id, store_id, folder_name, folder_path_str, limit, use_ocr, use_rollup),
            daemon=True,
        )
        thread.start()

    def run_pipeline(self, entry_id, store_id, folder_name, folder_path_str, max_limit, use_ocr, use_rollup=True):
        pythoncom.CoInitialize()
        try:
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            target_folder = namespace.GetFolderFromID(entry_id, store_id)

            self.log("=" * 50)
            self.log(f"[+] شروع استخراج پوشه: {folder_name}")
            self.log(f"[+] تعداد کل پیام‌ها: {target_folder.Items.Count} | سقف استخراج: {max_limit}")
            self.log(f"[+] وضعیت تجمیع زنجیره مکاتبات (Rollup): {'فعال' if use_rollup else 'غیرفعال'}")
            self.log(f"[+] وضعیت Google OCR پیوست‌ها: {'فعال' if use_ocr else 'غیرفعال'}")

            total_items = target_folder.Items.Count
            items_to_process = min(total_items, max_limit)

            items = target_folder.Items
            items.Sort("[ReceivedTime]", False)

            processed_count = 0
            saved_att_total = 0

            # نام ایمن برای پوشه خروجی اختصاصی
            safe_folder_name = s3.sanitize_filename(folder_name)
            project_dir = PROJECT_ROOT
            
            # ساختار پوشه‌بندی اختصاصی در مسیر ثابت:
            # <PROJECT_ROOT>\Extracted_Data\<FolderName>\
            safe_folder_name_clean, _ = os.path.splitext(safe_folder_name)
            base_folder_out = os.path.join(project_dir, "Extracted_Data", safe_folder_name_clean)
            output_dir = os.path.join(base_folder_out, "emails")
            att_dir = os.path.join(output_dir, "attachments")
            att_text_dir = os.path.join(base_folder_out, "attachments_text")
            
            os.makedirs(output_dir, exist_ok=True)
            os.makedirs(att_dir, exist_ok=True)
            os.makedirs(att_text_dir, exist_ok=True)

            attachment_manifest = {}  # filename -> [list of parent email filenames]
            hash_to_filename = {}     # sha256 -> filename

            if use_rollup:
                self.log("[+] در حال سازماندهی پیام‌ها در قالب زنجیره‌های مکاتبه (Conversation Rollup)...")
                mail_items = []
                for item in items:
                    if len(mail_items) >= max_limit:
                        break
                    if getattr(item, "Class", 0) == 43:  # MailItem
                        mail_items.append(item)

                conv_groups = {}
                for it in mail_items:
                    try:
                        cid = getattr(it, "ConversationID", "")
                    except Exception:
                        cid = ""
                    if not cid:
                        try:
                            topic = getattr(it, "ConversationTopic", "")
                        except Exception:
                            topic = ""
                        raw_subj = topic if topic else (getattr(it, "Subject", "") or "")
                        clean_s = s3.clean_subject_for_thread(raw_subj)
                        if clean_s and clean_s != "بدون موضوع":
                            cid = f"SUBJ_{s3.normalize_string(clean_s)}"
                        else:
                            cid = f"ITEM_{it.EntryID}"
                    conv_groups.setdefault(cid, []).append(it)

                self.log(f"[+] تعداد {len(mail_items)} ایمیل در قالب {len(conv_groups)} زنجیره مکاتبه تفکیک شدند.")

                conv_idx = 0
                for cid, c_items in conv_groups.items():
                    conv_idx += 1
                    try:
                        conv_saved_atts = []
                        item_att_map = {}
                        for it in c_items:
                            atts = save_item_attachments(it, conv_idx, att_dir, VALID_EXTENSIONS, hash_to_filename, self.log)
                            item_att_map[it.EntryID] = atts
                            conv_saved_atts.extend(atts)

                        first_item = c_items[0]
                        last_item = c_items[-1]

                        first_shamsi = s3.safe_extract_shamsi_date(first_item)
                        last_shamsi = s3.safe_extract_shamsi_date(last_item)
                        date_prefix = last_shamsi.replace("/", "")
                        date_range_str = f"{first_shamsi} تا {last_shamsi}" if first_shamsi != last_shamsi else first_shamsi

                        raw_subj = getattr(last_item, "Subject", "") or getattr(first_item, "Subject", "") or "(بدون موضوع)"
                        conv_subj = s3.clean_subject_for_thread(raw_subj)
                        safe_subj = s3.sanitize_filename(conv_subj)
                        safe_subj_name, _ = os.path.splitext(safe_subj)
                        out_name = f"{date_prefix}_{conv_idx:03d}_{safe_subj_name[:50]}.md"
                        out_path = os.path.join(output_dir, out_name)

                        for att_fn in conv_saved_atts:
                            attachment_manifest.setdefault(att_fn, [])
                            if out_name not in attachment_manifest[att_fn]:
                                attachment_manifest[att_fn].append(out_name)

                        if len(c_items) == 1:
                            single_item = c_items[0]
                            sender = single_item.SenderName if single_item.SenderName else "نامشخص"
                            to_rec = single_item.To if single_item.To else "ندارد"
                            cc_rec = single_item.CC if single_item.CC else "ندارد"
                            clean_thread = s3.parse_and_clean_thread(single_item.Body)
                            att_list_str = "\n".join([f"- attachments/{f}" for f in conv_saved_atts]) if conv_saved_atts else "ندارد"

                            md_content = f"""---
شناسه: {single_item.EntryID[:25]}...
موضوع: {conv_subj}
فرستنده: {sender.strip()}
گیرنده اصلی (To): {to_rec.strip()}
رونوشت (Cc): {cc_rec.strip()}
تاریخ شمسی: {last_shamsi}
مسیر پوشه: {folder_path_str}
تعداد پیوست‌های معتبر ذخیره شده: {len(conv_saved_atts)}
پیوست‌ها:
{att_list_str}
---

# متن مکاتبه:

{clean_thread}
"""
                        else:
                            participants = set()
                            for it in c_items:
                                if getattr(it, "SenderName", None):
                                    participants.add(it.SenderName.strip())
                            part_str = "، ".join(sorted(participants))

                            messages = []
                            earlier_quotes = s3.extract_quotes_chronological(first_item.Body)
                            for q in earlier_quotes:
                                q_headers_str = "\n".join([f"> {h}" for h in q["headers"]])
                                messages.append({
                                    "type": "quote",
                                    "headers": q_headers_str,
                                    "body": q["body"],
                                    "atts": [],
                                })

                            for it in c_items:
                                s_name = it.SenderName if it.SenderName else "نامشخص"
                                to_name = it.To if it.To else "ندارد"
                                cc_name = it.CC if it.CC else "ندارد"
                                d_shamsi = s3.safe_extract_shamsi_date(it)
                                sub = it.Subject or conv_subj
                                b_text = s3.extract_latest_message_body(it.Body)
                                it_atts = item_att_map.get(it.EntryID, [])

                                messages.append({
                                    "type": "email",
                                    "from": s_name.strip(),
                                    "to": to_name.strip(),
                                    "cc": cc_name.strip(),
                                    "date": d_shamsi,
                                    "subject": sub.strip(),
                                    "body": b_text,
                                    "atts": it_atts,
                                })

                            total_msgs = len(messages)
                            rendered_msgs = []
                            for m_idx, m in enumerate(messages, 1):
                                if m["type"] == "quote":
                                    rendered_msgs.append(f"### 💬 پیام {m_idx} از {total_msgs} (سوابق نقل‌شده در مکاتبه)\n{m['headers']}\n\n{m['body']}")
                                else:
                                    badge = ""
                                    if m_idx == 1:
                                        badge = " (شروع مکاتبه)"
                                    elif m_idx == total_msgs:
                                        badge = " (آخرین پاسخ / نتیجه)"

                                    att_str = ""
                                    if m["atts"]:
                                        att_lines = "\n".join([f"- attachments/{f}" for f in m["atts"]])
                                        att_str = f"\n\n**📎 پیوست‌های این پیام:**\n{att_lines}"

                                    rendered_msgs.append(f"""### 💬 پیام {m_idx} از {total_msgs}{badge}
> **فرستنده:** {m['from']}  
> **گیرنده اصلی (To):** {m['to']}  
> **رونوشت (Cc):** {m['cc']}  
> **تاریخ شمسی:** {m['date']}  
> **موضوع:** {m['subject']}  

{m['body']}{att_str}""")

                            all_att_list_str = "\n".join([f"- attachments/{f}" for f in conv_saved_atts]) if conv_saved_atts else "ندارد"
                            all_messages_body = "\n\n---\n\n".join(rendered_msgs)

                            md_content = f"""---
نوع سند: زنجیره مکاتبه (Conversation Thread)
شناسه گفتگو: {cid}
موضوع: {conv_subj}
تعداد کل پیام‌ها: {total_msgs}
بازه زمانی شمسی: {date_range_str}
مشارکت‌کنندگان: {part_str}
مسیر پوشه: {folder_path_str}
تعداد کل پیوست‌های ذخیره شده: {len(conv_saved_atts)}
پیوست‌ها:
{all_att_list_str}
---

# زنجیره مکاتبه: {conv_subj}

{all_messages_body}
"""

                        with open(out_path, "w", encoding="utf-8") as f:
                            f.write(md_content)

                        processed_count += len(c_items)
                        saved_att_total += len(conv_saved_atts)
                        self.log(f"[{conv_idx}/{len(conv_groups)}] ذخیره شد ({len(c_items)} ایمیل): {conv_subj[:40]}")
                    except Exception as e:
                        self.log(f"[-] خطا در زنجیره {conv_idx}: {e}")

            else:
                # حالت تفکیک تک‌ایمیلی (Legacy Mode)
                for idx, item in enumerate(items, 1):
                    if processed_count >= max_limit:
                        break
                    if item.Class != 43:  # MailItem
                        continue

                    try:
                        subj = item.Subject if item.Subject else "(بدون موضوع)"
                        subj = s3.COMPILED_SUBJECT_WARNING_REGEX.sub("", subj).strip()
                        if not subj:
                            subj = "(بدون موضوع)"

                        sender = item.SenderName if item.SenderName else "نامشخص"
                        to_rec = item.To if item.To else "ندارد"
                        cc_rec = item.CC if item.CC else "ندارد"

                        shamsi_date = s3.safe_extract_shamsi_date(item)
                        date_prefix = shamsi_date.replace("/", "")

                        safe_subj = s3.sanitize_filename(subj)
                        safe_subj_name, _ = os.path.splitext(safe_subj)
                        out_name = f"{date_prefix}_{idx:03d}_{safe_subj_name[:50]}.md"
                        out_path = os.path.join(output_dir, out_name)

                        saved_attachments = save_item_attachments(item, idx, att_dir, VALID_EXTENSIONS, hash_to_filename, self.log)
                        saved_att_total += len(saved_attachments)
                        for att_fn in saved_attachments:
                            attachment_manifest.setdefault(att_fn, [])
                            if out_name not in attachment_manifest[att_fn]:
                                attachment_manifest[att_fn].append(out_name)

                        clean_thread = s3.parse_and_clean_thread(item.Body)
                        att_list_str = "\n".join([f"- attachments/{f}" for f in saved_attachments]) if saved_attachments else "ندارد"

                        md_content = f"""---
شناسه: {item.EntryID[:25]}...
موضوع: {subj.strip()}
فرستنده: {sender.strip()}
گیرنده اصلی (To): {to_rec.strip()}
رونوشت (Cc): {cc_rec.strip()}
تاریخ شمسی: {shamsi_date}
مسیر پوشه: {folder_path_str}
تعداد پیوست‌های معتبر ذخیره شده: {len(saved_attachments)}
پیوست‌ها:
{att_list_str}
---

# متن مکاتبه:

{clean_thread}
"""
                        with open(out_path, "w", encoding="utf-8") as f:
                            f.write(md_content)

                        processed_count += 1
                        self.log(f"[{processed_count}/{items_to_process}] استخراج شد: {safe_subj[:35]}")
                    except Exception as e:
                        self.log(f"[-] خطا در پیام {idx}: {e}")
                    self.log(f"[-] خطا در پیام {idx}: {e}")

            # ذخیره مانیفست پیوست‌ها
            manifest_json_path = os.path.join(base_folder_out, "attachment_manifest.json")
            with open(manifest_json_path, "w", encoding="utf-8") as mf:
                json.dump(attachment_manifest, mf, ensure_ascii=False, indent=2)

            self.log(f"\n[+] استخراج {processed_count} ایمیل و {saved_att_total} پیوست یکتا تمام شد.")

            # پردازش ایمیل‌های پیوست‌شده (.msg)
            self.log("[+] در حال بررسی و استخراج ایمیل‌های پیوست‌شده (.msg)...")
            try:
                msg_count = msg_h.process_msg_attachments(
                    att_dir=att_dir,
                    emails_dir=output_dir,
                    attachment_manifest=attachment_manifest,
                    log_func=self.log,
                )
                if msg_count > 0:
                    self.log(f"[+] تعداد {msg_count} ایمیل پیوست‌شده (.msg) با موفقیت استخراج شدند.")
                    # بروزرسانی مجدد فایل مانیفست پس از پردازش msg
                    with open(manifest_json_path, "w", encoding="utf-8") as mf:
                        json.dump(attachment_manifest, mf, ensure_ascii=False, indent=2)
            except Exception as e:
                self.log(f"[-] خطا در پردازش فایل‌های MSG: {e}")

            self.log("[+] در حال تبدیل پیوست‌های آفیس به Markdown (Step 3.5)...")
            try:
                stats = s35.process_attachments(
                    att_dir=att_dir,
                    md_dir=output_dir,
                    out_dir=att_text_dir,
                    attachment_manifest=attachment_manifest,
                )
                self.log(f"[+] تبدیل پیوست‌های آفلاین پایان یافت ({stats['md']} فایل).")
            except Exception as e:
                self.log(f"[-] خطا در پردازش پیوست‌های آفلاین: {e}")

            # تبدیل PDFها و تصاویر اسکن‌شده با Google OCR در صورت فعال بودن تیک
            if use_ocr:
                self.log("\n[+] در حال اجرای Google OCR برای کلیه PDFها و اسناد پیوست...")
                ocr_out_dir = os.path.join(base_folder_out, "attachments_ocr_google")
                try:
                    g_ocr.batch_convert_all(
                        att_dir,
                        ocr_out_dir,
                        force_overwrite=False,
                        log_func=self.log,
                        attachment_manifest=attachment_manifest,
                    )
                    self.log("[+] عملیات Google OCR با موفقیت تمام شد!")
                except Exception as e:
                    import traceback
                    err_details = traceback.format_exc()
                    self.log(f"[-] خطا در Google OCR: {e}\n{err_details}")
            else:
                self.log("\n[i] تبدیل Google OCR بر اساس تنظیمات غیرفعال بود (نادیده گرفته شد).")

            self.log(f"\n[+] پایان کل عملیات! مسیر خروجی:\n{base_folder_out}")
            messagebox.showinfo("اتمام عملیات", f"استخراج و تبدیل پوشه با موفقیت در مسیر زیر انجام شد:\n{base_folder_out}")
        finally:
            self.btn_run.config(state=tk.NORMAL)
            pythoncom.CoUninitialize()


if __name__ == "__main__":
    root = tk.Tk()
    app = OutlookExtractorGUI(root)
    root.mainloop()

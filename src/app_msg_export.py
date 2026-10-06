# -*- coding: utf-8 -*-
"""
ابزار استخراج خام ایمیل‌های Outlook با پسوند اصلی .msg
- نمایش درختی پوشه‌های Outlook (همه صندوق‌ها)
- انتخاب هر پوشه/دسته‌بندی و کلیک روی دکمه خروجی
- ذخیره تمام ایمیل‌های آن دسته به صورت فایل خام .msg روی دسکتاپ
"""
from project_paths import PROJECT_ROOT
import os
import re
import sys
import time
import queue
import threading
import traceback
import ctypes
import ctypes.wintypes
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

import pythoncom
import win32com.client


def write_crash_log(context=""):
    """ذخیره خطای بحرانی در فایل لاگ کنار برنامه (برای عیب‌یابی)."""
    try:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = PROJECT_ROOT
        log_path = os.path.join(base, "app_msg_export_error.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"=== CRASH {context} ===\n")
            f.write(traceback.format_exc())
            f.write("\n")
        return log_path
    except Exception:
        return None

# ثابت‌های SaveAs در Outlook (OlSaveAsType)
OL_MSG_UNICODE = 9  # فرمت .msg یونیکد (حفظ کامل فارسی)
MAIL_ITEM_CLASS = 43  # MailItem

INVALID_FILENAME_CHARS_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')

COLLECTED_WARNING_KEYWORDS = [
    "کلمه عبور", "رمز عبور", "پیوست حساس", "دسترسی محدود",
    "این ایمیل به صورت خودکار", "هشدار", "توجه", "اخطار",
]
COMPILED_SUBJECT_WARNING_REGEX = re.compile(
    r"^(?:" + "|".join(COLLECTED_WARNING_KEYWORDS) + r")\s*[:\-–]\s*",
    flags=re.IGNORECASE,
)


def sanitize_filename(name, max_len=100):
    name = str(name or "").strip()
    name = COMPILED_SUBJECT_WARNING_REGEX.sub("", name).strip()
    name = INVALID_FILENAME_CHARS_RE.sub("_", name).strip(" .")
    if not name:
        name = "(بدون موضوع)"
    return name[:max_len].strip(" .")


def get_desktop_path():
    """مسیر واقعی دسکتاپ (حتی اگر توسط OneDrive جابه‌جا شده باشد)."""
    try:
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        # CSIDL_DESKTOP = 0x0000
        res = ctypes.windll.shell32.SHGetFolderPathW(None, 0x0000, None, 0, buf)
        if res == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


class RawMsgExporterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("استخراج خام ایمیل‌ها با فرمت .msg")
        self.root.geometry("820x620")

        self.node_map = {}   # tree node id -> (entry_id, store_id, folder_name, count)
        self.ui_queue = queue.Queue()
        self.load_gen = 0    # نسخه عملیات بارگذاری (برای ابطال تلاش‌های قبلی)
        self.load_start = None
        self.loaded = False
        self.exporting = False
        self.export_start = None
        self.com_poisoned = False  # یک صندوق قطع باعث قفل اتصال Outlook شده

        self.setup_ui()
        self.root.after(100, self.poll_queue)
        self.root.after(300, self.start_load)

    # ---------- UI ----------
    def setup_ui(self):
        top_frame = ttk.LabelFrame(self.root, text="پوشه‌های Outlook (همه صندوق‌ها)")
        top_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.tree = ttk.Treeview(top_frame)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(top_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self.on_folder_select)

        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=10)

        self.lbl_status = ttk.Label(
            status_frame,
            text="در حال اتصال به Outlook...",
            font=("Segoe UI", 9, "bold"),
            foreground="#b26a00",
        )
        self.lbl_status.pack(side=tk.LEFT, padx=5)

        self.btn_retry = ttk.Button(
            status_frame,
            text="تلاش مجدد",
            command=self.start_load,
            state=tk.DISABLED,
        )
        self.btn_retry.pack(side=tk.RIGHT, padx=5)

        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill=tk.X, padx=10, pady=5)

        self.lbl_selected = ttk.Label(
            ctrl_frame,
            text="پوشه انتخاب‌شده: هیچ‌کدام",
            font=("Segoe UI", 9, "bold"),
        )
        self.lbl_selected.pack(side=tk.LEFT, padx=5)

        self.btn_export = ttk.Button(
            ctrl_frame,
            text="Export خام (.msg) به دسکتاپ",
            command=self.start_export,
            state=tk.DISABLED,
        )
        self.btn_export.pack(side=tk.RIGHT, padx=5)

        log_frame = ttk.LabelFrame(self.root, text="گزارش عملیات")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.txt_log = scrolledtext.ScrolledText(
            log_frame, height=10, state=tk.DISABLED, font=("Consolas", 9)
        )
        self.txt_log.pack(fill=tk.BOTH, expand=True)

    def log(self, text):
        self.txt_log.config(state=tk.NORMAL)
        self.txt_log.insert(tk.END, text + "\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state=tk.DISABLED)

    def set_status(self, text, color="#b26a00"):
        self.lbl_status.config(text=text, foreground=color)

    # ---------- صف پیام‌های ترد پس‌زمینه ----------
    def poll_queue(self):
        try:
            while True:
                event = self.ui_queue.get_nowait()
                self.handle_event(event)
        except queue.Empty:
            pass

        # تایمر وضعیت اتصال
        if not self.loaded and self.load_start is not None:
            elapsed = int(time.time() - self.load_start)
            if elapsed > 0 and self.load_gen > 0:
                if elapsed % 10 == 0:
                    self.set_status(
                        f"در حال اتصال به Outlook... ({elapsed} ثانیه) — بار اول ممکن است طول بکشد",
                        "#b26a00",
                    )

        # تایمر محافظ خروجی: اگر استخراج بیش از 90 ثانیه پاسخ نداد
        if self.exporting and self.export_start is not None:
            elapsed = int(time.time() - self.export_start)
            if elapsed > 90:
                self.exporting = False
                self.export_start = None
                self.btn_export.config(state=tk.NORMAL)
                self.log("[!] استخراج بیش از 90 ثانیه بدون پاسخ ماند — احتمالاً اتصال Outlook توسط صندوق قطع قفل شده.")
                self.log("[i] برنامه را ببندید، اتصال شبکه/Exchange را بررسی کنید و دوباره باز کنید.")
                self.set_status("استخراج بدون پاسخ ماند — برنامه را ببندید و دوباره باز کنید", "#c62828")

        self.root.after(250, self.poll_queue)

    def handle_event(self, event):
        kind = event[0]
        gen = event[1] if len(event) > 1 else None
        if gen is not None and gen != self.load_gen:
            return  # رویداد متعلق به تلاش قبلی است

        if kind == "log":
            self.log(event[2])
        elif kind == "store_progress":
            i, n = event[2]
            if not self.loaded:
                self.set_status(f"در حال خواندن صندوق {i} از {n}...", "#b26a00")
        elif kind == "tree":
            tree_data = event[2]
            self.tree.delete(*self.tree.get_children())
            self.node_map.clear()
            for parent_key, node_key, entry_id, store_id, name, count in tree_data:
                display = f"{name} ({count})" if count != "" else name
                if parent_key:
                    self.tree.insert(parent_key, "end", iid=node_key, text=display, open=False)
                else:
                    self.tree.insert("", "end", iid=node_key, text=display, open=False)
                self.node_map[node_key] = (entry_id, store_id, name, count)
            self.loaded = True
            self.load_start = None
            n_roots = len(self.tree.get_children())
            self.set_status(
                f"اتصال برقرار شد — {n_roots} صندوق یافت شد. یک پوشه را انتخاب کنید.",
                "#2e7d32",
            )
            self.btn_retry.config(state=tk.NORMAL)
            self.btn_retry.config(text="بارگذاری مجدد پوشه‌ها")
        elif kind == "load_error":
            msg = event[2]
            self.loaded = False
            self.load_start = None
            self.set_status(msg, "#c62828")
            self.btn_retry.config(state=tk.NORMAL)
        elif kind == "export_log":
            self.log(event[2])
        elif kind == "export_done":
            self.handle_export_done(event[2])
        elif kind == "poisoned":
            self.com_poisoned = True
            self.log("[i] توجه: چون یک صندوق قطع‌شده بود، اگر خروجی عمل نکرد برنامه را ببندید و بعد از وصل شدن شبکه دوباره باز کنید.")

    # ---------- بارگذاری پوشه‌ها ----------
    def start_load(self):
        self.load_gen += 1
        gen = self.load_gen
        self.loaded = False
        self.load_start = time.time()
        self.tree.delete(*self.tree.get_children())
        self.node_map.clear()
        self.btn_export.config(state=tk.DISABLED)
        self.btn_retry.config(state=tk.DISABLED)
        self.set_status("در حال اتصال به Outlook... (بار اول ممکن است ۴۰-۶۰ ثانیه طول بکشد)", "#b26a00")
        threading.Thread(target=self.load_folders_worker, args=(gen,), daemon=True).start()

    def load_folders_worker(self, gen):
        q = self.ui_queue
        try:
            pythoncom.CoInitialize()
            q.put(("log", gen, "اتصال به Outlook Application..."))
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            q.put(("log", gen, "اتصال برقرار شد. در حال خواندن لیست صندوق‌ها..."))

            stores = namespace.Stores
            n_stores = stores.Count
            if n_stores == 0:
                q.put(("load_error", gen, "هیچ صندوقی در Outlook یافت نشد"))
                q.put(("log", gen, "[-] هیچ صندوقی در Outlook یافت نشد."))
                return

            # مرحله ۱: فقط متادیتا (بدون دسترسی به پوشه‌ها؛ سریع و بدون قفل)
            meta = []  # (index, display_name)
            for i in range(1, n_stores + 1):
                try:
                    s = stores.Item(i)
                    try:
                        name = s.DisplayName
                    except Exception:
                        name = f"صندوق {i}"
                    meta.append((i, name))
                except Exception as e:
                    desc = str(e)
                    if "-2147221219" in desc or "Exchange" in desc:
                        q.put(("log", gen, f"[i] صندوق {i}: Exchange در دسترس نیست — نادیده گرفته شد."))
                    else:
                        q.put(("log", gen, f"[i] صندوق {i} قابل خواندن نیست: {desc[:80]}"))

            if not meta:
                q.put(("load_error", gen, "هیچ صندوق قابل دسترسی‌ای یافت نشد (شبکه/Exchange را بررسی کنید)"))
                return

            tree_data = []
            STORE_TIMEOUT = 30  # ثانیه؛ اگر صندوقی پاسخ نداد نادیده گرفته می‌شود

            def probe(res_box, idx):
                try:
                    pythoncom.CoInitialize()
                    out = win32com.client.Dispatch("Outlook.Application")
                    ns = out.GetNamespace("MAPI")
                    root_folder = ns.Stores.Item(idx).GetRootFolder()

                    def collect(folder_obj):
                        rows = []
                        try:
                            for sub in folder_obj.Folders:
                                try:
                                    count = sub.Items.Count
                                except Exception:
                                    count = "?"
                                rows.append((sub.EntryID, sub.StoreID, sub.Name, count))
                                if sub.Folders.Count > 0:
                                    rows.extend(collect(sub))
                        except Exception:
                            pass
                        return rows

                    rows = collect(root_folder)
                    res_box["ok"] = rows
                except Exception as e:
                    res_box["err"] = str(e)
                finally:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass

            timed_out = False
            for idx, name in meta:
                q.put(("log", gen, f"در حال خواندن پوشه‌های صندوق «{name}»..."))
                q.put(("store_progress", gen, (idx, len(meta))))
                result = {}

                t = threading.Thread(target=probe, args=(result, idx), daemon=True)
                t.start()
                t.join(timeout=STORE_TIMEOUT)

                if t.is_alive():
                    timed_out = True
                    q.put(("log", gen, f"[!] صندوق «{name}» در {STORE_TIMEOUT} ثانیه پاسخ نداد — نادیده گرفته شد. دکمه «تلاش مجدد» را بزنید."))
                    continue
                if "ok" in result:
                    rows = result["ok"]
                    node_key = f"node{idx}"
                    tree_data.append(("", node_key, "", "", name, ""))
                    for entry_id, store_id, sub_name, count in rows:
                        child_key = f"node{idx}_{len(tree_data)}"
                        tree_data.append((node_key, child_key, entry_id, store_id, sub_name, count))
                    q.put(("log", gen, f"[+] صندوق «{name}» با {len(rows)} زیرپوشه بارگذاری شد."))
                else:
                    q.put(("log", gen, f"[!] خطا در صندوق «{name}»: {result.get('err', 'نامشخص')[:100]}"))

            if not tree_data:
                q.put(("load_error", gen, "هیچ صندوق قابل دسترسی‌ای یافت نشد"))
                return

            q.put(("tree", gen, tree_data))
            q.put(("log", gen, f"[+] بارگذاری کامل: {len(tree_data)} پوشه."))
            if timed_out:
                q.put(("poisoned", gen, True))
        except Exception:
            log_path = write_crash_log("load_folders_worker")
            q.put(("load_error", gen, f"خطا در اتصال به Outlook (جزئیات: {log_path or 'لاگ'})"))
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    # ---------- انتخاب و استخراج ----------
    def on_folder_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        info = self.node_map.get(selected[0])
        if info:
            entry_id, store_id, name, count = info
            self.lbl_selected.config(text=f"پوشه انتخاب‌شده: {name} ({count} پیام)")
            if self.loaded and not self.exporting:
                self.btn_export.config(state=tk.NORMAL)

    def start_export(self):
        selected = self.tree.selection()
        if not selected:
            return
        info = self.node_map.get(selected[0])
        if not info:
            return
        entry_id, store_id, folder_name, _count = info
        if not entry_id:
            messagebox.showwarning(
                "غیرقابل استخراج",
                "صندوق اصلی قابل استخراج مستقیم نیست.\nیکی از زیرپوشه‌های داخل آن را انتخاب کنید.",
            )
            return

        self.exporting = True
        self.export_start = time.time()
        self.btn_export.config(state=tk.DISABLED)
        threading.Thread(
            target=self.run_export,
            args=(entry_id, store_id, folder_name),
            daemon=True,
        ).start()

    def run_export(self, entry_id, store_id, folder_name):
        q = self.ui_queue

        def log(text):
            q.put(("export_log", None, text))

        try:
            log("[*] آماده‌سازی اتصال به Outlook...")
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            log("[*] در حال یافتن پوشه هدف...")
            target_folder = namespace.GetFolderFromID(entry_id, store_id)

            desktop = get_desktop_path()
            log(f"[*] مسیر دسکتاپ: {desktop}")
            safe_dir = sanitize_filename(folder_name, max_len=60)
            out_dir = os.path.join(desktop, safe_dir)

            # جلوگیری از بازنویسی پوشه قبلی: پسوند عددی
            final_dir = out_dir
            counter = 1
            while os.path.exists(final_dir):
                counter += 1
                final_dir = f"{out_dir} ({counter})"
            os.makedirs(final_dir, exist_ok=True)

            total = target_folder.Items.Count
            log("=" * 50)
            log(f"[+] شروع استخراج خام پوشه: {folder_name}")
            log(f"[+] تعداد کل پیام‌ها: {total}")
            log(f"[+] مسیر خروجی: {final_dir}")

            items = target_folder.Items
            items.Sort("[ReceivedTime]", False)

            saved = 0
            skipped = 0
            failed = 0
            used_names = set()

            for idx in range(1, total + 1):
                item = items.Item(idx)
                try:
                    if item.Class != MAIL_ITEM_CLASS:
                        skipped += 1
                        continue

                    subj = item.Subject if item.Subject else "(بدون موضوع)"
                    safe_subj = sanitize_filename(subj)

                    try:
                        rt = item.ReceivedTime
                        date_prefix = rt.strftime("%Y-%m-%d")
                    except Exception:
                        date_prefix = "nodate"

                    base_name = f"{date_prefix}_{idx:04d}_{safe_subj[:60]}"
                    file_name = f"{base_name}.msg"
                    n = 1
                    while file_name.lower() in used_names:
                        n += 1
                        file_name = f"{base_name}_{n}.msg"
                    used_names.add(file_name.lower())

                    save_path = os.path.join(final_dir, file_name)
                    item.SaveAs(save_path, OL_MSG_UNICODE)
                    saved += 1

                    if saved % 20 == 0 or saved == total:
                        log(f"[{saved}/{total}] ... {file_name[:40]}")
                except Exception as e:
                    failed += 1
                    log(f"[-] خطا در پیام {idx}: {e}")

            log("")
            log(f"[+] تمام شد: {saved} فایل .msg ذخیره شد.")
            if skipped:
                log(f"[i] {skipped} آیتم غیر ایمیل (تقویم/گزارش و ...) نادیده گرفته شد.")
            if failed:
                log(f"[!] {failed} پیام با خطا مواجه شد.")
            log(f"[+] مسیر خروجی:\n{final_dir}")
            q.put(("export_done", None, (saved, failed, final_dir)))
        except Exception:
            log_path = write_crash_log("run_export")
            import traceback as tb
            log("[-] خطای کلی استخراج:")
            log(tb.format_exc())
            log(f"[-] جزئیات در: {log_path or 'لاگ'}")
            q.put(("export_done", None, (0, 1, "")))
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def handle_export_done(self, payload):
        self.exporting = False
        saved, failed, final_dir = payload
        self.btn_export.config(state=tk.NORMAL)
        if saved > 0:
            messagebox.showinfo(
                "اتمام عملیات",
                f"{saved} فایل .msg در مسیر زیر ذخیره شد:\n{final_dir}",
            )
        elif failed > 0:
            messagebox.showerror(
                "خطا",
                "استخراج با خطا مواجه شد. جزئیات در پنجره گزارش و فایل لاگ.",
            )
        else:
            messagebox.showinfo(
                "چیزی استخراج نشد",
                "هیچ ایمیل قابل استخراجی در این پوشه نبود (شاید همه آیتم‌ها غیر ایمیل بودند).",
            )


if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = RawMsgExporterGUI(root)
        root.mainloop()
    except Exception:
        write_crash_log("main")
        raise

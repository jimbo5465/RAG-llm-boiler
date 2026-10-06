# -*- coding: utf-8 -*-
"""انتخاب مسیرهای دلخواه برای استخراج MSG با روال تأییدشده پروژه."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from project_paths import PROJECT_ROOT
from msg_folder_runner import validate_paths, snapshot

BASE = Path(PROJECT_ROOT)
SETTINGS = BASE / 'msg_extractor_settings.json'


class ExtractorWindow:
    def __init__(self, window):
        self.window = window
        self.running = False
        self.events = queue.Queue()
        window.title('تبدیل ایمیل‌های MSG و پیوست‌ها')
        window.geometry('950x600')
        defaults = {'input': '', 'output': str(BASE / 'Extracted_Data')}
        try:
            saved = json.loads(SETTINGS.read_text(encoding='utf-8'))
            defaults.update({key: saved[key] for key in defaults if key in saved})
        except (OSError, ValueError, TypeError):
            pass
        self.values = {key: tk.StringVar(value=value) for key, value in defaults.items()}
        self.destination = tk.StringVar()
        self.status = tk.StringVar(value='پوشه ورودی و ریشه خروجی را انتخاب کنید.')
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        self.controls = []
        for row, (key, label) in enumerate([('input', 'پوشه ایمیل‌های MSG'), ('output', 'ریشه ذخیره خروجی')]):
            button = ttk.Button(frame, text='انتخاب…', command=lambda k=key: self.browse(k))
            button.grid(row=row, column=0, padx=6, pady=8)
            entry = ttk.Entry(frame, textvariable=self.values[key])
            entry.grid(row=row, column=1, sticky='ew')
            ttk.Label(frame, text=label).grid(row=row, column=2, padx=6)
            self.controls.extend([button, entry])
            self.values[key].trace_add('write', self.update_destination)
        ttk.Label(frame, textvariable=self.destination, wraplength=880).grid(row=2, column=0, columnspan=3, sticky='ew', pady=8)
        ttk.Label(frame, text='پوشه خروجی دقیقاً نام پوشه ورودی را دارد. خروجی موجود بازنویسی نمی‌شود.\nپردازش با Google OCR انجام می‌شود؛ Embedding و بسته NotebookLM ساخته نمی‌شوند.',
                  anchor='e').grid(row=3, column=0, columnspan=3, sticky='ew', pady=8)
        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, columnspan=3, sticky='e')
        for label, preview in [('بررسی مسیرها', True), ('شروع تبدیل', False)]:
            button = ttk.Button(actions, text=label, command=lambda p=preview: self.start(p))
            button.pack(side='right', padx=5)
            self.controls.append(button)
        repair_button = ttk.Button(actions, text='تکمیل RAR خروجی موجود', command=self.start_rar_repair)
        repair_button.pack(side='right', padx=5)
        self.controls.append(repair_button)
        ttk.Label(frame, textvariable=self.status).grid(row=5, column=0, columnspan=3, sticky='ew', pady=8)
        self.log = tk.Text(frame, state='disabled', wrap='word')
        self.log.grid(row=6, column=0, columnspan=3, sticky='nsew')
        scrollbar = ttk.Scrollbar(frame, command=self.log.yview)
        scrollbar.grid(row=6, column=3, sticky='ns')
        self.log.configure(yscrollcommand=scrollbar.set, exportselection=False)
        ttk.Button(actions, text='کپی کل لاگ', command=self.copy_all_log).pack(side='right', padx=5)
        self.log_menu = tk.Menu(self.log, tearoff=False)
        self.log_menu.add_command(label='کپی متن انتخاب‌شده', command=self.copy_selection)
        self.log_menu.add_command(label='انتخاب همه', command=self.select_all_log)
        self.log_menu.add_command(label='کپی کل لاگ', command=self.copy_all_log)
        self.log.bind('<Button-3>', self.show_log_menu)
        self.log.bind('<Control-KeyPress>', self.log_shortcut)
        frame.rowconfigure(6, weight=1)
        self.update_destination()
        window.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = window.after(150, self.poll)

    def update_destination(self, *_):
        source, root = (self.values[k].get().strip() for k in ('input', 'output'))
        self.destination.set(f'مسیر نهایی خروجی: {Path(root) / Path(source).name}' if source and root else 'مسیر نهایی پس از انتخاب پوشه‌ها نمایش داده می‌شود.')

    def browse(self, key):
        value = filedialog.askdirectory(title='انتخاب پوشه ورودی MSG' if key == 'input' else 'انتخاب ریشه خروجی')
        if value:
            self.values[key].set(value)

    def append(self, value):
        self.log.configure(state='normal')
        self.log.insert('end', value + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def copy_selection(self):
        if self.log.tag_ranges('sel'):
            self.window.clipboard_clear()
            self.window.clipboard_append(self.log.get('sel.first', 'sel.last'))
        return 'break'

    def copy_all_log(self):
        self.window.clipboard_clear()
        self.window.clipboard_append(self.log.get('1.0', 'end-1c'))
        return 'break'

    def select_all_log(self):
        self.log.focus_set()
        self.log.tag_add('sel', '1.0', 'end-1c')
        return 'break'

    def log_shortcut(self, event):
        # کد کلید ویندوز مستقل از زبان فارسی/انگلیسی صفحه‌کلید است.
        if event.keycode == 67 or event.keysym.lower() == 'c':
            return self.copy_selection()
        if event.keycode == 65 or event.keysym.lower() == 'a':
            return self.select_all_log()

    def show_log_menu(self, event):
        self.log.focus_set()
        try:
            self.log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.log_menu.grab_release()
        return 'break'

    def start(self, preview):
        config = {key: value.get().strip() for key, value in self.values.items()}
        try:
            if not all(config.values()):
                raise ValueError('هر دو مسیر را انتخاب کنید.')
            source, target = validate_paths(config['input'], config['output'])
        except ValueError as error:
            messagebox.showerror('مسیر نامعتبر', str(error))
            return
        try:
            SETTINGS.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError as error:
            self.append(f'ذخیره تنظیمات ممکن نشد: {error}')
        self.running = True
        for control in self.controls:
            control.configure(state='disabled')
        self.status.set('بررسی فایل‌ها…' if preview else 'استخراج و پردازش در جریان است…')
        self.append(f'ورودی: {source}\nخروجی: {target}')
        threading.Thread(target=self.worker, args=(source, config['output'], preview), daemon=True).start()

    def start_rar_repair(self):
        folder = filedialog.askdirectory(title='پوشه مجموعه خروجی موجود را انتخاب کنید — تکمیل با Google OCR')
        if not folder:
            return
        dataset = Path(folder)
        if not (dataset / 'attachment_manifest.json').is_file() or not (dataset / 'emails/attachments').is_dir():
            messagebox.showerror('خروجی نامعتبر', 'پوشه خود مجموعه را انتخاب کنید؛ باید emails و attachment_manifest.json داشته باشد.')
            return
        self.running = True
        for control in self.controls:
            control.configure(state='disabled')
        self.status.set('تکمیل RAR با Google OCR؛ خروجی‌های متنی موجود حفظ می‌شوند…')
        self.append(f'تکمیل فقط RAR: {dataset}')
        threading.Thread(target=self.worker, args=(dataset, '', False, True), daemon=True).start()

    def worker(self, source, output, preview, repair=False):
        try:
            if preview:
                count = len(snapshot(source))
                if not count:
                    raise ValueError('هیچ فایل MSG پیدا نشد.')
                self.events.put(('line', f'{count} فایل MSG؛ مسیرها معتبرند. بررسی اتصال گوگل هنگام شروع تبدیل انجام می‌شود.'))
                code = 0
            else:
                executable = Path(sys.executable)
                if executable.name.lower() == 'pythonw.exe':
                    executable = executable.with_name('python.exe')
                command = ([str(executable), '-u', str(BASE / 'tools/recover_rar_attachments.py'),
                            '--dataset-dir', str(source)] if repair else
                           [str(executable), '-u', str(BASE / 'src/msg_folder_runner.py'),
                            '--input', str(source), '--output-root', output])
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', errors='replace',
                    env=dict(os.environ, PYTHONIOENCODING='utf-8'),
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                for line in process.stdout:
                    self.events.put(('line', line.rstrip()))
                code = process.wait()
            self.events.put(('done', (code, preview)))
        except Exception as error:
            self.events.put(('line', str(error)))
            self.events.put(('done', (1, preview)))

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'line':
                    self.append(value)
                else:
                    code, preview = value
                    self.running = False
                    for control in self.controls:
                        control.configure(state='normal')
                    self.status.set(('بررسی مسیرها تمام شد.' if preview else 'تبدیل تمام شد؛ گزارش کیفیت و لاگ را بررسی کنید.') if code == 0 else 'اجرا با خطا پایان یافت؛ جزئیات در زیر آمده است.')
        except queue.Empty:
            pass
        self.poll_id = self.window.after(150, self.poll)

    def close(self):
        if self.running:
            messagebox.showinfo('اجرا در جریان است', 'پس از پایان پردازش پنجره را ببندید.')
        else:
            self.window.after_cancel(self.poll_id)
            self.window.destroy()


if __name__ == '__main__':
    window = tk.Tk()
    ExtractorWindow(window)
    window.mainloop()

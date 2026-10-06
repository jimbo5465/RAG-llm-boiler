# -*- coding: utf-8 -*-
"""پنجره اجرایی تجمیع Markdown با روال مصوب پروژه."""
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from project_paths import PROJECT_ROOT
from msg_extractor_gui import ExtractorWindow
from notebooklm_folder_runner import validate_paths

BASE = Path(PROJECT_ROOT)


class BundlerWindow(ExtractorWindow):
    # رفتار انتخاب و کپی لاگ و بستن امن پنجره با برنامه استخراج مشترک است.
    def __init__(self, window):
        self.window = window
        self.running = False
        self.events = queue.Queue()
        window.title('تجمیع Markdown ایمیل‌ها و پیوست‌ها')
        window.geometry('980x620')
        self.values = {'input': tk.StringVar(), 'output': tk.StringVar(value=str(BASE / 'Extracted_Data' / 'NotebookLM_Bundles'))}
        self.destination = tk.StringVar()
        self.status = tk.StringVar(value='پوشه مجموعه و ریشه خروجی را انتخاب کنید.')
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)
        self.controls = []
        for row, (key, label) in enumerate([('input', 'پوشه مجموعه ایمیل‌ها'), ('output', 'ریشه ذخیره بسته‌ها')]):
            button = ttk.Button(frame, text='انتخاب…', command=lambda k=key: self.browse(k))
            button.grid(row=row, column=0, padx=6, pady=8)
            entry = ttk.Entry(frame, textvariable=self.values[key])
            entry.grid(row=row, column=1, sticky='ew')
            ttk.Label(frame, text=label).grid(row=row, column=2, padx=6)
            self.controls.extend([button, entry])
            self.values[key].trace_add('write', self.update_destination)
        ttk.Label(frame, textvariable=self.destination, wraplength=920).grid(row=2, column=0, columnspan=3, sticky='ew', pady=8)
        ttk.Label(frame, text='ترتیب تاریخی؛ متن هر پیوست زیر ایمیل والد؛ بدون خلاصه‌سازی.\nسقف هر بخش: ۲۰۰ هزار کلمه یا ۵۰ مگابایت. ایمیل و پیوست‌هایش با هم حفظ می‌شوند.\nنام پوشه و فایل خروجی از نام ورودی گرفته می‌شود؛ بخش‌های متعدد شماره دارند.',
                  justify='right').grid(row=3, column=0, columnspan=3, sticky='e', pady=8)
        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, columnspan=3, sticky='ew')
        start = ttk.Button(actions, text='شروع تجمیع', command=self.start)
        start.pack(side='right', padx=5)
        self.controls.append(start)
        ttk.Button(actions, text='کپی کل لاگ', command=self.copy_all_log).pack(side='right', padx=5)
        ttk.Label(actions, textvariable=self.status).pack(side='left')
        self.log = tk.Text(frame, state='disabled', wrap='word', exportselection=False)
        self.log.grid(row=5, column=0, columnspan=3, sticky='nsew')
        scroll = ttk.Scrollbar(frame, command=self.log.yview)
        scroll.grid(row=5, column=3, sticky='ns')
        self.log.configure(yscrollcommand=scroll.set)
        self.log_menu = tk.Menu(self.log, tearoff=False)
        self.log_menu.add_command(label='کپی متن انتخاب‌شده', command=self.copy_selection)
        self.log_menu.add_command(label='انتخاب همه', command=self.select_all_log)
        self.log_menu.add_command(label='کپی کل لاگ', command=self.copy_all_log)
        self.log.bind('<Button-3>', self.show_log_menu)
        self.log.bind('<Control-KeyPress>', self.log_shortcut)
        self.update_destination()
        window.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = window.after(150, self.poll)

    def browse(self, key):
        value = filedialog.askdirectory(title='انتخاب پوشه مجموعه' if key == 'input' else 'انتخاب ریشه خروجی بسته‌ها')
        if value:
            self.values[key].set(value)

    def start(self):
        try:
            values = {k: v.get().strip().strip('"') for k, v in self.values.items()}
            if not all(values.values()):
                raise ValueError('هر دو مسیر را وارد کنید.')
            source, target = validate_paths(values['input'], values['output'])
        except ValueError as error:
            messagebox.showerror('مسیر نامعتبر', str(error))
            return
        self.running = True
        for control in self.controls:
            control.configure(state='disabled')
        self.status.set('تجمیع در جریان است…')
        self.append(f'ورودی: {source}\nخروجی: {target}')
        threading.Thread(target=self.worker, args=(source, values['output']), daemon=True).start()

    def worker(self, source, output):
        try:
            executable = Path(sys.executable)
            if executable.name.lower() == 'pythonw.exe':
                executable = executable.with_name('python.exe')
            process = subprocess.Popen([str(executable), '-u', str(BASE / 'src/notebooklm_folder_runner.py'),
                                        '--input', str(source), '--output-root', output],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                errors='replace', env=dict(os.environ, PYTHONIOENCODING='utf-8'),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for line in process.stdout:
                self.events.put(('line', line.rstrip()))
            code = process.wait()
        except Exception as error:
            self.events.put(('line', str(error)))
            code = 1
        self.events.put(('done', (code, False)))

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'line':
                    self.append(value)
                else:
                    code, _ = value
                    self.running = False
                    for control in self.controls:
                        control.configure(state='normal')
                    self.status.set('تجمیع تمام شد.' if code == 0 else 'تجمیع با خطا متوقف شد؛ لاگ را بررسی کنید.')
        except queue.Empty:
            pass
        self.poll_id = self.window.after(150, self.poll)


if __name__ == '__main__':
    window = tk.Tk()
    BundlerWindow(window)
    window.mainloop()

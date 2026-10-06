# -*- coding: utf-8 -*-
"""رابط محلی انتخاب مسیرها برای جمع‌آوری اصل مدارک دانش."""
from project_paths import PROJECT_ROOT
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

BASE = Path(PROJECT_ROOT)
SETTINGS = BASE / 'knowledge_collector_settings.json'


class CollectorWindow:
    def __init__(self, window):
        self.window = window
        window.title('جمع‌آوری اصل مدارک دانش')
        window.geometry('900x540')
        window.minsize(760, 480)
        self.events = queue.Queue()
        self.running = False
        defaults = {'input': str(BASE / 'درس اموخته و ثبت پیشنهادات فنی'),
                    'output': str(BASE / 'درس اموخته و ثبت پیشنهادات فنی/دانش'),
                    'archive': str(BASE), 'manifest': '', 'msg_input': ''}
        try:
            defaults.update(json.loads(SETTINGS.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            pass
        self.values = {key: tk.StringVar(value=value) for key, value in defaults.items()}
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text='گزارش‌های Word و اصل منابع را در پوشه‌های موضوعی جمع‌آوری کنید.', anchor='e').grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 12))
        labels = [('input', 'پوشه گزارش‌های Word'), ('output', 'پوشه خروجی دانش'),
                  ('archive', 'ریشه آرشیو ایمیل و ضمائم'), ('manifest', 'نقشه ارجاع NotebookLM'),
                  ('msg_input', 'پوشه MSGهای اصلی — اختیاری')]
        self.controls = []
        for row, (key, label) in enumerate(labels, 1):
            button = ttk.Button(frame, text='انتخاب…', command=lambda k=key: self.browse(k))
            button.grid(row=row, column=0, padx=(0, 8), pady=5)
            entry = ttk.Entry(frame, textvariable=self.values[key])
            entry.grid(row=row, column=1, sticky='ew', pady=5)
            ttk.Label(frame, text=label, anchor='e').grid(row=row, column=2, padx=(8, 0), pady=5)
            self.controls.extend([button, entry])
        ttk.Label(frame, text='ریشه آرشیو مبنای مسیرهای نقشه ارجاع است. نقشه باید متعلق به همان بسته‌ای باشد که به NotebookLM داده‌اید.', anchor='e', wraplength=840).grid(row=6, column=0, columnspan=3, sticky='ew', pady=8)
        actions = ttk.Frame(frame)
        actions.grid(row=7, column=0, columnspan=3, sticky='e', pady=8)
        for label, preview in [('بررسی بدون کپی', True), ('جمع‌آوری مدارک', False)]:
            button = ttk.Button(actions, text=label, command=lambda p=preview: self.start(p))
            button.pack(side='right', padx=4)
            self.controls.append(button)
        self.status = tk.StringVar(value='مسیرها را انتخاب کنید؛ خروجی‌های قبلی بازنویسی نمی‌شوند.')
        ttk.Label(frame, textvariable=self.status, anchor='e').grid(row=8, column=0, columnspan=3, sticky='ew')
        self.log = tk.Text(frame, height=12, wrap='word', state='disabled')
        self.log.grid(row=9, column=0, columnspan=3, sticky='nsew', pady=(8, 0))
        frame.rowconfigure(9, weight=1)
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.after(150, self.poll)

    def browse(self, key):
        if key == 'manifest':
            value = filedialog.askopenfilename(title='انتخاب bundle_manifest.json همان بسته NotebookLM', filetypes=[('JSON', '*.json')])
        else:
            value = filedialog.askdirectory(title={'input': 'گزارش‌های Word', 'output': 'خروجی دانش',
                                                  'archive': 'ریشه آرشیو', 'msg_input': 'MSGهای اصلی'}[key])
        if value:
            self.values[key].set(value)
            if key == 'archive':
                self.values['manifest'].set('')

    def append(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def start(self, preview):
        config = {key: value.get().strip() for key, value in self.values.items()}
        if not all(config.get(key) for key in ('input', 'output', 'archive')):
            messagebox.showerror('مسیر ناقص', 'پوشه گزارش‌ها، خروجی دانش و ریشه آرشیو را انتخاب کنید.')
            return
        if not Path(config['input']).is_dir() or not Path(config['archive']).is_dir():
            messagebox.showerror('مسیر نامعتبر', 'پوشه ورودی و ریشه آرشیو باید وجود داشته باشند.')
            return
        if not config['manifest']:
            from collect_knowledge_sources import source_manifest
            try:
                config['manifest'] = str(source_manifest(Path(config['archive'])))
                self.values['manifest'].set(config['manifest'])
            except ValueError as error:
                messagebox.showerror('انتخاب نقشه ارجاع', str(error))
                return
        SETTINGS.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        executable = Path(sys.executable)
        if executable.name.lower() == 'pythonw.exe':
            executable = executable.with_name('python.exe')
        command = [str(executable), '-u', str(BASE / 'src/collect_knowledge_sources.py'),
                   '--input', config['input'], '--output', config['output'],
                   '--archive', config['archive'], '--manifest', config['manifest']]
        if config['msg_input']:
            command.extend(['--msg-input', config['msg_input']])
        if preview:
            command.append('--dry-run')
        self.running = True
        for control in self.controls:
            control.configure(state='disabled')
        self.status.set('بررسی منابع و شناسه ایمیل‌های اصلی…')
        self.append('بررسی بدون کپی' if preview else 'جمع‌آوری مدارک')
        threading.Thread(target=self.worker, args=(command,), daemon=True).start()

    def worker(self, command):
        try:
            import os
            environment = dict(os.environ, PYTHONIOENCODING='utf-8')
            result = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, encoding='utf-8', env=environment,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for line in result.stdout:
                self.events.put(('line', line.strip()))
            self.events.put(('done', result.wait()))
        except Exception as error:
            self.events.put(('line', str(error)))
            self.events.put(('done', 1))

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'done':
                    self.running = False
                    for control in self.controls:
                        control.configure(state='normal')
                    self.status.set('تمام شد؛ موارد نیازمند بررسی در فهرست زیر و گزارش خروجی ثبت شده‌اند.' if value == 0 else 'اجرا ناموفق بود؛ خطا را در فهرست زیر ببینید.')
                else:
                    try:
                        record = json.loads(value)
                        if 'report' in record:
                            state = 'بدون تغییر؛ کپی مجدد لازم نیست' if record.get('status') == 'unchanged' else 'آماده'
                            self.append(f"{record['report']} | {state} | {record['files']} منبع | {len(record['unresolved'])} مورد نیازمند بررسی")
                            for item in record['unresolved']:
                                self.append(f"  {item['reference']}: {item['reason']}")
                            continue
                    except ValueError:
                        pass
                    self.append(value)
        except queue.Empty:
            pass
        self.window.after(150, self.poll)

    def close(self):
        if self.running:
            messagebox.showinfo('اجرا در جریان است', 'پس از پایان جمع‌آوری، پنجره را ببندید.')
        else:
            self.window.destroy()


if __name__ == '__main__':
    app = tk.Tk()
    CollectorWindow(app)
    app.mainloop()

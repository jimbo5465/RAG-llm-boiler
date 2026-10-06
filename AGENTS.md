# Context & Rules for AI Agents

## 1. قوانین محیط و Shell (بسیار مهم)

- **محیط خط فرمان:** فقط `cmd.exe`. هرگز PowerShell استفاده نشود (توسط Group Policy سازمانی بلاک است: `This program is blocked by group policy`).
- **یونیکد / فارسی:** دستورات CMD کدپیج فارسی ندارند (نام فایل‌ها `???` می‌شوند). هرگونه خواندن، نوشتن یا پردازش فایل‌های دارای نام فارسی فقط از طریق اسکریپت‌های پایتون با انکودینگ UTF-8 انجام شود.
- **اجرای پایتون:** همیشه متغیر محیطی ست شود: `set PYTHONIOENCODING=utf-8 && python <script>.py`

## 2. مشخصات پروژه

- **نام:** RAG LLM — پایگاه دانش ایمیل‌های فنی بویلر نیروگاه فردوسی
- **هدف:** تبدیل مکاتبات ایمیلی و پیوست‌ها به آرشیو متنی تمیز و آماده RAG لوکال با هزینه صفر.
- **زبان مستندات و خروجی‌ها:** فارسی.

## 3. ساختار فعلی پروژه و داده‌ها

- `src/`: کد برنامه؛ `tests/`: آزمون‌ها؛ `tools/`: بررسی و بازیابی؛ `docs/`: مستندات؛ `packaging/`: تنظیمات ساخت EXE.
- ریشه داده‌ها از `src/project_paths.py` گرفته می‌شود؛ محل سورس را با محل داده اشتباه نگیرید.
- `Run_MSG_Extractor.bat`: ورودی MSG و مقصد دلخواه، بدون Embedding؛ `Run_NotebookLM_Bundler.bat`: ساخت بسته؛ `Run_Knowledge_Collector.bat`: جمع‌آوری اصل مدارک کنار گزارش Word.
- `Run_Outlook_Extractor.bat` مسیر قبلی CLI روی MSG با OCR و RAG است؛ اتصال مستقیم Outlook در `src/app_gui.py` قرار دارد.
- `Extracted_Data/<dataset>/` پیش‌فرض مجموعه‌هاست؛ مسیر خارجی نیز در برنامه‌های پنجره‌ای ممکن است. `final` نام مجموعه تاریخی است.
- `emails/attachments/` اصل ضمائم، `attachments_text/` و `attachments_ocr_google/` متن استخراج‌شده‌اند. اصل MSG ورودی باید حفظ شود.
- `bundle_manifest.json` مرجع شناسه‌های همان بسته NotebookLM است؛ `attachment_manifest.json` والدهای پیوست و گزارش اجرا مسیر ورودی را نگه می‌دارد.
- خروجی دانش پوشه موضوع با Word و اصل PDF/Excel/Word/MSG است؛ ZIP و Markdown منبع تحویل داده نمی‌شوند.
- خروجی‌های قدیمی `Extracted_Sample/` و `Extracted_Sample_text/` حفظ شده‌اند؛ داده‌های خصوصی و اطلاعات ورود وارد Git نشوند. `.gitignore` مسیرهای خارجی یا پوشه‌های خصوصی تازه را خودکار پوشش نمی‌دهد.
- راهنمای جاری: `README.md` و `docs/INDEX_FA.md`. سند Word تعریف مسئله نسخه تاریخی ۰٫۱ است.

## 4. وابستگی‌ها و اجرا

در CMD از ریشه پروژه:

```bat
set PYTHONIOENCODING=utf-8
py -3 -m pip install -r requirements.txt
```

MSG به `extract-msg` و RAR به `rarfile` و ابزار UnRAR نیاز دارد. `pywin32` برای مسیر مستقیم Outlook ویندوز است. OCR منتخب به OAuth گوگل و شبکه وابسته است؛ همه مراحل کاملاً آفلاین نیستند.

RAG اختیاری:

```bat
set PYTHONIOENCODING=utf-8
py -3 -m pip install chromadb sentence-transformers
```

`langchain` وابستگی لازم کد RAG فعلی نیست. اجرای آزمون‌ها: `py -3 -m unittest discover -s tests`. اجرای ابزارهای نمونه یا OCR واقعی از آزمون واحد جدا باشد.

## 5. کنوانسیون‌های کدنویسی

- پایتون 3.10+
- تمام فایل‌های پایتون با هدر `# -*- coding: utf-8 -*-`
- استفاده از توابع اختصاصی نرمال‌سازی حروف فارسی (`ي` به `ی`، `ك` به `ک`، مدیریت نیم‌فاصله)
- عدم استفاده از سرویس‌های ابری پولی، APIهای تجاری، یا وابستگی به کارت گرافیک مجزا (طراحی شده برای اجرای CPU لوکال).

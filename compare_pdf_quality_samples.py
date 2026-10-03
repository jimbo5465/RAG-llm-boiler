# -*- coding: utf-8 -*-
"""گزارش مقایسهٔ دو نمونه با اعداد شاخصی که از تصویر اصلی بازبینی شدند."""
import json
import re
from run_pdf_quality_samples import NAMES, OUTPUT_DIR, ROOT
from pdf_ocr_quality import compact, text_only

references = {
    NAMES[0]: {3: ['BOLT GAL', '1060', 'A490M']},
    NAMES[1]: {
        1: ['23862', '23855', '23852', '22440'],
        5: ['23862', '23865', '23850', '22440', '22466', '22452'],
        7: ['23983', '23984', '23971', '22570', '22555', '22560'],
        8: ['24070', '24099', '24076', '22570', '22571', '22585'],
        10: ['24192', '24221', '24204', '22700', '22695', '22713'],
        11: ['24106', '24091', '24111', '22700', '22687', '22688'],
    },
}

rows = ['# نتیجهٔ آزمون واقعی دو PDF', '',
        'تاریخ: ۱۴۰۵/۰۷/۰۹ (۲۰۲۶/۱۰/۰۱)', '',
        '۱۶ آزمون محلی گذشت. دو PDF اصلی تغییر نکرده‌اند. تمام صفحات انتخاب‌شده به گوگل ارسال شدند.',
        'وجود شناسه‌های آغاز و پایان فقط حضور صفحات را تأیید می‌کند؛ کامل بودن محتوای هر صفحه را تضمین نمی‌کند.', '',
        '## مشاهدات', '',
        '- فایل اول: متن فارسی دو فرم نسبت به خروجی قبلی خواناتر شده است. چرخش صفحهٔ سوم اصلاح شد. ارسال یکجای PDF بخشی از Packing List را جا انداخت؛ تلاش مستقل صفحهٔ سوم عنوان، BOLT GAL و مقدار 1060 را بازیابی کرد.',
        '- فایل دوم: نقشه‌های صفحات ۲، ۴ و ۶ هنوز بسیار ناقص‌اند. صفحات ۱، ۳ و ۵ با OCR مستقل بهتر شدند. جدول‌های عددی هنوز باید با تصویر اصل تطبیق داده شوند.',
        '- هر دو خروجی WARNING هستند. کاربر در ۱۴۰۵/۰۷/۰۹ این سطح کیفیت را کافی و روال را تأیید کرد؛ متن خوانا به‌عنوان توضیح تکمیلی ایمیل برای RAG پذیرفته می‌شود. متن خام اولیه و هر تلاش مجدد جداگانه نگهداری شده‌اند.', '',
        '## وجود عبارت‌ها و اعداد شاخص', '',
        'این جدول فقط وجود مقدار را بررسی می‌کند، نه صحت جایگاه آن در سطر و ستون. مرجع‌های این آزمون از تصویر نمونه‌ها انتخاب شده‌اند؛ این قابلیت، اعتبارسنجی عمومی اعداد همهٔ اسناد نیست.', '',
        '| فایل | صفحه | مقدارهای گمشده از خروجی نهایی |',
        '| --- | --- | --- |']

results = []
summaries = []
for name in NAMES:
    stem = name[:-4]
    diagnostics = OUTPUT_DIR / '_ocr_diagnostics' / stem
    content = text_only((OUTPUT_DIR / (stem + '.md')).read_text(encoding='utf-8'))
    report = json.loads((diagnostics / 'quality.json').read_text(encoding='utf-8'))
    sections = re.split(r'^## صفحه (\d+)\s*$', content, flags=re.M)
    pages = {int(sections[i]): sections[i+1] for i in range(1, len(sections), 2)}
    checks = []
    for number, expected in references[name].items():
        text = compact(pages.get(number, ''))
        missing = [value for value in expected if compact(value) not in text]
        rows.append(f"| {stem} | {number} | {', '.join(missing) or 'همهٔ مقادیر شاخص حاضرند؛ ساختار جدول تأیید نشده'} |")
        checks.append({'page': number, 'expected': expected, 'missing': missing})
    request_count = 1 + len(list(diagnostics.glob('retry_page_*.txt')))
    results.append({'file': name, 'status': report['status'], 'requests_with_saved_response': request_count, 'reference_checks': checks})
    summaries.append(f"فایل `{name}`: {report['source']['processed']} از {report['source']['total']} صفحه؛ وضعیت {report['status']}؛ {request_count} پاسخ گوگل ذخیره شده است.")

rows.extend(['', *summaries, ''])
rows.extend(['## محدودیت‌های پیاده‌سازی فعلی', '',
             '- رندر ۳۰۰ DPI اطلاعات گم‌شدهٔ اسکن کم‌کیفیت را بازسازی نمی‌کند.',
             '- چرخش از جهت خطوط موجود حدس زده می‌شود؛ تشخیص مستقل جهت و کجی از تصویر هنوز عمومی نیست.',
             '- کنترل کیفیت قواعد اولیه دارد و صحت معنی، نام افراد، کد کالا و اعداد را تضمین نمی‌کند.',
             '- طبق تأیید کاربر، این سطح کیفیت کافی است؛ توسعهٔ بیشتر PDF فعلاً متوقف شده و تمرکز آزمون بعدی روی ایمیل است.',
             '- تقسیم سند به بسته‌های چندصفحه‌ای انجام نشده؛ درخواست اضافه فقط برای صفحهٔ مردود بوده است.'])
(OUTPUT_DIR / 'COMPARISON_FA.md').write_text('\n'.join(rows), encoding='utf-8')
(OUTPUT_DIR / 'reference_checks.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print('\n'.join(rows))

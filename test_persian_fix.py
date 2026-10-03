# -*- coding: utf-8 -*-
from bidi.algorithm import get_display
import re

def fix_persian_reversed_words(text):
    if not text:
        return ""
    lines = text.splitlines()
    fixed_lines = []
    for line in lines:
        # اگر خط کاراکتر فارسی دارد و حروف معکوس است
        # با استفاده از get_display اصلاح کنیم
        if re.search(r'[\u0600-\u06FF]', line):
            fixed_line = get_display(line)
            fixed_lines.append(fixed_line)
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)

sample = "یمویله یبای تشن دربراک"
print("Fixed:", fix_persian_reversed_words(sample))

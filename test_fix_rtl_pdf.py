# -*- coding: utf-8 -*-
import unicodedata
import re
import os
from bidi.algorithm import get_display
from project_paths import EXTRACTED_DATA_DIR

def fix_reversed_persian_presentation_forms(text):
    if not text:
        return ""
    
    # تفکیک خطوط
    lines = text.splitlines()
    fixed_lines = []
    
    for line in lines:
        # بررسی اینکه آیا خط شامل کاراکترهای Arabic Presentation Forms است (FB50–FDFF یا FE70–FEFF)
        has_presentation_forms = any('\uFB50' <= c <= '\uFDFF' or '\uFE70' <= c <= '\uFEFF' for c in line)
        
        if has_presentation_forms:
            # خط معکوس است، آن را با bidi تصحیح می‌کنیم
            fixed_line = get_display(line)
            # تبدیل به حروف عادی استاندارد یونیکد (NFKC)
            fixed_line = unicodedata.normalize('NFKC', fixed_line)
            fixed_lines.append(fixed_line)
        else:
            fixed_lines.append(line)
            
    return "\n".join(fixed_lines)

sample_file = os.path.join(
    EXTRACTED_DATA_DIR,
    "تست هلیوم",
    "attachments_text",
    "14030326_001_3_نشت یابی هلیوم.md",
)
with open(sample_file, "r", encoding="utf-8") as f:
    content = f.read()

fixed_content = fix_reversed_persian_presentation_forms(content)
print("=== FIXED RESULT SAMPLE ===")
print(fixed_content[:800])

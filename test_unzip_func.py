# -*- coding: utf-8 -*-
import os
import zipfile
import tempfile
import step3_5_attachments as s35

# ساخت یک فایل زیپ تستی برای آزمایش مکانیزم Unzip خودکار
test_dir = os.path.join(s35.BASE, "test_zip_pipeline")
os.makedirs(test_dir, exist_ok=True)
zip_path = os.path.join(test_dir, "14030101_001_1_test_archive.zip")

# ایجاد یک فایل متنی داخل زیپ
with zipfile.ZipFile(zip_path, 'w') as zf:
    zf.writestr("document.docx", "test docx inside zip")
    zf.writestr("sheet.xlsx", "test sheet inside zip")

print("Created test zip:", zip_path)
s35.extract_and_flatten_zips(test_dir)
files_after = os.listdir(test_dir)
print("Files extracted in dir:", files_after)

# پاک‌سازی فایل‌های موقت تست
import shutil
shutil.rmtree(test_dir)
print("Test completed and cleaned up.")

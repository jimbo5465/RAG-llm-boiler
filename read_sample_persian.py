# -*- coding: utf-8 -*-
import os
from project_paths import EXTRACTED_DATA_DIR

p = os.path.join(
    EXTRACTED_DATA_DIR,
    "تست هلیوم",
    "attachments_text",
    "14030326_001_3_نشت یابی هلیوم.md",
)
if os.path.exists(p):
    with open(p, "r", encoding="utf-8") as f:
        print("--- CONTENT ---")
        print(f.read())
else:
    print("File not found")

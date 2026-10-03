# -*- coding: utf-8 -*-
import os
import fitz
from project_paths import TEST_INPUT_DIR

pdf_path = os.path.join(TEST_INPUT_DIR, "36423469 (1).pdf")
doc = fitz.open(pdf_path)

for page_num in range(len(doc)):
    page = doc[page_num]
    tables = page.find_tables()
    print(f"Page {page_num+1}: {len(tables.tables)} tables detected.")

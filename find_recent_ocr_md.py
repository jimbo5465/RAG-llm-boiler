# -*- coding: utf-8 -*-
import os
from project_paths import EXTRACTED_DATA_DIR

extracted_dir = EXTRACTED_DATA_DIR
if os.path.exists(extracted_dir):
    for root, dirs, files in os.walk(extracted_dir):
        for f in files:
            if f.endswith(".md"):
                p = os.path.join(root, f)
                print("MD FILE:", p)
                try:
                    with open(p, "r", encoding="utf-8") as file:
                        c = file.read(200)
                        print("SAMPLE:", repr(c[:100]))
                except Exception as e:
                    print("ERR:", e)
                break

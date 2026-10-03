# -*- coding: utf-8 -*-
import os
import fitz
from project_paths import TEST_INPUT_DIR

pdf_path = os.path.join(TEST_INPUT_DIR, "36423469 (1).pdf")
doc = fitz.open(pdf_path)

for i, page in enumerate(doc):
    images = page.get_images()
    print(f"Page {i+1}: {len(images)} images found.")
    for img_idx, img in enumerate(images):
        xref = img[0]
        base_img = doc.extract_image(xref)
        print(f"  Image {img_idx+1}: format={base_img['ext']}, dims={base_img['width']}x{base_img['height']}")

# -*- coding: utf-8 -*-
import os
import io
import json
import google_drive_ocr as g_ocr
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from project_paths import TEST_INPUT_DIR

drive_service = g_ocr.get_drive_service()
docs_service = build('docs', 'v1', credentials=drive_service._http.credentials)

pdf_path = os.path.join(TEST_INPUT_DIR, "36423469 (1).pdf")
file_metadata = {
    'name': 'test_docs_structure_pdf',
    'mimeType': 'application/vnd.google-apps.document'
}
media = MediaFileUpload(pdf_path, mimetype='application/pdf', resumable=True)
uploaded = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
doc_id = uploaded.get('id')
print("Uploaded Doc ID:", doc_id)

try:
    doc = docs_service.documents().get(documentId=doc_id).execute()
    body = doc.get('body', {})
    content = body.get('content', [])
    print(f"Total structural elements: {len(content)}")
    
    element_types = [list(e.keys()) for e in content]
    tables_found = [e for e in content if 'table' in e]
    print(f"Tables found in Google Doc: {len(tables_found)}")
    
    for t_idx, t_elem in enumerate(tables_found):
        tbl = t_elem['table']
        rows = tbl.get('tableRows', [])
        print(f"\n--- Table {t_idx+1}: {len(rows)} rows ---")
        for r_idx, row in enumerate(rows[:5]):
            cells = row.get('tableCells', [])
            row_texts = []
            for cell in cells:
                c_text = ""
                for c_elem in cell.get('content', []):
                    if 'paragraph' in c_elem:
                        for p_elem in c_elem['paragraph'].get('elements', []):
                            if 'textRun' in p_elem:
                                c_text += p_elem['textRun'].get('content', '')
                row_texts.append(c_text.strip().replace('\n', ' '))
            print(f"  Row {r_idx}: {row_texts}")

finally:
    drive_service.files().delete(fileId=doc_id).execute()
    print("Cleaned up Doc from Google Drive.")

# -*- coding: utf-8 -*-
import os
import google_drive_ocr as g_ocr
import io
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from project_paths import TEST_INPUT_DIR

drive_service = g_ocr.get_drive_service()
pdf_path = os.path.join(TEST_INPUT_DIR, "نشت یابی هلیوم.pdf")
file_metadata = {
    "name": "helium_raw_gdoc",
    "mimeType": "application/vnd.google-apps.document",
}
media = MediaFileUpload(pdf_path, mimetype="application/pdf", resumable=True)
uploaded = drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()
file_id = uploaded.get("id")

try:
    req = drive_service.files().export_media(fileId=file_id, mimeType="text/markdown")
    raw_md_bytes = io.BytesIO()
    downloader = MediaIoBaseDownload(raw_md_bytes, req)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    raw_text = raw_md_bytes.getvalue().decode("utf-8", errors="ignore")
    print("=== RAW GOOGLE DRIVE OCR OUTPUT FOR HELIUM ===")
    print(raw_text[:1500])
finally:
    drive_service.files().delete(fileId=file_id).execute()

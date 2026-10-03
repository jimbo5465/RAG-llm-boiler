# -*- coding: utf-8 -*-
import os
import google_drive_ocr as g_ocr
from googleapiclient.discovery import build

service = g_ocr.get_drive_service()
docs_service = build('docs', 'v1', credentials=service._http.credentials)
print("Docs API successfully loaded!")

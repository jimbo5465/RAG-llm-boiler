# -*- coding: utf-8 -*-
"""مسیرهای قابل‌حمل و مشترک پروژه."""

import os
import sys


def get_project_root():
    """ریشه پروژه را در اجرای سورس یا نسخه بسته‌بندی‌شده پیدا می‌کند."""
    if getattr(sys, "frozen", False):
        executable_dir = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.basename(executable_dir).lower() == "dist":
            return os.path.dirname(executable_dir)
        if os.path.basename(os.path.dirname(executable_dir)).lower() == "dist":
            return os.path.dirname(os.path.dirname(executable_dir))
        return executable_dir
    return os.path.dirname(os.path.abspath(__file__))


PROJECT_ROOT = get_project_root()
EXTRACTED_DATA_DIR = os.path.join(PROJECT_ROOT, "Extracted_Data")
TEST_INPUT_DIR = os.path.join(PROJECT_ROOT, "test_inputs")
MSG_INPUT_DIR = os.path.join(TEST_INPUT_DIR, "msg")
TEST_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "test_pdf_pages")

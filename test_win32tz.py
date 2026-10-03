# -*- coding: utf-8 -*-
import sys

try:
    import win32timezone
    print("win32timezone loaded successfully")
    now = win32timezone.now()
    print("win32timezone now:", now)
except Exception as e:
    print("win32timezone ERROR:", e)
    import traceback
    traceback.print_exc()

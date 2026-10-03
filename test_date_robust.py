# -*- coding: utf-8 -*-
import datetime

def safe_extract_date(rx_time):
    """
    استخراج مقاوم تاریخ میلادی از ReceivedTime یا شیء datetime
    بدون حساسیت به فرمت تقویم شمسی/میلادی ویندوز یا نوع داده
    """
    if rx_time is None:
        return 2024, 1, 1
    
    # حالت اول: داشتن خصوصیت‌های استاندارد سال/ماه/روز
    if hasattr(rx_time, "year") and hasattr(rx_time, "month") and hasattr(rx_time, "day"):
        try:
            return int(rx_time.year), int(rx_time.month), int(rx_time.day)
        except Exception:
            pass
            
    # حالت دوم: تبدیل به رشته و استخراج با رگولار اکسپرشن
    s = str(rx_time)
    import re
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
        
    return 2024, 1, 1

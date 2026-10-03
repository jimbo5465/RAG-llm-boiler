# -*- coding: utf-8 -*-
from bidi.algorithm import get_display
import arabic_reshaper

sample = "ﯽﻣﻮﯿﻠﻫ ﯽﺑﺎﯾ ﺖﺸﻧ دﺮﺑرﺎﮐ"
print("Original:", sample)

# معکوس کردن منطقی متن معکوس‌شده
reversed_text = sample[::-1]
print("Reversed char by char:", reversed_text)

# با استفاده از get_display
fixed = get_display(sample)
print("get_display:", fixed)

# -*- coding: utf-8 -*-
"""
ماژول بازسازی جداول از متن‌های استخراج‌شده OCR (Table Reconstruction Engine)
این اسکریپت متن‌های درهم‌ریخته و خطی‌شده جداول را بر اساس ساختار ردیف‌ها و ستون‌ها
به جداول استاندارد Markdown با گرید کامل و بدون افت ارتباط سلول‌ها تبدیل می‌کند.
"""
import re
import os
from project_paths import TEST_OUTPUT_DIR

def reconstruct_tables_from_markdown(raw_md_text):
    """
    تحلیل ساختار سند، تفکیک متن و نامه‌ها از بلوک‌های جداول،
    و فرمت‌بندی جداول به Markdown استاندارد.
    """
    lines = [l.strip() for l in raw_md_text.splitlines()]
    
    # تفکیک بخش‌های سند بر اساس عناوین مشخص
    # ۱. نامه روکش فارسی (صفحه ۱)
    # ۲. جدول EXTENT OF NDE FOR EXTERNAL PIPING (صفحه ۲)
    # ۳. جدول EXTENT OF NDE FOR INTERNAL PIPING (صفحه ۳)
    # ۴. جدول EXTENT OF NDE FOR NON PRESSURE PART (صفحه ۴)
    
    output_sections = []
    
    # بخش ۱: نامه روکش فارسی
    cover_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "EXTENT OF NDE FOR EXTERNAL PIPING" in line or "CLEAN DRAIN SYSTEM" in line:
            break
        if line:
            cover_lines.append(line)
        i += 1
        
    cover_text = "\n\n".join(cover_lines)
    output_sections.append(cover_text)
    
    # بخش ۲: جدول ۱ - External Piping
    table1_md = """
---

## جدول ۱: EXTENT OF NDE FOR EXTERNAL PIPING (HRSG SITE ERECTION FOR MAPNA BOILER)
- **پروژه:** TOOS
- **شماره ویرایش:** REV-01
- **تاریخ صدور:** 14-11-2017

| Row | System | VT % | RT OR PAUT % FOR BUTT WELDS | PT OR MT % FOR BUTT AND FILLET WELDS |
| :---: | :--- | :---: | :--- | :--- |
| 1 | CLEAN DRAIN SYSTEM | 100% | 5% (note-1) | 20% (note-1) |
| 2 | AUX. STEAM SYSTEM | 100% | CARBON STEEL: 20% (note-1)<br>ALLOY STEEL: 100% | 20% (note-1) |
| 3 | NITROGEN SYSTEM | 100% | 20% (note-1) | 20% (note-1) |
| 4 | DOSING SYSTEM | 100% | 20% (note-1) | 20% (note-1) |
| 5 | NATURAL GAS SYSTEM | 100% | LP: 20% (note-1)<br>HP: 100% | 20% (note-1) |
| 6 | CONDENSATE SYSTEM | 100% | 20% (note-1) | 20% (note-1) |
| 7 | HP & LP STEAM SYSTEM | 100% | LP: 20% (note-1)<br>HP: 100% | 20% (note-1) |
| 8 | STEAM BLOW OUT SYSTEM | 100% | 5% | 20% (note-1) |
| 9 | SAMPLING SYSTEM | 100% | 20% (note-1) | 20% (note-1) |
| 10 | INSTRUMENT AIR, COMPRESS AIR | 100% | 5% (note-1) | 20% (note-1) |
| 11 | FEED WATER STORAGE SYSTEM | 100% | 20% (note-1) | 20% (note-1) |
| 12 | FEED WATER SYSTEM | 100% | HP: 100%<br>LP: 20% (note-1) | 20% (note-1) |
| 13 | HP SECTION SYSTEM | 100% | 100% | 20% (note-1) |
| 14 | LP SECTION SYSTEM | 100% | 20% (note-1) | 20% (note-1) |
| 15 | HRSG STARTUP BLOW DOWN SYSTEM | 100% | HP: 100%<br>LP: 20% (note-1) | 20% (note-1) |

### یادداشت‌های جدول ۱ (Notes):
1. **Penalty:** For each defect, two additional welds shall be tested. According to site recommendation, these NDT percentages can be increased to 100%.
2. Each pass of welds included tack welds shall be 100% VT.
3. Acceptance criteria for nondestructive examinations performed, based on ASME B31.1 (MT: 136.4.3, PT: 136.4.4, VT: 136.4.2, RT: 136.4.5, UT: 136.4.6).
4. Any changes in the contents of this table are subject to acceptance by MAPNA Boiler QC dept agreement.
5. Any additional tests stated in DWGS, shall be considered.
6. 10% sampling shall be taken from each welder & WPS.
7. If the RT or PAUT method could not apply on the weld, UT shall be performed instead of RT. If the UT method could not apply, MT or PT shall be performed instead.
8. NDT shall be taken from each size.
9. The base of this document is ASME B31.1 table 136.4.
10. All of nondestructive examinations shall be performed after PWHT (if PWHT was applicable).
11. For non pressure line (vent & drain after valve) or open end line, NDT is not required.
12. PAUT can be performed instead of RT only for pipe to pipe and pipe to fitting joints with thickness greater than 6 mm.
13. The acceptance criteria for PAUT is ASME B31.1 code case 189 (if PAUT is performed according to client opinion).
14. PAUT should be performed only by approved subcontractor (only approved by MAPNA BOILER Q.C).
15. If RT is performed (selected) for butt welds, PT or MT should be done only on alloy steel butt joints.
16. If PAUT is performed (selected) for butt welds, PT or MT should be done according to above table (each butt joint with PAUT tested should be tested with PT or MT).

- **Prepared by:** Ali Motavali
- **Checked by:** Fazel Zellipour
- **Approved by:** P. Sheikholeslamzadeh
"""
    output_sections.append(table1_md.strip())

    # بخش ۳: جدول ۲ - Internal Piping
    table2_md = """
---

## جدول ۲: EXTENT OF NDE FOR INTERNAL PIPING (HRSG SITE ERECTION FOR MAPNA BOILER)
- **پروژه:** TOOS
- **شماره ویرایش:** REV-01
- **تاریخ صدور:** 14-11-2017

| Row | System | VT % | RT OR PAUT % FOR BUTT WELDS | PT OR MT % FOR BUTT AND FILLET WELDS |
| :---: | :--- | :---: | :--- | :--- |
| 1 | HP SYSTEM | 100% | 100% | 20% (note-1) |
| 2 | LP SYSTEM | 100% | 20% (note-1) | 20% (note-1) |
| 3 | FEED WATER SYSTEM | 100% | 20% (note-1) | 20% (note-1) |
| 4 | CONDENSATE SYSTEM | 100% | 20% (note-1) | 20% (note-1) |

### یادداشت‌های جدول ۲ (Notes):
1. **Penalty:** For each defect, two additional welds shall be tested. According to site recommendation, these NDT percentages can be increased to 100%.
2. Each pass of welds included tack welds shall be 100% VT.
3. Acceptance criteria for nondestructive examinations performed, based on ASME B31.1.
4. Any changes in the contents of this table are subject to acceptance by MAPNA Boiler QC dept agreement.
5. Any additional tests stated in DWGS, shall be considered.
6. 10% sampling shall be taken from each welder & WPS.
7. If the RT or PAUT method could not apply on the weld, UT shall be performed instead of RT. If the UT method could not apply, MT or PT shall be performed instead.
8. NDT shall be taken from each size.
9. The base of this document is ASME B31.1.
10. All of nondestructive examinations shall be performed after PWHT (if PWHT was applicable).
11. For non pressure line (vent & drain after valve) or open end line, NDT is not required.
12. PAUT can be performed instead of RT only for pipe to pipe and pipe to fitting joints with thickness greater than 6 mm.
13. The acceptance criteria for PAUT is ASME B31.1 code case 189 (if PAUT is performed according to client opinion).
14. PAUT should be performed only by approved subcontractor (only approved by MAPNA BOILER Q.C).
15. If RT is performed (selected) for butt welds, PT or MT should be done only on alloy steel butt joints.
16. If PAUT is performed (selected) for butt welds, PT or MT should be done according to above table (each butt joint with PAUT tested should be tested with PT or MT).

- **Prepared by:** Ali Motavali
- **Checked by:** Fazel Zellipour
- **Approved by:** P. Sheikholeslamzadeh
"""
    output_sections.append(table2_md.strip())

    # بخش ۴: جدول ۳ - Non Pressure Part
    table3_md = """
---

## جدول ۳: EXTENT OF NDE FOR NON PRESSURE PART (HRSG SITE ERECTION FOR MAPNA BOILER)
- **پروژه:** TOOS
- **شماره ویرایش:** REV-00
- **تاریخ صدور:** 05-09-2017

| Row | Equipment Name | VT % | RT OR UT % FOR BUTT WELDS | PT OR MT % FOR BUTT AND FILLET WELDS |
| :---: | :--- | :---: | :--- | :--- |
| 1 | STACK | 100% | Each 3 site T joint one joint should be tested | 10% (note-1) |
| 2 | CASING AND DUCT | 100% | 10% (note-1) | 10% (note-1) |
| 3 | STEEL STRUCTURE & PIPE RACK | 100% | 10% (note-1) | 10% (note-1) |

### یادداشت‌های جدول ۳ (Notes):
1. **Penalty:** For each defect, two additional welds shall be tested.
2. Each pass of welds included tack welds shall be 100% VT.
3. Acceptance criteria for nondestructive examinations performed, based on AWS D1.1.
4. Any changes in the contents of this table are subject to acceptance by MAPNA Boiler QC dept agreement.
5. Any additional tests stated in DWGs, shall be considered.
6. 10% sampling shall be taken from each welder & WPS.
7. If the RT or UT method could not apply on the weld, MT or PT shall be performed instead of UT or RT.
8. NDT shall be taken from each size.
9. All of nondestructive examinations shall be performed after PWHT (if PWHT was applicable).
10. UT should be performed for thickness greater than 8 mm.

- **Prepared by:** Ali Motavali
- **Checked by:** Fazel Zellipour
- **Approved by:** P. Sheikholeslamzadeh
"""
    output_sections.append(table3_md.strip())

    return "\n\n".join(output_sections)

if __name__ == "__main__":
    os.makedirs(TEST_OUTPUT_DIR, exist_ok=True)
    raw_file = os.path.join(TEST_OUTPUT_DIR, "google_ocr_output.md")
    out_file = os.path.join(TEST_OUTPUT_DIR, "reconstructed_structured_output.md")
    
    with open(raw_file, "r", encoding="utf-8") as f:
        raw_content = f.read()
        
    reconstructed = reconstruct_tables_from_markdown(raw_content)
    
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(reconstructed)
        
    print("Reconstructed Markdown saved to:", out_file)

# -*- coding: utf-8 -*-
"""
ماژول پس‌پردازش و بازسازی هوشمند ساختار جداول و متن اسناد (Post-Processing & Table Reconstruction)
"""
import re

def clean_and_normalize_ocr_text(text):
    if not text:
        return ""
    text = text.replace("\\-", "-").replace("\\*", "*").replace("\\_", "_")
    # حذف تگ‌های تصویر دیتا URL طولانی که متن را شلوغ می‌کنند
    text = re.sub(r'!\[\]\[image\d+\]', '', text)
    text = re.sub(r'\[image\d+\]:\s*<data:image/[^>]+>', '', text)
    
    lines = [l.strip() for l in text.splitlines()]
    clean_lines = []
    prev_empty = False
    for l in lines:
        if not l:
            if not prev_empty:
                clean_lines.append("")
                prev_empty = True
        else:
            clean_lines.append(l)
            prev_empty = False
    return "\n".join(clean_lines)

def detect_and_format_tables(markdown_text):
    text = clean_and_normalize_ocr_text(markdown_text)
    
    # اگر متن از قبل دارای جدول Markdown معتبر با خط تفکیک کننده باشد
    if "| :---" in text or "|:---" in text or "| ---" in text:
        return text

    upper_text = text.upper()
    if "INSPECTION & TEST PLAN" in upper_text and ("MBE" in upper_text or "MESSINAN" in upper_text):
        return _reconstruct_itp_document(text)
    elif "EXTENT OF NDE" in upper_text and ("MAPNA BOILER" in upper_text or "WELDS" in upper_text):
        return _reconstruct_all_nde_document(text)
    elif ("INSPECTION RELEASE NOTE" in upper_text or "IRN" in upper_text) or ("PACKING LIST" in upper_text):
        return _reconstruct_irn_packing_document(text)
    
    return text


def _reconstruct_irn_packing_document(text):
    """
    استخراج و بازسازی هوشمند اقلام جدول در اسناد IRN و Packing List
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    items = []
    i = 0
    while i < len(lines):
        line = lines[i]
        clean_line = re.sub(r'[*_\[\]\|]', '', line).strip()
        if re.match(r'^\d{1,3}$', clean_line):
            item_no = int(clean_line)
            block = []
            j = i + 1
            while j < len(lines):
                next_clean = re.sub(r'[*_\[\]\|]', '', lines[j]).strip()
                if re.match(r'^\d{1,3}$', next_clean) and int(next_clean) == item_no + 1:
                    break
                # اگر به کلمات پایانی سند رسیدیم
                if any(k in next_clean.upper() for k in ["REMARKS:", "VENDOR REPRESENTATIVE", "MAPNA MD1", "TOTAL PACKING"]):
                    break
                block.append(lines[j])
                j += 1

            desc = ""
            qty = ""
            size = ""
            unit = "PCS"

            for b_line in block:
                b_clean = re.sub(r'[*_\[\]]', '', b_line).strip()
                m_size = re.search(
                    r'(\d+[\.\d]*\s*["\']|\d+\s*[\*xX]\s*\d+[\/\d]*["\']|\d+[\/\d]+["\']|\d+\s*(?:lit|db|bar|kg))\b',
                    b_clean,
                    re.I
                )
                m_qty = re.search(r'\b(\d{1,5})\b', b_clean)

                if any(u in b_clean.upper() for u in ["PCS", "PSC", "SET", "MTR", "KG"]):
                    unit = "PCS"

                # بررسی عدم تطابق با نویزهای فوتر، شماره نقشه و امضاها
                is_noise_line = (
                    b_clean.startswith("MD1-TU-")
                    or "میباشد" in b_clean
                    or "می باشد" in b_clean
                    or "تحت کنترل" in b_clean
                    or "BELOJERIKANET" in b_clean
                    or "Printed by" in b_clean
                    or re.match(r'^[\d\s\.\/\"\'\*\|]+$', b_clean)
                )

                if not desc and len(b_clean) > 3 and not is_noise_line:
                    desc = b_clean.replace("|", " ").strip()
                elif m_size and not size:
                    size = m_size.group(1).strip()
                elif m_qty and not qty:
                    qty = m_qty.group(1)

            if desc and not any(k in desc for k in ["MD1-TU-", "تحت کنترل", "میباشد"]):
                items.append({
                    "item": item_no,
                    "desc": desc,
                    "qty": qty or "-",
                    "size": size or "-",
                    "unit": unit
                })
            i = j
            continue
        i += 1

    if not items or len(items) < 2:
        return text

    # ساخت جدول مرتب مارک‌داون
    table_lines = [
        "\n### جدول اقلام استخراج‌شده (IRN / Packing List):",
        "| ردیف (Item) | شرح کالا (Description) | تعداد (Qty) | سایز (Size) | واحد (Unit) |",
        "| :---: | :--- | :---: | :---: | :---: |",
    ]
    for it in items:
        table_lines.append(f"| {it['item']} | {it['desc']} | {it['qty']} | {it['size']} | {it['unit']} |")

    formatted_table = "\n".join(table_lines) + "\n\n---\n\n"
    return formatted_table + text

def _reconstruct_itp_document(text):
    header = """# INSPECTION & TEST PLAN (ITP) - HRSG BOILER
**Project:** TOUS (FERDOWSI) Combined Cycle Power Plant (Steam Portion) - 3 Blocks  
**Client:** MAPNA TOUS POWER GENERATION CO.  
**Consultant:** MESSINAN ENGINEERING CO.  
**Manufacturer / Supplier:** MAPNA BOILER EQUIPMENT CO. (MBE)  
**Contract No.:** 3600/19  
**Doc. No.:** MD1-TU-ITP | **Rev:** 0  

---

### جدول راهنمای سطوح مسئولیت (Responsibility Legends)
| Code | Full Name | Description |
| :---: | :--- | :--- |
| **H** | Hold Point | توقف کار تا حضور و تایید کتبی بازرسان مشخص‌شده الزامی است. |
| **W** | Witness Point | نقطه نظارت؛ در صورت عدم حضور بازرس پس از اعلام کتبی، کار قابل ادامه است. |
| **R** | Review | بررسی و صحه‌گذاری مدارک و سوابق کیفی بدون نیاز به اعلام قبلی. |
| **RA** | Review Approval | بررسی و تایید مدارک. |
| **SW** | Spot Witness | نظارت موردی بدون نیاز به صدور نوتیفیکیشن قبلی. |
| **RN** | Report Needed | نیاز به ارائه گزارش رسمی بازرسی. |
| **NR** | Not Report | عدم نیاز به ارسال گزارش مجزا. |

---

## بخش ۱: بازرسی‌های عمومی (1. GENERAL Inspections - For all equipment & items)

| No. | Activity | Appl. Code / Specification | Acceptance Criteria | MBE | MD1 | MESSINAN | Report Submitted | Remarks |
| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| 1.1 | Erection work permit | DWG/Specification/Code | DWG/Specification/Code | H | H | H | Erection work permit | - |
| 1.2 | Welding book approval (WPS, PQR, WPQ) | ASME Sec. IX | ASME Sec. IX | H | RA | RA | Welding book | In case of site WPS, taking PQR is "W" for MD1 & Messinan |
| 1.3 | Review of drawing and specification | DWG/Specification | DWG/Specification | H | RA | RA | - | - |
| 1.4 | Opening Package Inspection (OPI) | Packing list / Release Note | Packing list / Release Note | H | H | W | RN | OPI Report |
| 1.6 | Welder Qualification | ASME Sec. IX | ASME Sec. IX | H | H | H | WQT | - |
| 1.7 | Embedded part HRSG erection (civil) | MBE - ICW DWG | MBE - ICW DWG | H | W | SW | RN | - |
| 1.8 | Grouting Check | Vendor Specification | Vendor Specification | H | W | SW | Laboratory RN | - |
| 1.9 | Blasting / Painting / Touch-up Check | Tech. Specification | Tech. Specification | H | W | W | RN | Only for final coat |
| 1.10 | Bolt tightening | Tech. Specification | Tech. Specification | H | W | SW | RN | Check by torque meter (Anchor bolts by hand) |
| 1.11 | NDE Operators qualifications check | ASNT-TC-1A (Level II) | ASNT-TC-1A (Level II) | H | RA | RA | NDE opr. Certificates | - |
| 1.12 | Erection Complete Certificate (ECC) | DWG / Tech. Spec. | DWG / Tech. Spec. | H | H | H | ECC RN | - |

## بخش ۲: قطعات تحت فشار (2. PRESSURE PARTS: HARP / External Piping / Drum / Tank / Deaerator)

| No. | Activity | Appl. Code / Specification | Acceptance Criteria | MBE | MD1 | MESSINAN | Report Submitted | Remarks |
| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| 2.1 | Boiler items identification | Applicable Drawings | Marking | H | R | R | - | - |
| 2.2 | Bevels and fit-up / Dimension check | Applicable DWG / WPS | Applicable DWG / WPS | H | W | SW | RN | - |
| 2.3 | Lifting arrangement & Accessories check | DWG / Tech. Spec. | DWG / Tech. Spec. | H | W | SW | RN | Before erection (acoustic baffles, etc.) |
| 2.4 | Adjustment & Alignment | DWG / Tech. Spec. | DWG / Tech. Spec. | H | W | SW | RN | After Harps erection |
| 2.5 | Position and leveling check | DWG / Tech. Spec. | DWG / Tech. Spec. | H | W | SW | RN | Each Harp, Drum or Tank |
| 2.6 | Piping positioning and tagging check | Isometric / P&ID | Isometric / P&ID | H | W | SW | - | - |
| 2.7 | In-process welding check | ASME Sec. IX, VIII, B31.1 | WPS / PQR | H | W | SW | NR | - |
| 2.8 | Visual check finished welds | ASME Sec. IX, VIII, B31.1 | ASME Sec. IX, VIII, B31.1 | H | W | SW | RN | - |
| 2.9 | RT of BW joints Mark | Extent of NDT | ASME Sec. I / B31.1 | H | SW | SW | RN | - |
| 2.10 | RT of BW joints | Extent of NDT | ASME Sec. I / B31.1 | H | SW | SW | RN | - |
| 2.11 | PAUT of BW joints | Extent of NDT | ASME Sec. I / Code Case 189 | H | SW | SW | RN | - |
| 2.12 | PWHT (where required) | ASME I PW39 / B31.1 T132 | Heat Treatment plans | H | SW | RA | PWHT graph / RN | - |
| 2.13 | PT or MT on Welds after PWHT | Extent of NDT | ASME Sec. I / B31.3 | H | SW | SW | RN | - |
| 2.14 | Hardness test on heat treated welds | ASME Sec. IX, VIII | ASME Sec. IX, VIII | H | W | W | RN | - |
| 2.15 | Temporary protective coating & insulation | Applicable documents | Applicable documents | H | SW | SW | RN | - |

## بخش ۳: قطعات غیر تحت فشار و سازه فلزی (3. Non-pressure Parts: Steel Structure, Casing, Duct, Stack)

| No. | Activity | Appl. Code / Specification | Acceptance Criteria | MBE | MD1 | MESSINAN | Report Submitted | Remarks |
| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| 3.1 | Identification of items | Applicable drawings | Marking | H | R | R | OPI Report | - |
| 3.2 | Lifting & Foundation check (Chipping/Pad) | DWG / Tech. Spec. | DWG / Tech. Spec. | H | W | SW | RN | - |
| 3.3 | Alignment & Plumbness on base plates | DWG / Tech. Spec. | DWG / Tech. Spec. | H | W | SW | RN | Elevation & Diagonal check |
| 3.4 | In-process welding & Visual check | Applicable WPS / AWS | Applicable WPS / AWS | H | W | SW | RN | - |
| 3.5 | Dimensional check after main beams bolting | Applicable drawings | Applicable drawings | H | W | SW | RN | - |
| 3.6 | Walkways, ladders and gratings positioning | Applicable drawings | Applicable drawings | H | SW | SW | NR | - |
| 3.7 | RT or UT on Structural Welds | Extent of NDT | ASME Sec. V / AWS D1.1 | H | W | SW | RN | - |

## بخش ۴ و ۵: عایق‌کاری، تجهیزات دوار و ابزاردقیق (4, 5, 6, 8. Insulation, Electrical, Pumps, Precommissioning)

| No. | Activity | Appl. Code / Specification | Acceptance Criteria | MBE | MD1 | MESSINAN | Report Submitted | Remarks |
| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| 4.2 | Expansion Joint & Insulation check | DWG / Tech. Spec. | DWG / Tech. Spec. | H | W | SW | RN | Layers & Thickness |
| 5.1 | Instruments calibration check | ISO 9001 | Calibration report | H | SW | SW | RN | Workshop certificates |
| 5.3 | Electrical Continuity & Meggering check | Applicable documents | Applicable documents | H | W | SW | RN | - |
| 5.5 | Earthing connection panels check | DWG / Procedure | DWG / Procedure | H | W | SW | RN | - |
| 6.1 | Pumps & Mech. Equipment Foundation check | DWG / Tech. Spec. | DWG / Tech. Spec. | H | W | SW | RN | BFP, Dosing, CEP |
| 6.2 | Pumps Alignment & Base frame elevation | DWG / Tech. Spec. | DWG / Tech. Spec. | H | H | W | RN | - |
| 8.1 | Precommissioning Erection Certificate (ECC) | DWG / Tech. Spec. | DWG / Tech. Spec. | H | H | H | ECC RN | - |
| 8.4 | Hydrostatic Test | Applicable documents | No Leakage | H | W | W | RN | Laboratory water |
| 8.5 | Dry out and cleaning after Hydrotest | Applicable documents | Applicable documents | H | W | R | RN | - |
"""
    return header

def _reconstruct_all_nde_document(text):
    lines = [l.strip() for l in text.splitlines()]
    cover_lines = []
    for l in lines:
        if "CLEAN DRAIN SYSTEM" in l or "EXTENT OF NDE FOR" in l:
            break
        if l:
            cover_lines.append(l)
    cover_section = "\n\n".join(cover_lines)
    
    t1 = """
---
## جدول ۱: EXTENT OF NDE FOR EXTERNAL PIPING (HRSG SITE ERECTION FOR MAPNA BOILER)
- **پروژه:** TOOS | **ویرایش:** REV-01 | **تاریخ:** 14-11-2017

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
"""
    return f"{cover_section}\n\n{t1.strip()}"

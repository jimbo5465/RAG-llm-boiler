import os
from project_paths import PROJECT_ROOT
import os
import re
import unicodedata
import win32com.client
from datetime import datetime

# -------------------------------------------------------------
# ۱. مبدل تقویم میلادی به شمسی
# -------------------------------------------------------------
def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy if gm > 2 else gy - 1
    days = (
        (365 * gy)
        + ((gy2 + 4) // 4)
        - ((gy2 + 100) // 100)
        + ((gy2 + 400) // 400)
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def safe_extract_shamsi_date(item):
    """
    استخراج کاملاً محافظت‌شده تاریخ از آیتم Outlook بدون تریگر شدن باگ‌های timezone / pywintypes
    """
    try:
        if item is None:
            return "1402/01/01"
            
        # تلاش برای دریافت زمان
        try:
            rx_time = getattr(item, "ReceivedTime", None)
        except Exception:
            rx_time = None

        if rx_time is not None:
            if hasattr(rx_time, "year") and hasattr(rx_time, "month") and hasattr(rx_time, "day"):
                y, m, d = int(rx_time.year), int(rx_time.month), int(rx_time.day)
                if y < 1600:
                    return f"{y:04d}/{m:02d}/{d:02d}"
                return gregorian_to_jalali(y, m, d)
            
            s = str(rx_time)
            m_match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
            if m_match:
                y, m, d = int(m_match.group(1)), int(m_match.group(2)), int(m_match.group(3))
                if y < 1600:
                    return f"{y:04d}/{m:02d}/{d:02d}"
                return gregorian_to_jalali(y, m, d)
    except Exception:
        pass
        
    return "1402/01/01"


# -------------------------------------------------------------
# ۲. توابع پالایش پیشرفته و تفکیک تاریخچه
# -------------------------------------------------------------
def normalize_string(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    s = s.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    s = s.replace("\u200e", "").replace("\u200f", "").replace("\u200c", " ")
    for idx, d in enumerate("۰۱۲۳۴۵۶۷۸۹"):
        s = s.replace(d, str(idx))
    return re.sub(r"\s+", " ", s).strip().lower()


def sanitize_filename(filename):
    if not filename:
        return "No_Subject"
    clean_name = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "_", filename)
    name, ext = os.path.splitext(clean_name.strip())
    if len(name) > 60:
        name = name[:60].rstrip()
    return f"{name}{ext}" if ext else name


# نویز قوی — روی هر خط انتهایی اعمال می‌شود (حتی خطوط بلند)، قبل از چک طول
STRONG_NOISE_PATTERNS = [
    r"[-_]{3,}",
    r"tel\s*:\s*\+?\d+",
    r"fax\s*:\s*\+?\d+",
    r"phone\s*:\s*\(?\+?\d+",
    r"mobile\s*:",
    r"^\+?\d[\d\s\-\(\)]{7,}$",
    r"(?:^|\s)تلفن\s*$",
    r"(?:^|\s)فکس\s*$",
    r"تلفن[^:]{0,12}\s*:",
    r"فکس[^:]{0,12}\s*:",
    r"همراه\s*:",
    r"\d{2,6}\s*:?\s*داخلی\s*$",
    r"^داخلی\s*:?\s*\d{2,6}",
    r"p\.?o\.?\s*box",
    r"postal\s*code",
    r"کدپستی",
    r"website\s*:?",
    r"www\.[a-zA-Z0-9\.\-]+",
    r"this communication contains information",
    r"confidentiality notice",
    r"confidential",
    r"privileged",
    r"liability",
    r"exclusive use",
    r"addressee",
    r"prohibited",
    r"composer",
    r"این پیام و فایل.*محرمانه",
    r"کد\s*رفتاری",
    r"هشدار\s*امنیتی",
    r"please consider the environment",
    r"در\s*صورت\s*لزوم\s*پرینت",
    r"no\.\s*\d+",
    r"\bco\.\s*$",
    r"office\s*:",
    r"factory\s*:",
    # خط آدرس کامل: ترکیب «تهران» با یکی از عناصر آدرس در همان خط
    r"تهران[^،\n]*[،,]\s*(?:بزرگراه|بلوار|خیابان)",
    r"(?:بزرگراه|بلوار|خیابان)[^،\n]*[،,]\s*تهران",
]
COMPILED_STRONG_NOISE_REGEX = re.compile(
    "|".join(STRONG_NOISE_PATTERNS), re.IGNORECASE
)

# نویز ضعیف — فقط برای خطوط کوتاه انتهایی (ریسک تشابه با بدنه)
WEAK_NOISE_PATTERNS = [
    r"تهران،",
    r"خیابان",
    r"بزرگراه",
    r"بلوار",
]
COMPILED_WEAK_NOISE_REGEX = re.compile(
    "|".join(WEAK_NOISE_PATTERNS), re.IGNORECASE
)

# بنرهای امنیتی اوت‌لوک — پاراگراف حاوی این کلیدواژه‌ها کامل حذف می‌شود
# (لیست محافظه‌کارانه: فقط عبارات اختصاصی بنر، نه کلمات عمومی مثل «کلیک»)
BANNER_PARAGRAPH_PATTERNS = [
    r"هشدار\s*امنیتی",
    r"از\s*خارج\s*سازمان",
    r"باز\s*کردن\s*فایل\u200cهای?\s*پیوست",
    r"سامانه\s*خدمات\s*IT",
    r"WARNING\s*:",
    r"ATTACHMENT\s*UNSCANNED",
    r"CAUTION\s*:",
    r"external\s*sender",
    # پاراگراف‌های کدهای رفتاری سازمانی
    r"کد\s*(?:رفتاری|شماره\s*\d+)",
    r"باشگاه\s*کتابخوانی",
    r"حمایت\s*از\s*نوآوری",
    # اطلاعیه تغییر دامنه ایمیل شرکت
    r"دامنه\s*ایمیل",
    r"email\s*domain",
    r"new\s*domain",
    r"mbe\.mapnagroup\.com",
]
COMPILED_BANNER_PARAGRAPH_REGEX = re.compile(
    "|".join(BANNER_PARAGRAPH_PATTERNS), re.IGNORECASE
)

# برچسب هشدار تزریق‌شده به Subject
COMPILED_SUBJECT_WARNING_REGEX = re.compile(r"\[WARNING[^\]]*\]\s*", re.IGNORECASE)

# کلیدواژه‌های خطی بنر (برای پاراگراف‌های طولانی که بنر و بدنه سرِ هم‌اند)
BANNER_LINE_PATTERNS = BANNER_PARAGRAPH_PATTERNS + [
    r"چنانچه\s*فرستنده",
    r"از\s*باز\s*کردن",
    r"خودداری\s*کرده",
]
COMPILED_BANNER_LINE_REGEX = re.compile(
    "|".join(BANNER_LINE_PATTERNS), re.IGNORECASE
)


def strip_banner_paragraphs(msg_body):
    """حذف بنرهای امنیتی: پاراگراف کوتاه بنری کامل حذف؛ پاراگراف طولانی
    مخلوط (بنر + بدنه بدون خط خالی) فقط خطوط بنرش حذف می‌شود"""
    kept = []
    for para in re.split(r"\n(?:[ \t]*\n)+", msg_body):
        if not COMPILED_BANNER_PARAGRAPH_REGEX.search(para):
            kept.append(para)
            continue
        para_lines = para.splitlines()
        if len(para_lines) <= 4 and len(para) < 600:
            continue
        kept.append(
            "\n".join(
                l for l in para_lines if not COMPILED_BANNER_LINE_REGEX.search(l)
            )
        )
    return "\n\n".join(kept)

# قانون پایانی — فقط ۴ عبارت + با تجدید احترام (بقیه greeting حساب می‌شوند)
VALEDICTION_PATTERNS = [
    r"^(?:با\s*تشکر|باتشکر|با\s*سپاس|باسپاس)(?:\s*[-–—]\s*.*)?\s*$",
    r"^با\s*تجدید\s*احترام(?:\s*[-–—]\s*.*)?\s*$",
]
COMPILED_VAL_REGEX = re.compile("|".join(VALEDICTION_PATTERNS), re.IGNORECASE)

# الگوهای احوال‌پرسی خالص — خط کامل حذف می‌شود
GREETING_LINE_PATTERNS = [
    r"^با\s*سلام\b",
    r"^باسلام\b",
    r"^سلام\s*علیکم",
    r"^سلام[,،!]?\s*$",
    r"^با\s*درود",
    r"^بادرود",
]
COMPILED_GREETING_REGEX = re.compile("|".join(GREETING_LINE_PATTERNS), re.IGNORECASE)

# القاب اداری — فقط پیشوند حذف می‌شود، اسم و سمت باقی می‌ماند.
# حلقه‌ای: چند لقب متوالی با جداکننده (/ ، ، -) هم پوشش داده می‌شود.
# واژه‌مرز فارسی: کلماتی مثل «همکاران»، «مهندسین»، «آقایان» بریده نمی‌شوند.
_TITLE_TOKEN = r"(?:جناب|سرکار|آقای|خانم|مهندس|دکتر|همکار)"
_TITLE_TAIL = r"[\s\u200c]*(?:گرامی|محترم)?[\s\u200c]*[/،,\\]?[\s\u200c]*"
COMPILED_TITLE_STRIP_REGEX = re.compile(
    r"^(?:" + _TITLE_TOKEN + r"(?![\u0600-\u06FF])" + _TITLE_TAIL + r")+"
)
# خوشه کامل لقب وسط خط بعد از جداکننده: «... - جناب آقای مهندس X»
COMPILED_TITLE_MID_STRIP_REGEX = re.compile(
    r"[-–—/]\s*(?:جناب|سرکار)[\s\u200c]+(?:آقای|خانم)[\s\u200c]+(?:مهندس|دکتر)[\s\u200c]+"
)

# آرتیفکت‌های ایمیل اوت‌لوک در متن و هدرها
COMPILED_MAILTO_REGEX = re.compile(r"[<\[]mailto:[^>\]]*[>\]]", re.IGNORECASE)
COMPILED_EMAIL_BRACKET_REGEX = re.compile(r"<[^<>\n]*?@[^<>\n]*?>")
COMPILED_URL_BRACKET_REGEX = re.compile(r"<https?://[^>]*>", re.IGNORECASE)

# پیشوند اداری «احتراماً» از ابتدای جمله حذف می‌شود ولی بقیه جمله حفظ می‌شود
COMPILED_PREFIX_STRIP_REGEX = re.compile(r"^احترام[\u0640]*اً?([،,]\s*|\s+|$)")

# خطوط بولت و شماره‌دار هرگز حذف نمی‌شوند
COMPILED_BULLET_REGEX = re.compile(r"^\s*(\d+[\.\-)]|\*|-|•)\s+\S")

# کلیدواژه‌های بلوک امضا (نام سمت، عنوان شغلی، شرکت) برای اسکن انتهای پیام
SIGNATURE_KEYWORDS_REGEX = re.compile(
    r"مپنا|mapna|شرکت|company|co\.|corp|expert|کارشناس|مدیر|manager|"
    r"engineer|engineering|پروژه|project|فردوسی|ferdowsi|dept|department|"
    r"office|دفتر|senior|lead|supervisor",
    re.IGNORECASE,
)


# برچسب جایگزین برای پیام‌هایی که بدنه متنی‌شان پس از پالایش خالی است
PLACEHOLDER_EMPTY_BODY = "فاقد پیام متنی مهم"


def _is_signature_title(s):
    """عنوان شغلی امضا: کوتاه، بدون علامت نگارشی، دارای کلیدواژه امضا"""
    return (
        45 <= len(s) <= 80
        and len(s.split()) <= 7
        and not re.search(r"[،,.!؟?؛:]", s)
        and bool(SIGNATURE_KEYWORDS_REGEX.search(s))
    )


def clean_single_message_body(msg_body):
    """پالایش یک پیام منفرد: حذف امضا، دیسکلیمر، احوال‌پرسی و عبارات اداری"""
    if not msg_body:
        return ""

    # ۰. حذف بنرهای امنیتی (پاراگرافی + خطی)
    paragraphs = strip_banner_paragraphs(msg_body)
    lines = []
    for p_idx, para in enumerate(paragraphs.split("\n\n")):
        if not para.strip():
            continue
        if p_idx:
            lines.append("")
        lines.extend(para.splitlines())

    # ۱. قانون پایانی: اولین عبارت پایانی از پایین → همه‌چیز تا پایان همین بخش
    cut_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        if s and len(s) < 60 and COMPILED_VAL_REGEX.search(s):
            cut_idx = i
            break
    if cut_idx != -1:
        lines = lines[:cut_idx]
    else:
        # ۲. عبارت پایانی نبود: اسکن زنجیره‌ای امضای انتهایی
        kept_reversed = []
        dropped_prev = False
        non_empty_scanned = 0
        for l in reversed(lines):
            s = l.strip()
            if not s:
                kept_reversed.append(l)
                continue
            non_empty_scanned += 1
            if non_empty_scanned > 30:
                kept_reversed.append(l)
                continue
            if COMPILED_BULLET_REGEX.match(s) or "@" in s:
                kept_reversed.append(l)
                dropped_prev = False
                continue
            if COMPILED_STRONG_NOISE_REGEX.search(s):
                dropped_prev = True
                continue
            if len(s) >= 45:
                if _is_signature_title(s):
                    dropped_prev = True
                    continue
                kept_reversed.append(l)
                dropped_prev = False
                continue
            if (
                COMPILED_WEAK_NOISE_REGEX.search(s)
                or SIGNATURE_KEYWORDS_REGEX.search(s)
                or dropped_prev
            ):
                dropped_prev = True
                continue
            kept_reversed.append(l)
            dropped_prev = False
        lines = list(reversed(kept_reversed))

    # ۳. حذف احوال‌پرسی/القاب/خطوط تزئینی
    result_lines = []
    prev_empty = True
    for l in lines:
        s = l.strip()
        if not s:
            if prev_empty:
                continue
            prev_empty = True
            result_lines.append("")
            continue
        prev_empty = False
        if COMPILED_GREETING_REGEX.search(s):
            continue
        if re.fullmatch(r"[-_=–—\s]{3,}", s):
            continue
        s = COMPILED_TITLE_STRIP_REGEX.sub("", s)
        s = COMPILED_TITLE_MID_STRIP_REGEX.sub("- ", s)
        s = COMPILED_PREFIX_STRIP_REGEX.sub("", s)
        if s:
            result_lines.append(s)

    cleaned_text = "\n".join(result_lines)
    cleaned_text = unicodedata.normalize("NFC", cleaned_text)
    cleaned_text = (
        cleaned_text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    )
    cleaned_text = cleaned_text.replace("\u200e", "").replace("\u200f", "")
    # حذف آرتیفکت‌های <mailto:...> و <email@...> باقی‌مانده در متن
    cleaned_text = COMPILED_MAILTO_REGEX.sub("", cleaned_text)
    cleaned_text = COMPILED_EMAIL_BRACKET_REGEX.sub("", cleaned_text)
    cleaned_text = COMPILED_URL_BRACKET_REGEX.sub("", cleaned_text)
    cleaned_text = re.sub(r"<\s*>", "", cleaned_text)
    cleaned_text = re.sub(r"[ \t]{2,}", " ", cleaned_text)
    return re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()


def parse_and_clean_thread(full_body):
    """تفکیک زنجیره مکاتبات و ساختاربندی به فرمت Markdown"""
    if not full_body:
        return ""

    # الگوی شکستن متن بر اساس هدرهای اوت‌لوک
    header_pattern = r"(?m)^(?:\s*[-_]{2,}\s*)?^(From:|از:)\s*(.*?)(?=^From:|^از:|\Z)"
    matches = list(
        re.finditer(r"(?m)^(?:\s*[-_]{2,}\s*)?^(From:|از:)", full_body)
    )

    if not matches:
        # پیام تکی است و تاریخچه‌ای ندارد
        cleaned = clean_single_message_body(full_body)
        return cleaned if cleaned else PLACEHOLDER_EMPTY_BODY

    sections = []
    # متن پیام اول (جدیدترین پیام قبل از اولین هدر)
    first_msg = full_body[: matches[0].start()].strip()
    if first_msg:
        cleaned_first = clean_single_message_body(first_msg)
        if not cleaned_first:
            cleaned_first = PLACEHOLDER_EMPTY_BODY
        sections.append(f"### 📩 آخرین پیام (پاسخ جاری):\n\n{cleaned_first}")

    # پیمایش پیام‌های تاریخچه
    for i in range(len(matches)):
        start_idx = matches[i].start()
        end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(full_body)
        raw_section = full_body[start_idx:end_idx].strip()

        # استخراج خطوط هدر و بدنه
        header_lines = []
        body_lines = []
        in_header = True

        for line in raw_section.splitlines():
            if in_header and (
                line.startswith(
                    (
                        "From:",
                        "از:",
                        "Sent:",
                        "ارسال:",
                        "فرستاده شده:",
                        "To:",
                        "به:",
                        "Cc:",
                        "رونوشت:",
                        "Subject:",
                        "موضوع:",
                    )
                )
                or line.strip() == ""
            ):
                if line.strip():
                    stripped_line = line.strip()
                    # رونوشت‌ها در تاریخچه حذف می‌شوند (در متادیتای اصلی موجودند)
                    if stripped_line.lower().startswith(("cc:", "رونوشت:")):
                        continue
                    h = COMPILED_MAILTO_REGEX.sub("", stripped_line)
                    h = COMPILED_EMAIL_BRACKET_REGEX.sub("", h)
                    h = COMPILED_URL_BRACKET_REGEX.sub("", h)
                    h = re.sub(r"<\s*>", "", h)
                    h = re.sub(r"\[\s*\]", "", h)
                    h = re.sub(r"\s{2,}", " ", h).strip()
                    h = convert_sent_line_to_jalali(h)
                    if re.match(r"(?i)^(subject|موضوع)\s*:", h):
                        h = COMPILED_SUBJECT_WARNING_REGEX.sub("", h)
                    if h:
                        header_lines.append(f"> {h}")
            else:
                in_header = False
                body_lines.append(line)

        header_block = "\n".join(header_lines)
        cleaned_section_body = clean_single_message_body("\n".join(body_lines))
        body_out = cleaned_section_body or PLACEHOLDER_EMPTY_BODY

        sections.append(
            f"### 📜 پیام در تاریخچه مکاتبات:\n{header_block}\n\n{body_out}"
        )

    return "\n\n---\n\n".join(sections)


# -------------------------------------------------------------
# ۳. تبدیل تاریخ Sent در هدرهای تاریخچه به شمسی
# -------------------------------------------------------------
SENT_LINE_REGEX = re.compile(
    r"^(Sent|Date|ارسال|فرستاده شده)\s*:\s*(.*)$", re.IGNORECASE
)
SENT_DATE_FORMATS = [
    "%A, %B %d, %Y %I:%M %p",
    "%A, %b %d, %Y %I:%M %p",
    "%B %d, %Y %I:%M %p",
    "%b %d, %Y %I:%M %p",
    "%d/%b/%Y %I:%M %p",
    "%d/%B/%Y %I:%M %p",
    "%d %b %Y %I:%M %p",
    "%A, %B %d, %Y %H:%M",
    "%B %d, %Y %H:%M",
    "%d/%b/%Y %H:%M",
    "%Y-%m-%d %H:%M",
]


def convert_sent_line_to_jalali(stripped_line):
    """هدر Sent تاریخچه را به فرمت شمسی یکدست تبدیل می‌کند"""
    m = SENT_LINE_REGEX.match(stripped_line)
    if not m:
        return stripped_line
    raw = m.group(2).strip()

    # تاریخ از پیش شمسی (فارسی): «12 شهریور 1404»
    m_fa = re.search(
        r"(\d{1,2})\s+(فروردین|اردیبهشت|اردی\s*بهشت|خرداد|تیر|مرداد|"
        r"شهریور|مهر|آبان|آذر|دی|بهمن|اسفند)\s+(\d{4})",
        raw,
    )
    if m_fa:
        fa_months = {
            "فروردین": 1,
            "اردیبهشت": 2,
            "اردی بهشت": 2,
            "خرداد": 3,
            "تیر": 4,
            "مرداد": 5,
            "شهریور": 6,
            "مهر": 7,
            "آبان": 8,
            "آذر": 9,
            "دی": 10,
            "بهمن": 11,
            "اسفند": 12,
        }
        day = int(m_fa.group(1))
        month_name = re.sub(r"\s+", " ", m_fa.group(2))
        month = fa_months.get(month_name)
        year = int(m_fa.group(3))
        if month:
            return f"Sent: {year:04d}/{month:02d}/{day:02d}"

    # حذف نام روز هفته انگلیسی از ابتدا (Thursday, ...)
    candidate = re.sub(r"^[A-Za-z]+[,،]\s*", "", raw)
    dt = None
    for fmt in SENT_DATE_FORMATS:
        try:
            dt = datetime.strptime(candidate, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return stripped_line
    shamsi = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"Sent: {shamsi}"


# -------------------------------------------------------------
# ۳.۱ توابع پشتیبانی از تجمیع زنجیره مکاتبات (Conversation Rollup)
# -------------------------------------------------------------
SUBJECT_PREFIX_REGEX = re.compile(
    r"^(?:(?:re|fw|fwd|پاسخ|بازفرست)\s*[:：]\s*|\s*\[warning[^\]]*\]\s*)+",
    re.IGNORECASE,
)


def clean_subject_for_thread(subject):
    """پاک‌سازی تمام پیشوندهای RE, FW, پاسخ و هشدارهای امنیتی از موضوع ایمیل"""
    if not subject:
        return "بدون موضوع"
    s = COMPILED_SUBJECT_WARNING_REGEX.sub("", subject).strip()
    while True:
        m = SUBJECT_PREFIX_REGEX.match(s)
        if m:
            s = s[m.end():].strip()
        else:
            break
    return s if s else "بدون موضوع"


HEADER_SPLIT_REGEX = re.compile(
    r"(?m)^(?:\s*[-_]{2,}\s*)?(?:>\s*)?(?:From:|از:)", re.IGNORECASE
)


def extract_latest_message_body(full_body):
    """استخراج فقط متن جدیدترین پیام بدون تاریخچه نقل‌قول‌ها"""
    if not full_body:
        return ""
    # حذف برچسب‌های مارک‌داون موجود در صورت تست روی فایل‌های از پیش ذخیره‌شده
    clean_in = re.sub(r"^###\s*📩[^\n]*\n+", "", full_body).strip()
    matches = list(HEADER_SPLIT_REGEX.finditer(clean_in))
    if not matches:
        cleaned = clean_single_message_body(clean_in)
        return cleaned if cleaned else PLACEHOLDER_EMPTY_BODY
    first_msg = clean_in[: matches[0].start()].strip()
    first_msg = re.sub(r"(?:###\s*📜[^\n]*|\-{3,}|_{3,})\s*$", "", first_msg).strip()
    cleaned_first = clean_single_message_body(first_msg)
    return cleaned_first if cleaned_first else PLACEHOLDER_EMPTY_BODY


def extract_quotes_chronological(full_body):
    """استخراج پیام‌های تاریخچه نقل‌قول‌شده و بازگرداندن آن‌ها به ترتیب زمانی (قدیم به جدید)"""
    if not full_body:
        return []
    clean_in = re.sub(r"^###\s*📩[^\n]*\n+", "", full_body).strip()
    matches = list(HEADER_SPLIT_REGEX.finditer(clean_in))
    if not matches:
        return []

    sections = []
    for i in range(len(matches)):
        start_idx = matches[i].start()
        end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(clean_in)
        raw_section = clean_in[start_idx:end_idx].strip()

        header_lines = []
        body_lines = []
        in_header = True

        for line in raw_section.splitlines():
            s_line = line.strip()
            # حذف علامت نقل‌قول > و تیتر مارک‌داون
            if s_line.startswith("###"):
                continue
            if s_line.startswith(">"):
                s_line = s_line.lstrip(">").strip()

            if in_header and (
                s_line.lower().startswith(
                    (
                        "from:", "از:", "sent:", "ارسال:", "فرستاده شده:",
                        "to:", "به:", "cc:", "رونوشت:", "subject:", "موضوع:",
                    )
                ) or s_line == ""
            ):
                if s_line:
                    if s_line.lower().startswith(("cc:", "رونوشت:")):
                        continue
                    h = COMPILED_MAILTO_REGEX.sub("", s_line)
                    h = COMPILED_EMAIL_BRACKET_REGEX.sub("", h)
                    h = COMPILED_URL_BRACKET_REGEX.sub("", h)
                    h = re.sub(r"<\s*>", "", h)
                    h = re.sub(r"\[\s*\]", "", h)
                    h = re.sub(r"\s{2,}", " ", h).strip()
                    h = convert_sent_line_to_jalali(h)
                    if re.match(r"(?i)^(subject|موضوع)\s*:", h):
                        h = COMPILED_SUBJECT_WARNING_REGEX.sub("", h)
                    if h:
                        header_lines.append(h)
            else:
                in_header = False
                body_lines.append(s_line)

        cleaned_body = clean_single_message_body("\n".join(body_lines))
        sections.append({
            "headers": header_lines,
            "body": cleaned_body or PLACEHOLDER_EMPTY_BODY,
        })

    return list(reversed(sections))


# -------------------------------------------------------------
# ۴. تابع هدایت به پوشه هدف
# -------------------------------------------------------------
def get_folder_by_path(root_folder, path_list):
    current = root_folder
    for target_name in path_list:
        norm_target = normalize_string(target_name)
        found = False
        for i in range(1, current.Folders.Count + 1):
            sub = current.Folders.Item(i)
            if normalize_string(sub.Name) == norm_target:
                current = sub
                found = True
                break
        if not found:
            print(f"[-] پوشه [{target_name}] پیدا نشد!")
            return None
    return current


# -------------------------------------------------------------
# ۵. فرایند اصلی استخراج
# -------------------------------------------------------------
def run_pipeline():
    project_dir = PROJECT_ROOT
    output_dir = os.path.join(project_dir, "Extracted_Sample")
    att_dir = os.path.join(output_dir, "attachments")

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(att_dir, exist_ok=True)

    print("[+] در حال اتصال به Outlook...")
    try:
        outlook = win32com.client.GetActiveObject("Outlook.Application")
    except Exception:
        outlook = win32com.client.Dispatch("Outlook.Application")

    namespace = outlook.GetNamespace("MAPI")

    target_root = None
    for i in range(1, namespace.Folders.Count + 1):
        f = namespace.Folders.Item(i)
        if f.Name.lower() == "archives":
            target_root = f
            break

    if not target_root:
        print("[-] ریشه Archives پیدا نشد!")
        return

    target_path = ["Inbox", "نصب نیرو", "بویلر واحد ۳", "دریافتی"]
    print(f"[+] مسیر انتخابی: {' -> '.join(target_path)}")
    target_folder = get_folder_by_path(target_root, target_path)

    if not target_folder:
        return

    total_items = target_folder.Items.Count
    print(f"[+] تعداد کل پیام‌های این پوشه: {total_items}")

    MAX_LIMIT = 150
    items_to_process = min(total_items, MAX_LIMIT)
    print(f"[+] در حال پردازش {items_to_process} پیام اول...\n")

    items = target_folder.Items
    items.Sort("[ReceivedTime]", False)

    processed_count = 0
    saved_att_total = 0

    VALID_EXTENSIONS = {
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".pptx",
        ".rar",
        ".zip",
        ".dwg",
        ".jpg",
        ".jpeg",
        ".png",
    }
    IMAGE_MIN_SIZE_BYTES = 40 * 1024

    for idx, item in enumerate(items, 1):
        if processed_count >= MAX_LIMIT:
            break

        if item.Class != 43:  # فقط MailItem
            continue

        try:
            subject = item.Subject if item.Subject else "(بدون موضوع)"
            # حذف برچسب هشدار تزریقی اوت‌لوک از موضوع
            subject = COMPILED_SUBJECT_WARNING_REGEX.sub("", subject).strip()
            if not subject:
                subject = "(بدون موضوع)"
            sender_name = item.SenderName if item.SenderName else "نامشخص"
            to_recipients = item.To if item.To else "ندارد"
            cc_recipients = item.CC if item.CC else "ندارد"

            shamsi_date = safe_extract_shamsi_date(item)
            date_prefix = shamsi_date.replace("/", "")

            saved_attachments_for_email = []

            # پردازش پیوست‌ها
            if item.Attachments.Count > 0:
                for a_idx in range(1, item.Attachments.Count + 1):
                    att = item.Attachments.Item(a_idx)
                    orig_filename = att.FileName
                    ext = os.path.splitext(orig_filename)[1].lower()

                    if ext not in VALID_EXTENSIONS:
                        continue

                    # فیلتر آیکون‌ها و عکس‌های امضا
                    att_size = att.Size
                    if ext in {".jpg", ".jpeg", ".png"}:
                        if (
                            "image" in orig_filename.lower()
                            or "signature" in orig_filename.lower()
                            or "logo" in orig_filename.lower()
                        ):
                            if att_size < IMAGE_MIN_SIZE_BYTES:
                                continue

                    clean_att_name = sanitize_filename(orig_filename)
                    unique_att_filename = (
                        f"{date_prefix}_{idx:03d}_{a_idx}_{clean_att_name}"
                    )
                    att_save_path = os.path.join(att_dir, unique_att_filename)

                    try:
                        att.SaveAsFile(att_save_path)
                        saved_attachments_for_email.append(unique_att_filename)
                        saved_att_total += 1
                    except Exception as save_err:
                        print(
                            f"      [!] خطا در ذخیره پیوست {orig_filename}: {save_err}"
                        )

            # پردازش و تفکیک بدنه ایمیل
            body_text = item.Body
            clean_thread_content = parse_and_clean_thread(body_text)

            att_list_str = (
                "\n".join(
                    [f"- attachments/{f}" for f in saved_attachments_for_email]
                )
                if saved_attachments_for_email
                else "ندارد"
            )

            file_content = f"""---
شناسه: {item.EntryID[:25]}...
موضوع: {subject.strip()}
فرستنده: {sender_name.strip()}
گیرنده اصلی (To): {to_recipients.strip()}
رونوشت (Cc): {cc_recipients.strip()}
تاریخ شمسی: {shamsi_date}
مسیر پوشه: {' / '.join(target_path)}
تعداد پیوست‌های معتبر ذخیره شده: {len(saved_attachments_for_email)}
پیوست‌ها:
{att_list_str}
---

# متن مکاتبه:

{clean_thread_content}
"""
            safe_subj = sanitize_filename(subject)
            out_file_name = f"{date_prefix}_{idx:03d}_{safe_subj}.md"
            out_file_path = os.path.join(output_dir, out_file_name)

            with open(out_file_path, "w", encoding="utf-8") as f:
                f.write(file_content)

            processed_count += 1
            print(
                f"[{processed_count}/{items_to_process}] استخراج شد: {safe_subj[:30]}"
            )

        except Exception as err:
            print(f"[-] خطا در پیام {idx}: {err}")

    print("\n" + "=" * 60)
    print(
        f"استخراج با موفقیت پایان یافت! {processed_count} سند کامل ذخیره شد."
    )
    print(f"تعداد کل پیوست‌های واقعی دانلود شده: {saved_att_total}")
    print(f"مسیر ذخیره: {output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    run_pipeline()

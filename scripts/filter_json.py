# scripts/filter_json.py
# -*- coding: utf-8 -*-
import json
import re
import unicodedata
from pathlib import Path
import requests

# ========= إعدادات =========
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"
LIVEONSAT_PATH = MATCHES_DIR / "liveonsat_raw.json"

YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"

# نافذة التطابق بالوقت (دقائق)
TIME_TOL_MIN = 25

# ========= أدوات مساعدة =========
EMOJI_MISC_RE = re.compile(r'[\u2600-\u27BF\U0001F300-\U0001FAFF]+')
BEIN_EN_RE = re.compile(r'bein\s*sports?', re.I)
# العربية: بي/بى + (أن|ان) + سبورت (مرنة)
BEIN_AR_RE = re.compile(r'(?:بي|بى)\s*[^A-Za-z0-9]{0,2}\s*ا?ن\s*[^A-Za-z0-9]{0,4}\s*سبورت', re.I)

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
TIME_RE_12 = re.compile(r'^\s*(\d{1,2}):(\d{2})\s*([AP]M)\s*$', re.I)
TIME_RE_24 = re.compile(r'^\s*(\d{1,2}):(\d{2})\s*$')

def to_western_digits(s: str) -> str:
    return (s or "").translate(ARABIC_DIGITS)

def kickoff_to_minutes(hhmm: str) -> int | None:
    if not hhmm:
        return None
    s = to_western_digits(hhmm).strip()
    m = TIME_RE_12.match(s)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if ap == "PM" and h != 12:
            h += 12
        if ap == "AM" and h == 12:
            h = 0
        return h*60 + mi
    m = TIME_RE_24.match(s)
    if m:
        return int(m.group(1))*60 + int(m.group(2))
    return None

def minutes_close(m1: int | None, m2: int | None, tol: int = TIME_TOL_MIN) -> bool:
    if m1 is None or m2 is None:
        return False
    return abs(m1 - m2) <= tol

def strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = str(text)
    text = EMOJI_MISC_RE.sub('', text)
    text = re.sub(r'\(.*?\)', '', text)
    text = strip_accents(text)
    text = text.lower()
    text = text.replace("&", "and")
    text = re.sub(r'\b(fc|sc|cf|u\d+)\b', '', text)
    text = (text
            .replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
            .replace("ى", "ي").replace("ة", "ه").replace("ال", "")
            .replace("ـ", ""))
    text = text.replace(" ", "").replace("-", "").replace("_", "")
    text = re.sub(r'[^a-z0-9\u0600-\u06FF]', '', text)
    return text.strip()

def clean_channel_display(name: str) -> str:
    if not name:
        return ""
    s = str(name)
    s = EMOJI_MISC_RE.sub("", s)
    s = re.sub(r"\s*\((?:\$?\/?geo\/?R|geo\/?R|\$\/?geo|tjk)\)\s*", "", s, flags=re.I)
    s = re.sub(r"📺|\[online\]|\[app\]", "", s, flags=re.I)
    s = re.sub(r"\s*hd\s*$", " HD", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def to_list_channels(val):
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return []
        parts = re.split(r"\s*(?:,|،|/|\||&| و | and )\s*", s, flags=re.I)
        return [p for p in parts if p]
    return []

def unique_preserving(seq):
    seen, out = set(), []
    for x in seq:
        k = str(x).lower().strip()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out

def is_bein(name: str) -> bool:
    s = name or ""
    return bool(BEIN_EN_RE.search(s) or BEIN_AR_RE.search(s))

def extract_bein_signal(ch_name: str):
    """
    يرجّع dict مثل: {"is_bein": True/False, "mena": True/False/None, "num": int|None}
    (نستخدمه للمطابقة فقط، لا نضيف beIN من live للإخراج)
    """
    disp = clean_channel_display(ch_name)
    s = to_western_digits(disp)
    ok = is_bein(s)
    mena = None
    if re.search(r'\bmena\b|\bmiddle\s*east\b', s, re.I):
        mena = True
    if "الشرقالاوسط" in normalize_text(s):
        mena = True
    mnum = re.search(r'\b(\d{1,2})\b', s)
    num = int(mnum.group(1)) if mnum else None
    return {"is_bein": bool(ok), "mena": mena, "num": num}

# ========= القنوات المسموحة من liveonsat (حسب طلبك) =========
# - Sky: فقط Main Event + Premier League (بما فيها UK)
# - TNT: فقط TNT Sports (بدون رقم) + 1 + 2
# - Alkass: مرفوضة تمامًا
# - IRIB: TV3 + Varzesh
# - Varzish: كل صيغ Varzish TV/Sport
# - نحتفظ بباقي القنوات اللي كنت تريدها سابقًا (DAZN PT, Sport TV PT, ESPN Brazil, Football HD, Persiana, MBC Action, SSC, Shahid, Thmanyah, Starzplay, Abu Dhabi Sport)

DENY_PATTERNS = [
    re.compile(r'\balkass\b', re.I),
    re.compile(r'\bal\s*kass\b', re.I),
    re.compile(r'الكاس|الكأس', re.I),
]

SKY_ALLOWED_RE = re.compile(
    r'\bsky\s*sport[s]?\s*(?:main\s*event|premier\s*league(?:\s*uk)?)\b', re.I
)

TNT_BASE_RE = re.compile(r'\btnt\s*sports?\b(?:\s*(\d+))?', re.I)

IRIB_TV3_RE = re.compile(r'\birib\s*tv\s*3\b', re.I)
IRIB_VARZESH_RE = re.compile(r'\birib\s*varzesh\b', re.I)

VARZISH_RE = re.compile(r'\bvarzish\b', re.I)

# ✅ جديد: مطابقة DAZN Portugal (مع/بدون رقم) و Sport TV Portugal (مع/بدون رقم)
DAZN_PT_RE = re.compile(r'\bdazn\b\s*(?:\d+\s*)?portugal\b', re.I)
SPORTTV_PT_RE = re.compile(r'\bsport\s*tv\b\s*(?:\d+\s*)?portugal\b', re.I)

# باقي العوائل/القنوات المسموحة (عام)
GENERAL_ALLOWED_SUBSTRINGS = {
    "football hd",
    "dazn portugal",            # ستبقى، لكن أصبح عندنا ريجيكس أدق فوق
    "sport tv portugal",
    "espn 1 brazil", "espn 2 brazil", "espn 3 brazil", "espn 4 brazil", "espn 5 brazil", "espn 6 brazil", "espn 7 brazil",
    "persiana sport", "mbc action", "ssc ", " ssc", "shahid", "thmanyah", "starzplay", "abu dhabi sport",
    "irib varzesh", "irib tv3", "varzish",  # توكيد إضافي
}

def is_denied_channel(name: str) -> bool:
    if not name:
        return True
    n = name.lower()
    for pat in DENY_PATTERNS:
        if pat.search(n):
            return True
    return False

def sky_allowed(name: str) -> bool:
    return bool(SKY_ALLOWED_RE.search(name or ""))

def tnt_allowed(name: str) -> bool:
    m = TNT_BASE_RE.search(name or "")
    if not m:
        return False
    num = m.group(1)
    if num is None:  # TNT Sports بدون رقم
        return True
    return num in {"1", "2"}

def is_supported_channel(name: str) -> bool:
    if not name:
        return False
    disp = clean_channel_display(name)
    n = disp.lower()

    # 1) ممنوع Alkass بالكامل
    if is_denied_channel(n):
        return False

    # 2) beIN من live ممنوعة (نستخدمها للمطابقة فقط)
    if is_bein(disp):
        return False

    # 3) Sky المسموح فقط
    if "sky" in n:
        return sky_allowed(disp)

    # 4) TNT المسموح فقط
    if "tnt" in n:
        return tnt_allowed(disp)

    # ✅ 5) DAZN Portugal (بدون رقم أو 1-6)
    if DAZN_PT_RE.search(disp):
        return True

    # ✅ 6) Sport TV Portugal (بدون رقم أو مع رقم)
    if SPORTTV_PT_RE.search(disp):
        return True

    # 7) IRIB TV3 / IRIB Varzesh
    if IRIB_TV3_RE.search(disp) or IRIB_VARZESH_RE.search(disp):
        return True

    # 8) Varzish TV/Sport
    if VARZISH_RE.search(disp):
        return True

    # 9) باقي العوائل العامة اللي توافق رغبتك الأصلية
    for sub in GENERAL_ALLOWED_SUBSTRINGS:
        if sub in n:
            return True

    return False

# ========= توحيد أسماء القنوات =========
CHANNEL_CANON_RULES = [
    # Thmanyah / Starzplay / Abu Dhabi
    (re.compile(r"thmanyah\s*(\d+)", re.I),            lambda m: (f"thmanyah-{m.group(1)}", f"Thmanyah {m.group(1)}")),
    (re.compile(r"starzplay\s*(\d+)", re.I),           lambda m: (f"starzplay-{m.group(1)}", f"Starzplay {m.group(1)}")),
    (re.compile(r"starzplay\b", re.I),                 lambda m: ("starzplay-1", "Starzplay 1")),
    (re.compile(r"abu\s*dhabi\s*sport\s*(\d+)", re.I), lambda m: (f"abudhabi-{m.group(1)}", f"Abu Dhabi Sport {m.group(1)}")),
    # SSC / Shahid / Football
    (re.compile(r"ssc\s*extra", re.I),                 lambda m: ("ssc-extra", "SSC Extra HD")),
    (re.compile(r"ssc\s*(\d+)", re.I),                 lambda m: (f"ssc-{m.group(1)}", f"SSC {m.group(1)} HD")),
    (re.compile(r"shahid\s*(vip)?", re.I),             lambda m: ("shahid", "Shahid MBC")),
    (re.compile(r"football\s*hd", re.I),               lambda m: ("football-hd", "Football HD")),
    (re.compile(r"persiana\s*sport", re.I),            lambda m: ("persiana-sport", "Persiana Sport HD")),
    # Sky (Main Event / Premier League (UK or not))
    (re.compile(r"sky\s*sport[s]?\s*main\s*event", re.I),
                                                     lambda m: ("sky-main-event", "Sky Sports Main Event HD")),
    (re.compile(r"sky\s*sport[s]?\s*premier\s*league(?:\s*uk)?", re.I),
                                                     lambda m: ("sky-premier-league", "Sky Sports Premier League UK" if "uk" in m.group(0).lower() else "Sky Sport Premier League HD")),
    # DAZN PT
    (re.compile(r"dazn\s*1\s*portugal", re.I),         lambda m: ("dazn-pt-1", "DAZN 1 Portugal HD")),
    (re.compile(r"dazn\s*2\s*portugal", re.I),         lambda m: ("dazn-pt-2", "DAZN 2 Portugal HD")),
    (re.compile(r"dazn\s*3\s*portugal", re.I),         lambda m: ("dazn-pt-3", "DAZN 3 Portugal HD")),
    (re.compile(r"dazn\s*4\s*portugal", re.I),         lambda m: ("dazn-pt-4", "DAZN 4 Portugal HD")),
    (re.compile(r"dazn\s*5\s*portugal", re.I),         lambda m: ("dazn-pt-5", "DAZN 5 Portugal HD")),
    (re.compile(r"dazn\s*6\s*portugal", re.I),         lambda m: ("dazn-pt-6", "DAZN 6 Portugal HD")),
    # ✅ عام: DAZN Portugal بدون رقم
    (re.compile(r"dazn\s*portugal", re.I),             lambda m: ("dazn-pt", "DAZN Portugal HD")),
    # Sport TV PT
    (re.compile(r"sport\s*tv\s*1\s*portugal", re.I),   lambda m: ("sporttv-pt-1", "Sport TV1 Portugal HD")),
    (re.compile(r"sport\s*tv\s*2\s*portugal", re.I),   lambda m: ("sporttv-pt-2", "Sport TV2 Portugal HD")),
    # ✅ عام: Sport TV Portugal بدون رقم
    (re.compile(r"sport\s*tv\s*portugal", re.I),       lambda m: ("sporttv-pt", "Sport TV Portugal HD")),
    # TNT Sports (فقط 1 و 2 أو بدون رقم)
    (re.compile(r"tnt\s*sports?\s*1\b", re.I),         lambda m: ("tnt-1", "TNT Sports 1 HD")),
    (re.compile(r"tnt\s*sports?\s*2\b", re.I),         lambda m: ("tnt-2", "TNT Sports 2 HD")),
    (re.compile(r"tnt\s*sports?(?!\s*\d)", re.I),      lambda m: ("tnt", "TNT Sports HD")),
    # IRIB
    (re.compile(r"irib\s*tv\s*3", re.I),               lambda m: ("irib-tv3", "IRIB TV3 HD")),
    (re.compile(r"irib\s*varzesh", re.I),              lambda m: ("irib-varzesh", "IRIB Varzesh HD")),
    # Varzish
    (re.compile(r"varzish", re.I),                     lambda m: ("varzish", "Varzish TV Sport HD")),
]

def channel_key_and_display(raw_name: str) -> tuple[str, str]:
    disp = clean_channel_display(raw_name)
    low = disp.lower()
    if is_bein(disp):
        has_mena = bool(re.search(r'\bmena\b|\bmiddle\s*east\b', low)) or ("الشرقالاوسط" in normalize_text(disp))
        mnum = re.search(r'\b(\d{1,2})\b', to_western_digits(disp))
        if has_mena and mnum:
            return (f"bein-mena-{mnum.group(1)}", f"beIN Sports MENA {mnum.group(1)} HD")
        if has_mena:
            return ("bein-mena", "beIN Sports MENA HD")
        if mnum:
            return (f"bein-{mnum.group(1)}", f"beIN Sports {mnum.group(1)} HD")
        return ("bein", "beIN Sports HD")
    for pat, conv in CHANNEL_CANON_RULES:
        m = pat.search(disp)
        if m:
            key, fixed = conv(m)
            return (key.lower(), fixed)
    return (low, disp)

def dedupe_channels_preserve_order(ch_list: list[str]) -> list[str]:
    seen_keys, out_disp = set(), []
    for ch in ch_list:
        if not ch:
            continue
        key, disp = channel_key_and_display(ch)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out_disp.append(disp)
    return out_disp

# ========= buckets (نوع البطولة) =========
def comp_bucket(name: str) -> str:
    n = normalize_text(name)
    if "uefa" in n or "championsleague" in n or "دوريابطالاوروبا" in n:
        return "UEFA-CL"
    if "afc" in n or "دوريابطالاسيا" in n or "اسيا" in n:
        return "AFC-CL"
    if "carabao" in n or "efl" in n or ("كاس" in n and "الانجليزي" in n):
        return "ENG-EFL"
    if "المغربي" in n or "botola" in n:
        return "MAR-BOT"
    return "OTHER"

# ========= قراءة liveonsat إلى فهرس بالوقت + beIN + bucket =========
def build_live_time_index(live_data: dict):
    idx = []
    matches = (live_data or {}).get("matches", []) or []
    for m in matches:
        t = (m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff") or "").strip()
        tmin = kickoff_to_minutes(t)
        if tmin is None:
            continue

        comp = m.get("competition") or ""
        bucket = comp_bucket(comp)

        # قنوات live: نلتقط beIN كإشارة، ونكوّن allowed فقط حسب فلترك
        raw_channels = []
        for ck in ("channels_raw", "channels", "tv_channels", "broadcasters", "broadcaster"):
            if ck in m and m[ck]:
                raw = m[ck]
                if isinstance(raw, list):
                    raw_channels.extend([str(x) for x in raw])
                elif isinstance(raw, str):
                    raw_channels.extend(to_list_channels(raw))

        bein_nums = set()
        allowed = []
        for ch in raw_channels:
            disp = clean_channel_display(ch)
            if not disp:
                continue
            # beIN: اجمع رقمها كمؤشّر مطابقة فقط
            sig = extract_bein_signal(disp)
            if sig["is_bein"]:
                if sig["num"]:
                    bein_nums.add(sig["num"])
                continue  # لا نضيف beIN لإخراج القنوات

            # فلترة القنوات حسب القواعد الجديدة
            if is_supported_channel(disp):
                allowed.append(disp)

        allowed = dedupe_channels_preserve_order(allowed)

        idx.append({
            "tmin": tmin,
            "bucket": bucket,
            "bein_nums": bein_nums,     # مجموعة أرقام beIN الموجودة في live لهذه المباراة
            "allowed": allowed,         # قد تكون فاضية
        })
    return idx

# ========= قنوات يلا =========
def collect_yalla_channels(y: dict) -> list[str]:
    keys = ["channels_raw","channels","tv_channels","channel","channel_ar","channel_en","broadcasters","broadcaster"]
    out = []
    for k in keys:
        if k in y and y[k]:
            out.extend(to_list_channels(y[k]))
    return unique_preserving(out)

def yalla_primary_channel(y: dict) -> str | None:
    chs = [clean_channel_display(c) for c in collect_yalla_channels(y)]
    return chs[0] if chs else None

def yalla_bein_num(y: dict):
    for c in collect_yalla_channels(y):
        disp = clean_channel_display(c)
        sig = extract_bein_signal(disp)
        if sig["is_bein"] and sig["num"]:
            return sig["num"]
    return None

# ========= اختيار أفضل مرشّح من live =========
def pick_best_live_candidate(cands: list[dict], y_bein: int | None, y_bucket: str) -> dict | None:
    if not cands:
        return None
    # 1) لو عندي رقم beIN من يلا → صفّي على نفس الرقم
    if y_bein is not None:
        c_bein = [li for li in cands if y_bein in li["bein_nums"]]
        if len(c_bein) == 1:
            return c_bein[0]
        elif len(c_bein) > 1:
            cands = c_bein
    # 2) لو عندي bucket معروف → صفّي عليه
    if y_bucket != "OTHER":
        c_bucket = [li for li in cands if li["bucket"] == y_bucket]
        if len(c_bucket) == 1:
            return c_bucket[0]
        elif len(c_bucket) > 1:
            cands = c_bucket
    # 3) اختَر الأغنى بالقنوات المسموحة
    cands_sorted = sorted(cands, key=lambda li: len(li["allowed"]), reverse=True)
    return cands_sorted[0]

# ========= الرئيسي =========
def filter_matches():
    # 1) يلا شوت
    try:
        yresp = requests.get(YALLASHOOT_URL, timeout=25)
        yresp.raise_for_status()
        yalla = yresp.json()
    except Exception as e:
        print(f"[x] ERROR fetching yallashoot: {e}")
        return
    y_matches = (yalla or {}).get("matches", []) or []
    print(f"[i] Yalla matches: {len(y_matches)}")

    # 2) liveonsat (محلي)
    try:
        with LIVEONSAT_PATH.open("r", encoding="utf-8") as f:
            live_data = json.load(f)
    except Exception as e:
        print(f"[!] WARN reading liveonsat: {e}")
        live_data = {"matches": []}
    live_idx = build_live_time_index(live_data)
    print(f"[i] Live time-index: {len(live_idx)}")

    # 3) دمج: “مرشّح واحد فقط”
    out_matches = []
    matched_from_live = 0

    for m in y_matches:
        y_time = (m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff") or "").strip()
        y_tmin = kickoff_to_minutes(y_time)
        y_bucket = comp_bucket(m.get("competition") or "")
        y_bein = yalla_bein_num(m)

        merged = []
        primary = yalla_primary_channel(m)
        if primary:
            merged.append(primary)

        best = None
        if y_tmin is not None:
            cands = [li for li in live_idx if minutes_close(y_tmin, li["tmin"], tol=TIME_TOL_MIN)]
            best = pick_best_live_candidate(cands, y_bein, y_bucket)

        if best and best["allowed"]:
            merged.extend(best["allowed"])
            matched_from_live += 1

        merged = dedupe_channels_preserve_order(merged)

        out_matches.append({
            "competition": m.get("competition") or "",
            "kickoff_baghdad": y_time,
            "home_team": (m.get("home") or m.get("home_team") or "").strip(),
            "away_team": (m.get("away") or m.get("away_team") or "").strip(),
            "channels_raw": merged,
            "home_logo": m.get("home_logo"),
            "away_logo": m.get("away_logo"),
            "status_text": m.get("status_text"),
            "result_text": m.get("result_text"),
        })

    output = {
        "date": (yalla or {}).get("date"),
        "source_url": "yallashoot (primary) + liveonsat (single-best-by-time, custom channel filter)",
        "matches": out_matches
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[✓] Done. yalla: {len(y_matches)} | matched_from_live: {matched_from_live} | written: {len(out_matches)}")

if __name__ == "__main__":
    filter_matches()

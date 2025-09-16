# scripts/filter_json.py
# -*- coding: utf-8 -*-
import json
import re
import unicodedata
from pathlib import Path
import requests
from datetime import datetime

# ==== المسارات/الإعدادات ====
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH_LIVE = MATCHES_DIR / "liveonsat_raw.json"     # مصدر القنوات الإضافية (EN)
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"      # الناتج
YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"

# ==== أدوات مساعدة عامة ====
EMOJI_MISC_RE = re.compile(r'[\u2600-\u27BF\U0001F300-\U0001FAFF]+')
BEIN_RE = re.compile(r'bein\s*sports?', re.I)
TIME_RE = re.compile(r'^(\d{1,2}):(\d{2})$')

def strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

def normalize_text(text: str) -> str:
    """تطبيع قوي للاستخدام بالمفاتيح/المطابقة/الفلاتر الجزئية."""
    if not text:
        return ""
    text = str(text)
    text = EMOJI_MISC_RE.sub('', text)
    text = re.sub(r'\(.*?\)', '', text)
    text = strip_accents(text)
    text = text.lower()
    text = text.replace("&", "and")
    text = re.sub(r'\b(fc|sc|cf|u\d+)\b', '', text)
    # بدائل عربية شائعة
    text = (text
            .replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
            .replace("ى", "ي").replace("ة", "ه").replace("ال", "")
            .replace("ـ", ""))
    text = text.replace(" ", "").replace("-", "").replace("_", "")
    text = re.sub(r'[^a-z0-9\u0600-\u06FF]', '', text)
    return text.strip()

def unique_preserving(seq):
    seen, out = set(), []
    for x in seq:
        k = str(x).lower().strip()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out

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

def is_bein_channel(name: str) -> bool:
    return bool(BEIN_RE.search(name or ""))

# ==== القنوات المسموحة (whitelist) كما هي ====
SUPPORTED_CHANNELS = [
    "MATCH! Futbol 1", "MATCH! Futbol 2", "MATCH! Futbol 3",
    "Football HD",
    "Sport TV1 Portugal HD", "Sport TV2 Portugal HD",
    "ESPN 1 Brazil", "ESPN 2 Brazil", "ESPN 3 Brazil", "ESPN 4 Brazil", "ESPN 5 Brazil", "ESPN 6 Brazil", "ESPN 7 Brazil",
    "DAZN 1 Portugal HD", "DAZN 2 Portugal HD", "DAZN 3 Portugal HD", "DAZN 4 Portugal HD", "DAZN 5 Portugal HD", "DAZN 6 Portugal HD",
    "MATCH! Premier HD", "Sky Sports Main Event HD", "Sky Sport Premier League HD", "IRIB Varzesh HD",
    "Persiana Sport HD", "MBC Action HD", "TNT Sports 1 HD", "TNT Sports 2 HD", "TNT Sports HD",
    "MBC masrHD", "MBC masr2HD", "ssc1 hd", "ssc2 hd", "Shahid MBC",
    # تطبيقك (جديد)
    "Thmanyah 1", "Thmanyah 2", "Thmanyah 3",
    "Starzplay 1", "Starzplay 2",
    "Abu Dhabi Sport 1", "Abu Dhabi Sport 2",
]
ALLOWED_SUBSTRINGS = {
    "ssc ", " ssc", "ssc1", "ssc2", "ssc3", "ssc4", "ssc5", "ssc6", "ssc7", "ssc extra", "ssc sport",
    "alkass", "al kass", "al-kass", "الكاس", "الكأس",
    "shahid", "shahid vip", "shahid mbc",
    "mbc action", "persiana sport", "irib varzesh", "football hd",
    "thmanyah", "starzplay", "abu dhabi sport"
}

_supported_tokens = set()
for c in SUPPORTED_CHANNELS:
    cl = c.lower()
    _supported_tokens.add(cl)
    _supported_tokens.add(cl.replace(" hd", ""))

def is_supported_channel(name: str) -> bool:
    if not name:
        return False
    n = name.lower()
    if any(tok in n for tok in _supported_tokens):
        return True
    if any(sub in n for sub in ALLOWED_SUBSTRINGS):
        return True
    return False

# ==== توحيد أسماء القنوات لإزالة التكرار ====
CHANNEL_CANON_RULES = [
    (re.compile(r"thmanyah\s*(\d+)", re.I),                lambda m: (f"thmanyah-{m.group(1)}", f"Thmanyah {m.group(1)}")),
    (re.compile(r"starzplay\s*(\d+)", re.I),               lambda m: (f"starzplay-{m.group(1)}", f"Starzplay {m.group(1)}")),
    (re.compile(r"starzplay\b", re.I),                     lambda m: ("starzplay-1", "Starzplay 1")),
    (re.compile(r"abu\s*dhabi\s*sport\s*(\d+)", re.I),     lambda m: (f"abudhabi-{m.group(1)}", f"Abu Dhabi Sport {m.group(1)}")),
    (re.compile(r"(al[\s-]?kass|الكاس|الكأس)\s*(?:channel\s*)?(\d+)", re.I),
                                                       lambda m: (f"alkass-{m.group(2)}", f"Alkass {m.group(2)} HD")),
    (re.compile(r"^(?:الكاس|الكأس)\s*(\d+)", re.I),     lambda m: (f"alkass-{m.group(1)}", f"Alkass {m.group(1)} HD")),
    (re.compile(r"^al\s*kass\s*(\d+)", re.I),           lambda m: (f"alkass-{m.group(1)}", f"Alkass {m.group(1)} HD")),
    (re.compile(r"^alkass\s*(\d+)", re.I),              lambda m: (f"alkass-{m.group(1)}", f"Alkass {m.group(1)} HD")),
    (re.compile(r"ssc\s*extra", re.I),                   lambda m: ("ssc-extra", "SSC Extra HD")),
    (re.compile(r"ssc\s*(\d+)", re.I),                   lambda m: (f"ssc-{m.group(1)}", f"SSC {m.group(1)} HD")),
    (re.compile(r"shahid\s*(vip)?", re.I),               lambda m: ("shahid", "Shahid MBC")),
    (re.compile(r"football\s*hd", re.I),                 lambda m: ("football-hd", "Football HD")),
    (re.compile(r"sky\s*sport[s]?\s*premier\s*league", re.I),
                                                       lambda m: ("sky-premier-league", "Sky Sport Premier League HD")),
    (re.compile(r"sky\s*sport[s]?\s*main\s*event", re.I),
                                                       lambda m: ("sky-main-event", "Sky Sports Main Event HD")),
    (re.compile(r"dazn\s*1\s*portugal", re.I),           lambda m: ("dazn-pt-1", "DAZN 1 Portugal HD")),
    (re.compile(r"dazn\s*2\s*portugal", re.I),           lambda m: ("dazn-pt-2", "DAZN 2 Portugal HD")),
    (re.compile(r"dazn\s*3\s*portugal", re.I),           lambda m: ("dazn-pt-3", "DAZN 3 Portugal HD")),
    (re.compile(r"mbc\s*action", re.I),                  lambda m: ("mbc-action", "MBC Action HD")),
    (re.compile(r"persiana\s*sport", re.I),              lambda m: ("persiana-sport", "Persiana Sport HD")),
    (re.compile(r"irib\s*varzesh", re.I),                lambda m: ("irib-varzesh", "IRIB Varzesh HD")),
    (re.compile(r"tnt\s*sports?\s*1", re.I),             lambda m: ("tnt-1", "TNT Sports 1 HD")),
    (re.compile(r"tnt\s*sports?\s*2", re.I),             lambda m: ("tnt-2", "TNT Sports 2 HD")),
]

def channel_key_and_display(raw_name: str) -> tuple[str, str]:
    disp = clean_channel_display(raw_name)
    low = disp.lower()

    if is_bein_channel(disp):
        # نسمح بعرض beIN لكن لن نأخذ beIN من live فيما بعد
        has_mena = bool(re.search(r'\bmena\b|\bmiddle\s*east\b', low))
        mnum = re.search(r'\b(\d+)\b', disp)
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
    seen_keys = set()
    out_disp = []
    for ch in ch_list:
        if not ch:
            continue
        key, disp = channel_key_and_display(ch)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out_disp.append(disp)
    return out_disp

# ==== قاموس AR -> EN صغير لزيادة فرص التطابق ====
AR2EN = {
    "ريال مدريد": "Real Madrid",
    "مارسيليا": "Marseille",
    "برشلونة": "Barcelona",
    "اتلتيكو مدريد": "Atletico Madrid",
    "بايرن ميونخ": "Bayern Munich",
    "انتر": "Inter",
    "ميلان": "AC Milan",
    "يوفنتوس": "Juventus",
    "روما": "Roma",
    "ليفربول": "Liverpool",
    "مانشستر سيتي": "Manchester City",
    "مانشستر يونايتد": "Manchester United",
    "ارسنال": "Arsenal",
    "توتنهام": "Tottenham",
    "باريس سان جيرمان": "Paris Saint-Germain",
    "مارسيليا": "Marseille",
}

def ar_to_en_guess(name_ar: str) -> str:
    name_ar = (name_ar or "").strip()
    if not name_ar:
        return ""
    # قاموس مباشر
    if name_ar in AR2EN:
        return AR2EN[name_ar]
    return name_ar  # fallback (قد يكون أصلاً إنكليزي في بعض مصادر يلا)

# ==== parsing لمباراة من title ====
def parse_title_to_teams_generic(title: str) -> tuple[str | None, str | None]:
    if not title:
        return None, None
    t = title.strip()
    DELIMS = [
        r"\s+v(?:s)?\.?\s+",
        r"\s+-\s+", r"\s+–\s+", r"\s+—\s+",
        r"\s*:\s*", r"\s*\|\s*", r"\s*·\s*", r"\s*;\s*",
    ]
    for d in DELIMS:
        parts = re.split(d, t, maxsplit=1)
        if len(parts) == 2:
            l, r = parts[0].strip(), parts[1].strip()
            if l and r:
                return l, r
    return None, None

# ==== استخراج فرق liveonsat ====
def extract_live_match(m: dict) -> tuple[str | None, str | None]:
    home = (m.get("home") or m.get("home_team"))
    away = (m.get("away") or m.get("away_team"))
    if home and away:
        return str(home).strip(), str(away).strip()
    title = (m.get("title") or "").strip()
    return parse_title_to_teams_generic(title)

# ==== بناء فهرس liveonsat بالقنوات المسموحة فقط (بدون beIN) ====
def build_live_index(live_data: dict):
    idx = []
    matches = (live_data or {}).get("matches", []) or []
    for m in matches:
        h_en, a_en = extract_live_match(m)
        if not h_en or not a_en:
            continue

        # قنوات مسموحة فقط، مع تجاهل beIN
        raw_channels = []
        for ck in ("channels_raw", "channels", "tv_channels", "broadcasters", "broadcaster"):
            if ck in m and m[ck]:
                raw = m[ck]
                if isinstance(raw, list):
                    raw_channels.extend([str(x) for x in raw])
                elif isinstance(raw, str):
                    raw_channels.extend(to_list_channels(raw))

        filtered = []
        for ch in raw_channels:
            disp = clean_channel_display(ch)
            if not disp:
                continue
            if is_bein_channel(disp):
                continue  # لا نأخذ beIN من live
            if is_supported_channel(disp):
                filtered.append(disp)

        filtered = dedupe_channels_preserve_order(filtered)

        # خزّن عنصر فهرس (نستعمل قائمة بدل dict لنستطيع عمل مطابقة تقريبية)
        idx.append({
            "home_en": h_en,
            "away_en": a_en,
            "home_en_norm": normalize_text(h_en),
            "away_en_norm": normalize_text(a_en),
            "title": (m.get("title") or "").strip(),
            "title_norm": normalize_text(m.get("title") or ""),
            "competition": (m.get("competition") or "").strip(),
            "kickoff_baghdad": (m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff") or "").strip(),
            "channels_allowed": filtered,   # فقط المسموحة
        })
    return idx

def minutes_from_hhmm(hhmm: str) -> int | None:
    m = TIME_RE.match((hhmm or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return h * 60 + mi

def times_close(t1: str, t2: str, tol_min: int = 30) -> bool:
    m1 = minutes_from_hhmm(t1)
    m2 = minutes_from_hhmm(t2)
    if m1 is None or m2 is None:
        return True  # إذا ماكو وقتين معتبرين، لا نمنع المطابقة
    return abs(m1 - m2) <= tol_min

# ==== مطابقة تقريبية بين yalla (AR/EN) و live (EN) ====
def likely_same_match(y_item: dict, live_item: dict) -> bool:
    # مصادر أسماء من يلا: home/away بالعربي، ومحاولة تحويلها لإنكليزي، وكذلك العناوين
    h_ar = (y_item.get("home") or y_item.get("home_team") or "").strip()
    a_ar = (y_item.get("away") or y_item.get("away_team") or "").strip()
    h_en_guess = (y_item.get("home_en") or ar_to_en_guess(h_ar)).strip()
    a_en_guess = (y_item.get("away_en") or ar_to_en_guess(a_ar)).strip()

    # عناوين
    titles_try = [
        (y_item.get("title_en") or "").strip(),
        (y_item.get("title") or "").strip(),
        (y_item.get("title_ar") or "").strip(),
    ]
    title_pairs = []
    for t in titles_try:
        l, r = parse_title_to_teams_generic(t)
        if l and r:
            title_pairs.append((l.strip(), r.strip()))

    # نبني مرشّحات نصية مطبّعة (partial substring) لكلا الفريقين
    cand_pairs = []
    if h_en_guess and a_en_guess:
        cand_pairs.append((h_en_guess, a_en_guess))
    cand_pairs.extend(title_pairs)

    if not cand_pairs:
        # ماكو أسماء EN كافية: ما نقدر نضمن المطابقة
        return False

    lh, la = live_item["home_en_norm"], live_item["away_en_norm"]
    for (ph, pa) in cand_pairs:
        nh, na = normalize_text(ph), normalize_text(pa)
        # تحمّل الترتيبين، وبمطابقة جزئية بالاتجاهين
        cond1 = (nh in lh or lh in nh) and (na in la or la in na)
        cond2 = (nh in la or la in nh) and (na in lh or lh in na)
        if cond1 or cond2:
            # تحقق وقت قريب (إن أمكن)
            if times_close(y_item.get("kickoff_baghdad") or y_item.get("time_baghdad") or y_item.get("kickoff") or "",
                           live_item.get("kickoff_baghdad") or ""):
                return True
    return False

# ==== قنوات يلا شوت ====
def collect_yalla_channels(y: dict) -> list:
    keys_try = ["channels_raw", "channels", "tv_channels", "channel", "channel_ar", "channel_en", "broadcasters", "broadcaster"]
    out = []
    for k in keys_try:
        if k in y:
            out.extend(to_list_channels(y.get(k)))
    return unique_preserving(out)

def pick_primary_yalla_channel(chs: list[str]) -> str | None:
    """Starzplay أولاً، بعدها beIN، بعدها أول قناة."""
    if not chs:
        return None
    cleaned = [clean_channel_display(c) for c in chs if c]
    for c in cleaned:
        if "starzplay" in c.lower():
            return c
    for c in cleaned:
        if is_bein_channel(c):
            return c
    return cleaned[0] if cleaned else None

# ==== الرئيسي ====
def filter_matches():
    # 1) اقرأ يلا شوت (مصدر أساسي)
    try:
        yresp = requests.get(YALLASHOOT_URL, timeout=25)
        yresp.raise_for_status()
        yalla = yresp.json()
    except Exception as e:
        print(f"[x] ERROR fetching yallashoot: {e}")
        return

    y_matches = (yalla or {}).get("matches", []) or []

    # 2) اقرأ liveonsat لالتقاط القنوات الإضافية (المسموحة فقط)
    try:
        with INPUT_PATH_LIVE.open("r", encoding="utf-8") as f:
            live_data = json.load(f)
    except Exception as e:
        print(f"[!] WARN: cannot read liveonsat file: {e}")
        live_data = {"matches": []}

    live_idx = build_live_index(live_data)

    # 3) دمج: لكل مباراة من يلا شوت، نبحث عن المطابقة بالـ live لنفس المباراة
    out_matches = []
    matched_extra = 0
    for m in y_matches:
        # قناة يلا الأساسية
        y_chs = collect_yalla_channels(m)
        primary = pick_primary_yalla_channel(y_chs)
        merged = []
        if primary:
            merged.append(clean_channel_display(primary))

        # ابحث عن live match مطابق
        best_live = None
        for li in live_idx:
            if likely_same_match(m, li):
                best_live = li
                break

        # لو لقينا live مطابق، أضف القنوات المسموحة فقط (موجودة داخل li["channels_allowed"])
        if best_live and best_live["channels_allowed"]:
            merged.extend(best_live["channels_allowed"])
            matched_extra += 1

        # dedupe + ترتيب نهائي
        merged = dedupe_channels_preserve_order(merged)

        out = {
            "competition": m.get("competition") or "",
            "kickoff_baghdad": m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff") or "",
            "home_team": (m.get("home") or m.get("home_team") or "").strip(),
            "away_team": (m.get("away") or m.get("away_team") or "").strip(),
            "channels_raw": merged,
            "home_logo": m.get("home_logo"),
            "away_logo": m.get("away_logo"),
            "status_text": m.get("status_text"),
            "result_text": m.get("result_text"),
        }
        out_matches.append(out)

    # 4) كتابة الناتج
    output = {
        "date": yalla.get("date"),
        "source_url": "yallashoot (primary) + liveonsat (extra whitelisted channels)",
        "matches": out_matches
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[✓] Done. yalla: {len(y_matches)} | matched extra channels from live: {matched_extra} | written: {len(out_matches)}")

if __name__ == "__main__":
    filter_matches()

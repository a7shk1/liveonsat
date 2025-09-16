# scripts/filter_json.py
# -*- coding: utf-8 -*-
import json
import re
import unicodedata
from pathlib import Path
import requests

# ==== المسارات/الإعدادات (نفسها) ====
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"        # المصدر الأساسي
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"
YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"

# ==== أدوات مساعدة عامة ====
EMOJI_MISC_RE = re.compile(r'[\u2600-\u27BF\U0001F300-\U0001FAFF]+')
BEIN_RE = re.compile(r'bein\s*sports?', re.I)

def strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

def normalize_text(text: str) -> str:
    """تطبيع قوي للاستخدام بالمفاتيح/المطابقة."""
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

# ==== القنوات المسموحة (whitelist) ====
SUPPORTED_CHANNELS = [
    "MATCH! Futbol 1", "MATCH! Futbol 2", "MATCH! Futbol 3",
    "Football HD",
    "Sport TV1 Portugal HD", "Sport TV2 Portugal HD",
    "ESPN 1 Brazil", "ESPN 2 Brazil", "ESPN 3 Brazil", "ESPN 4 Brazil", "ESPN 5 Brazil", "ESPN 6 Brazil", "ESPN 7 Brazil",
    "DAZN 1 Portugal HD", "DAZN 2 Portugal HD", "DAZN 3 Portugal HD", "DAZN 4 Portugal HD", "DAZN 5 Portugal HD", "DAZN 6 Portugal HD",
    "MATCH! Premier HD", "Sky Sports Main Event HD", "Sky Sport Premier League HD", "IRIB Varzesh HD",
    "Persiana Sport HD", "MBC Action HD", "TNT Sports 1 HD", "TNT Sports 2 HD", "TNT Sports HD",
    "MBC masrHD", "MBC masr2HD", "ssc1 hd", "ssc2 hd", "Shahid MBC",
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

# ==== توحيد أسماء القنوات ====
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

def extract_bein_mena_display(name: str) -> str | None:
    if not name:
        return None
    disp = clean_channel_display(name)
    low = disp.lower()
    if not is_bein_channel(disp):
        return None
    if not re.search(r'\bmena\b|\bmiddle\s*east\b', low):
        return None
    mnum = re.search(r'\b(\d+)\b', disp)
    if not mnum:
        return None
    n = mnum.group(1)
    return f"beIN Sports MENA {n} HD"

# ==== قاموس EN→AR مختصر ====
EN2AR = {
    "Al Ahli": "الأهلي السعودي", "Al-Ittihad": "الاتحاد", "Al Ittihad": "الاتحاد",
    "Al Hilal": "الهلال", "Al Nassr": "النصر", "Al Sadd": "السد", "Al Duhail": "الدحيل",
    "Al Gharafa": "الغرافة", "Al Rayyan": "الريان", "Sharjah": "الشارقة", "Al Wahda": "الوحدة",
    "Al Shorta": "الشرطة", "Al Zawraa": "الزوراء", "Al Quwa Al Jawiya": "القوة الجوية",
    "Nasaf Qarshi": "ناساف كارشي",
    "Ittihad Tanger": "اتحاد طنجة", "Olympic Safi": "أولمبيك آسفي", "OC Safi": "أولمبيك آسفي",
    "Como": "كومو", "Genoa": "جنوى", "Espanyol": "إسبانيول",
    "Real Mallorca": "ريال مايوركا", "Mallorca": "ريال مايوركا",
}
AR2EN = {v: k for k, v in EN2AR.items()}

def en_to_ar(name: str) -> str:
    return EN2AR.get(name, name or "")

def ar_to_en(name: str) -> str:
    return AR2EN.get(name, name or "")

# ==== parsing ====
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

def extract_live_match(m: dict) -> tuple[str | None, str | None]:
    home = (m.get("home") or m.get("home_team"))
    away = (m.get("away") or m.get("away_team"))
    if home and away:
        return str(home).strip(), str(away).strip()
    title = (m.get("title") or "").strip()
    return parse_title_to_teams_generic(title)

# ==== liveonsat entries ====
def build_live_entries(live_data: dict):
    out = []
    matches = (live_data or {}).get("matches", []) or []
    for m in matches:
        h_en, a_en = extract_live_match(m)
        if not h_en or not a_en:
            continue

        raw_channels = []
        for ck in ("channels_raw", "channels", "tv_channels", "broadcasters", "broadcaster"):
            if ck in m and m[ck]:
                raw = m[ck]
                if isinstance(raw, list):
                    raw_channels.extend([str(x) for x in raw])
                elif isinstance(raw, str):
                    raw_channels.extend(to_list_channels(raw))

        filtered = []
        bein_mena_candidates = []

        for ch in raw_channels:
            ch_disp = clean_channel_display(ch)
            if not ch_disp:
                continue
            if is_bein_channel(ch_disp):
                bein_m = extract_bein_mena_display(ch_disp)
                if bein_m and bein_m not in bein_mena_candidates:
                    bein_mena_candidates.append(bein_m)
                continue
            if is_supported_channel(ch_disp):
                filtered.append(ch_disp)

        filtered = dedupe_channels_preserve_order(filtered)

        entry = {
            "competition": m.get("competition") or "",
            "kickoff_baghdad": m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff") or "",
            "home_en": h_en.strip(),
            "away_en": a_en.strip(),
            "home_ar_guess": en_to_ar(h_en.strip()),
            "away_ar_guess": en_to_ar(a_en.strip()),
            "title_src": (m.get("title") or "").strip(),   # <<< نخزّن العنوان الأصلي
            "channels": filtered,
            "bein_mena": bein_mena_candidates,
        }
        out.append(entry)
    return out

# ==== يلا شوت index ====
def collect_yalla_channels(y: dict) -> list:
    keys_try = ["channels_raw", "channels", "tv_channels", "channel", "channel_ar", "channel_en", "broadcasters", "broadcaster"]
    out = []
    for k in keys_try:
        if k in y:
            out.extend(to_list_channels(y.get(k)))
    return unique_preserving(out)

def pick_primary_yalla_channel(chs: list[str]) -> str | None:
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

def _add_key_pair(idx: dict, key_left: str, key_right: str, record: dict):
    """يسجل المفتاحين (ترتيبين) لو في بيانات كفاية."""
    if key_left and key_right:
        k1 = f"{normalize_text(key_left)}-{normalize_text(key_right)}"
        k2 = f"{normalize_text(key_right)}-{normalize_text(key_left)}"
        if k1 not in idx:
            idx[k1] = record
        if k2 not in idx:
            idx[k2] = record

def build_yalla_index(yalla_data: dict):
    idx = {}
    matches = (yalla_data or {}).get("matches", []) or []
    for m in matches:
        # نجمع كل مصادر الأسماء الممكنة من يلا شوت
        contenders = []

        # 1) حقول فرق صريحة (AR/EN) إن وجدت
        home_ar = (m.get("home") or m.get("home_team") or "").strip()
        away_ar = (m.get("away") or m.get("away_team") or "").strip()
        if home_ar and away_ar:
            contenders.append((home_ar, away_ar))

        home_en = (m.get("home_en") or ar_to_en(home_ar) or "").strip()
        away_en = (m.get("away_en") or ar_to_en(away_ar) or "").strip()
        if home_en and away_en:
            contenders.append((home_en, away_en))

        # 2) العنوان (title / title_en / title_ar) إن وجد — نفكّه لِفريقين
        for tk in ("title_en", "title_ar", "title"):
            t = (m.get(tk) or "").strip()
            if t:
                l, r = parse_title_to_teams_generic(t)
                if l and r:
                    contenders.append((l, r))

        # قناة أساسية
        y_chs = collect_yalla_channels(m)
        primary = pick_primary_yalla_channel(y_chs)
        pk, pd = channel_key_and_display(primary) if primary else (None, None)

        record = {"match": m, "primary_key": pk, "primary_disp": pd}

        # سجل كل المفاتيح المحتملة (بكل الترتيبين)
        for (l, r) in contenders:
            _add_key_pair(idx, l, r, record)

    return idx

# ==== المطابقة ====
def match_live_to_yalla(live_entry: dict, y_idx: dict) -> dict | None:
    # 1) مطابقة بالعربي المتوقع من EN2AR (إن توفّر)
    h_ar = live_entry["home_ar_guess"]
    a_ar = live_entry["away_ar_guess"]
    if h_ar and a_ar:
        k1 = f"{normalize_text(h_ar)}-{normalize_text(a_ar)}"
        k2 = f"{normalize_text(a_ar)}-{normalize_text(h_ar)}"
        if k1 in y_idx: return y_idx[k1]
        if k2 in y_idx: return y_idx[k2]

    # 2) مطابقة بالإنجليزي من live
    h_en = live_entry["home_en"]; a_en = live_entry["away_en"]
    k3 = f"{normalize_text(h_en)}-{normalize_text(a_en)}"
    k4 = f"{normalize_text(a_en)}-{normalize_text(h_en)}"
    if k3 in y_idx: return y_idx[k3]
    if k4 in y_idx: return y_idx[k4]

    # 3) مطابقة عبر عنوان live نفسه (لو يلا عنده title مناظر)
    title_src = (live_entry.get("title_src") or "").strip()
    if title_src:
        tl, tr = parse_title_to_teams_generic(title_src)
        if tl and tr:
            k5 = f"{normalize_text(tl)}-{normalize_text(tr)}"
            k6 = f"{normalize_text(tr)}-{normalize_text(tl)}"
            if k5 in y_idx: return y_idx[k5]
            if k6 in y_idx: return y_idx[k6]

    return None

# ==== الرئيسي ====
def filter_matches():
    # 0) اقرأ liveonsat
    try:
        with INPUT_PATH.open("r", encoding="utf-8") as f:
            live_data = json.load(f)
    except Exception as e:
        print(f"[x] ERROR reading liveonsat: {e}")
        return

    live_entries = build_live_entries(live_data)

    # 1) حمّل يلا شوت
    try:
        yresp = requests.get(YALLASHOOT_URL, timeout=25)
        yresp.raise_for_status()
        yalla = yresp.json()
    except Exception as e:
        print(f"[x] ERROR fetching yallashoot: {e}")
        yalla = {"matches": []}

    y_idx = build_yalla_index(yalla)

    # 2) تقاطع + دمج
    out_matches = []
    matched_cnt = 0
    for le in live_entries:
        m_y = match_live_to_yalla(le, y_idx)
        if not m_y:
            continue
        matched_cnt += 1

        y_match = m_y["match"]
        primary_disp = m_y.get("primary_disp")  # قد تكون Starzplay أو beIN أو غيرها

        # ✅ تحسين beIN: لو primary من يلا هي beIN عامة، ولدينا من live نسخة MENA مرقّمة نفضلها
        if primary_disp and is_bein_channel(primary_disp):
            if le.get("bein_mena"):
                primary_disp = le["bein_mena"][0]

        merged = []
        if primary_disp and "starzplay" in primary_disp.lower():
            merged.append(primary_disp)
        else:
            if primary_disp and is_bein_channel(primary_disp):
                merged.append(primary_disp)
            else:
                if le.get("bein_mena"):
                    merged.append(le["bein_mena"][0])

        merged.extend(le["channels"])
        merged = dedupe_channels_preserve_order(merged)

        out = {
            "competition": y_match.get("competition") or le["competition"],
            "kickoff_baghdad": y_match.get("kickoff_baghdad") or le["kickoff_baghdad"],
            "home_team": en_to_ar(le["home_en"]) if en_to_ar(le["home_en"]) else le["home_en"],
            "away_team": en_to_ar(le["away_en"]) if en_to_ar(le["away_en"]) else le["away_en"],
            "channels_raw": merged,
            "home_logo": y_match.get("home_logo"),
            "away_logo": y_match.get("away_logo"),
            "status_text": y_match.get("status_text"),
            "result_text": y_match.get("result_text"),
        }
        out_matches.append(out)

    # 3) كتابة المخرجات
    output = {
        "date": live_data.get("date") or yalla.get("date"),
        "source_url": live_data.get("source_url") or "liveonsat + yallashoot",
        "matches": out_matches
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[✓] Done. live entries: {len(live_entries)} | matched with yalla: {matched_cnt} | written: {len(out_matches)}")

if __name__ == "__main__":
    filter_matches()

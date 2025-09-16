# scripts/filter_json.py
# -*- coding: utf-8 -*-
import json
import re
import unicodedata
from pathlib import Path
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"

# مصادر
YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"
LIVE_PATH = MATCHES_DIR / "liveonsat_raw.json"

# ===== Utils =====
EMOJI_MISC_RE = re.compile(r'[\u2600-\u27BF\U0001F300-\U0001FAFF]+')
BEIN_RE = re.compile(r'bein\s*sports?', re.I)

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

# ===== Whitelist (كما هي من كلامك) =====
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

# ===== Canon rules =====
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

# قاموس AR→EN صغير (يكفي لريال/مارسيليا وغيرها الشائعة)
AR2EN = {
    "ريال مدريد": "Real Madrid",
    "مارسيليا": "Marseille",
    "برشلونة": "Barcelona",
    "بايرن ميونخ": "Bayern Munich",
    "ميلان": "AC Milan",
    "انتر": "Inter",
    "يوفنتوس": "Juventus",
    "روما": "Roma",
    "ليفربول": "Liverpool",
    "ارسنال": "Arsenal",
    "اتلتيكو مدريد": "Atletico Madrid",
    "باريس سان جيرمان": "Paris Saint-Germain",
}
def ar_to_en_guess(s: str) -> str:
    s = (s or "").strip()
    return AR2EN.get(s, s)

def parse_title_to_teams_generic(title: str):
    if not title:
        return None, None
    t = title.strip()
    DELIMS = [r"\s+v(?:s)?\.?\s+", r"\s+-\s+", r"\s+–\s+", r"\s+—\s+", r"\s*:\s*", r"\s*\|\s*", r"\s*·\s*", r"\s*;\s*"]
    for d in DELIMS:
        parts = re.split(d, t, maxsplit=1)
        if len(parts) == 2:
            l, r = parts[0].strip(), parts[1].strip()
            if l and r:
                return l, r
    return None, None

# ===== بناء فهرس liveonsat (EN) مع القنوات “المسموحة فقط” =====
def build_live_index(live_data: dict):
    idx = []
    matches = (live_data or {}).get("matches", []) or []
    for m in matches:
        # فرق إنكليزي
        home = (m.get("home") or m.get("home_team"))
        away = (m.get("away") or m.get("away_team"))
        if not (home and away):
            tl, tr = parse_title_to_teams_generic(m.get("title") or "")
            home, away = tl, tr
        if not (home and away):
            continue

        # قنوات مسموحة فقط + بدون beIN من live
        raw_channels = []
        for ck in ("channels_raw", "channels", "tv_channels", "broadcasters", "broadcaster"):
            if ck in m and m[ck]:
                raw = m[ck]
                if isinstance(raw, list):
                    raw_channels.extend([str(x) for x in raw])
                elif isinstance(raw, str):
                    raw_channels.extend(to_list_channels(raw))

        allowed = []
        for ch in raw_channels:
            disp = clean_channel_display(ch)
            if not disp or is_bein_channel(disp):
                continue
            if is_supported_channel(disp):
                allowed.append(disp)

        allowed = dedupe_channels_preserve_order(allowed)

        idx.append({
            "home_en": home.strip(),
            "away_en": away.strip(),
            "home_norm": normalize_text(home),
            "away_norm": normalize_text(away),
            "title": (m.get("title") or "").strip(),
            "title_norm": normalize_text(m.get("title") or ""),
            "kickoff_baghdad": (m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff") or "").strip(),
            "channels_allowed": allowed,
        })
    return idx

# ===== مطابقة تقريبية (جزئية) Yalla ↔ Live =====
def likely_same_match(y: dict, li: dict) -> bool:
    # نحاول تكوين زوج أسماء EN من بيانات يلا
    h_ar = (y.get("home") or y.get("home_team") or "").strip()
    a_ar = (y.get("away") or y.get("away_team") or "").strip()
    h_en = (y.get("home_en") or ar_to_en_guess(h_ar)).strip()
    a_en = (y.get("away_en") or ar_to_en_guess(a_ar)).strip()

    pairs = []
    if h_en and a_en:
        pairs.append((h_en, a_en))

    for tk in ("title_en", "title", "title_ar"):
        t = (y.get(tk) or "").strip()
        l, r = parse_title_to_teams_generic(t)
        if l and r:
            pairs.append((l, r))

    if not pairs:
        return False

    Lh, La = li["home_norm"], li["away_norm"]
    for (ph, pa) in pairs:
        nh, na = normalize_text(ph), normalize_text(pa)
        # مطابقة جزئية في الاتجاهين + تحمّل تبديل الملعب
        cond1 = (nh in Lh or Lh in nh) and (na in La or La in na)
        cond2 = (nh in La or La in nh) and (na in Lh or Lh in na)
        if cond1 or cond2:
            return True
    return False

def collect_yalla_channels(y: dict) -> list:
    keys_try = ["channels_raw", "channels", "tv_channels", "channel", "channel_ar", "channel_en", "broadcasters", "b]()_

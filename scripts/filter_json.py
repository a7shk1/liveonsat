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
BEIN_RE = re.compile(r'bein\s*sports?', re.I)
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
TIME_RE_12 = re.compile(r'^\s*(\d{1,2}):(\d{2})\s*([AP]M)\s*$', re.I)
TIME_RE_24 = re.compile(r'^\s*(\d{1,2}):(\d{2})\s*$')

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

# ========= القنوات المسموحة (كما هي) =========
SUPPORTED_CHANNELS = [
    "MATCH! Futbol 1", "MATCH! Futbol 2", "MATCH! Futbol 3",
    "Football HD",
    "Sport TV1 Portugal HD", "Sport TV2 Portugal HD",
    "ESPN 1 Brazil", "ESPN 2 Brazil", "ESPN 3 Brazil", "ESPN 4 Brazil", "ESPN 5 Brazil", "ESPN 6 Brazil", "ESPN 7 Brazil",
    "DAZN 1 Portugal HD", "DAZN 2 Portugal HD", "DAZN 3 Portugal HD", "DAZN 4 Portugal HD", "DAZN 5 Portugal HD", "DAZN 6 Portugal HD",
    "MATCH! Premier HD", "Sky Sports Main Event HD", "Sky Sport Premier League HD",
    "IRIB Varzesh HD", "Persiana Sport HD",
    "MBC Action HD",
    "TNT Sports 1 HD", "TNT Sports 2 HD", "TNT Sports HD",
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
_allowed_tokens = set()
for c in SUPPORTED_CHANNELS:
    cl = c.lower()
    _allowed_tokens.add(cl)
    _allowed_tokens.add(cl.replace(" hd", ""))

def is_supported_channel(name: str) -> bool:
    if not name:
        return False
    n = name.lower()
    if any(tok in n for tok in _allowed_tokens):
        return True
    if any(sub in n for sub in ALLOWED_SUBSTRINGS):
        return True
    return False

# ========= توحيد أسماء القنوات =========
CHANNEL_CANON_RULES = [
    (re.compile(r"thmanyah\s*(\d+)", re.I), lambda m: (f"thmanyah-{m.group(1)}", f"Thmanyah {m.group(1)}")),
    (re.compile(r"starzplay\s*(\d+)", re.I), lambda m: (f"starzplay-{m.group(1)}", f"Starzplay {m.group(1)}")),
    (re.compile(r"starzplay\b", re.I),      lambda m: ("starzplay-1", "Starzplay 1")),
    (re.compile(r"abu\s*dhabi\s*sport\s*(\d+)", re.I), lambda m: (f"abudhabi-{m.group(1)}", f"Abu Dhabi Sport {m.group(1)}")),
    (re.compile(r"(al[\s-]?kass|الكاس|الكأس)\s*(?:channel\s*)?(\d+)", re.I),
     lambda m: (f"alkass-{m.group(2)}", "Alkass %s HD" % m.group(2))),
    (re.compile(r"ssc\s*extra", re.I),     lambda m: ("ssc-extra", "SSC Extra HD")),
    (re.compile(r"ssc\s*(\d+)", re.I),     lambda m: (f"ssc-{m.group(1)}", f"SSC {m.group(1)} HD")),
    (re.compile(r"shahid\s*(vip)?", re.I),lambda m: ("shahid", "Shahid MBC")),
    (re.compile(r"football\s*hd", re.I),  lambda m: ("football-hd", "Football HD")),
    (re.compile(r"sky\s*sport[s]?\s*premier\s*league", re.I),
                                         lambda m: ("sky-premier-league", "Sky Sport Premier League HD")),
    (re.compile(r"sky\s*sport[s]?\s*main\s*event", re.I),
                                         lambda m: ("sky-main-event", "Sky Sports Main Event HD")),
    (re.compile(r"dazn\s*1\s*portugal", re.I), lambda m: ("dazn-pt-1", "DAZN 1 Portugal HD")),
    (re.compile(r"dazn\s*2\s*portugal", re.I), lambda m: ("dazn-pt-2", "DAZN 2 Portugal HD")),
    (re.compile(r"dazn\s*3\s*portugal", re.I), lambda m: ("dazn-pt-3", "DAZN 3 Portugal HD")),
    (re.compile(r"mbc\s*action", re.I),       lambda m: ("mbc-action", "MBC Action HD")),
    (re.compile(r"persiana\s*sport", re.I),   lambda m: ("persiana-sport", "Persiana Sport HD")),
    (re.compile(r"irib\s*varzesh", re.I),     lambda m: ("irib-varzesh", "IRIB Varzesh HD")),
    (re.compile(r"tnt\s*sports?\s*1", re.I),  lambda m: ("tnt-1", "TNT Sports 1 HD")),
    (re.compile(r"tnt\s*sports?\s*2", re.I),  lambda m: ("tnt-2", "TNT Sports 2 HD")),
]

def channel_key_and_display(raw_name: str) -> tuple[str, str]:
    disp = clean_channel_display(raw_name)
    low = disp.lower()
    if is_bein_channel(disp):
        has_mena = bool(re.search(r'\bmena\b|\bmiddle\s*east\b', low))
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
    
# ========= بناء فهرس liveonsat (الجديد) =========
def build_live_match_index(live_data: dict):
    idx = []
    matches = (live_data or {}).get("matches", []) or []
    for m in matches:
        t = (m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff") or "").strip()
        tmin = kickoff_to_minutes(t)
        if tmin is None:
            continue

        home_team = (m.get("home") or m.get("home_team") or "")
        away_team = (m.get("away") or m.get("away_team") or "")
        if not home_team or not away_team:
            continue

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
        if not allowed:
            continue

        idx.append({
            "tmin": tmin,
            "home_norm": normalize_text(home_team),
            "away_norm": normalize_text(away_team),
            "allowed": allowed,
        })
    return idx

# ========= قنوات يلا (مبسط) =========
def get_yalla_channels(y: dict) -> list[str]:
    keys = ["channels_raw","channels","tv_channels","channel","channel_ar","channel_en","broadcasters","broadcaster"]
    out = []
    for k in keys:
        if k in y and y[k]:
            out.extend(to_list_channels(y[k]))
    return [clean_channel_display(c) for c in unique_preserving(out) if c]

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
    live_idx = build_live_match_index(live_data)
    print(f"[i] Live match-index built: {len(live_idx)}")

    # 3) دمج ذكي
    out_matches = []
    added_from_live_count = 0
    used_live_indices = set()

    for y_match in y_matches:
        y_time_str = (y_match.get("kickoff_baghdad") or y_match.get("time_baghdad") or y_match.get("kickoff") or "").strip()
        y_tmin = kickoff_to_minutes(y_time_str)
        
        y_home_norm = normalize_text(y_match.get("home") or y_match.get("home_team"))
        y_away_norm = normalize_text(y_match.get("away") or y_match.get("away_team"))
        
        merged_channels = get_yalla_channels(y_match)
        
        found_match = False
        if y_tmin is not None and y_home_norm and y_away_norm:
            # ابحث عن أفضل تطابق
            for i, li in enumerate(live_idx):
                if i in used_live_indices:
                    continue
                
                if minutes_close(y_tmin, li["tmin"]):
                    # تحقق من تطابق أسماء الفرق (بالاتجاهين)
                    cond1 = (y_home_norm in li["home_norm"] or li["home_norm"] in y_home_norm) and \
                            (y_away_norm in li["away_norm"] or li["away_norm"] in y_away_norm)
                    cond2 = (y_home_norm in li["away_norm"] or li["away_norm"] in y_home_norm) and \
                            (y_away_norm in li["home_norm"] or li["home_norm"] in y_away_norm)
                    
                    if cond1 or cond2:
                        merged_channels.extend(li["allowed"])
                        used_live_indices.add(i) # نستخدم المباراة مرة واحدة فقط
                        added_from_live_count += 1
                        found_match = True
                        break # نكتفي بأول تطابق دقيق

        out_matches.append({
            "competition": y_match.get("competition") or "",
            "kickoff_baghdad": y_time_str,
            "home_team": (y_match.get("home") or y_match.get("home_team") or "").strip(),
            "away_team": (y_match.get("away") or y_match.get("away_team") or "").strip(),
            "channels_raw": dedupe_channels_preserve_order(merged_channels),
            "home_logo": y_match.get("home_logo"),
            "away_logo": y_match.get("away_logo"),
            "status_text": y_match.get("status_text"),
            "result_text": y_match.get("result_text"),
        })

    output = {
        "date": (yalla or {}).get("date"),
        "source_url": "yallashoot (primary) + liveonsat (extra-by-match, whitelisted)",
        "matches": out_matches
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[✓] Done. yalla: {len(y_matches)} | with-live-added: {added_from_live_count} | written: {len(out_matches)}")

if __name__ == "__main__":
    filter_matches()

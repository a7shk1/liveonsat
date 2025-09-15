# scripts/filter_json.py
import json
import re
import unicodedata
from pathlib import Path
import requests

# --- الإعدادات ---
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"        # نكمل منه القنوات
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"
YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"

# --- الأدوات ---
AR_LETTERS_RE = re.compile(r'[\u0600-\u06FF]')
EMOJI_MISC_RE = re.compile(r'[\u2600-\u27BF\U0001F300-\U0001FAFF]+')
BEIN_RE = re.compile(r'bein\s*sports?', re.I)

def strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = str(text)
    text = EMOJI_MISC_RE.sub("", text)
    text = re.sub(r"\(.*?\)", "", text)
    text = strip_accents(text)
    text = text.lower()
    text = text.replace("&", "and")
    text = re.sub(r"\bfc\b|\bsc\b|\bcf\b", "", text)
    text = text.replace(" ", "").replace("-", "").replace("_", "")
    text = text.replace("ال", "")
    text = re.sub(r"[^a-z0-9\u0600-\u06FF]", "", text)
    return text.strip()

def unique_preserving(seq):
    seen, out = set(), []
    for x in seq:
        k = str(x).lower().strip()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out

def is_bein_channel(name: str) -> bool:
    return bool(BEIN_RE.search(name or ""))

# --- القنوات المدعومة في التطبيق ---
SUPPORTED_CHANNELS = [
    "MATCH! Futbol 1", "MATCH! Futbol 2", "MATCH! Futbol 3",
    "Football HD",
    "Sport TV1 Portugal HD", "Sport TV2 Portugal HD",
    "ESPN 1 Brazil", "ESPN 2 Brazil", "ESPN 3 Brazil", "ESPN 4 Brazil", "ESPN 5 Brazil", "ESPN 6 Brazil", "ESPN 7 Brazil",
    "DAZN 1 Portugal HD", "DAZN 2 Portugal HD", "DAZN 3 Portugal HD", "DAZN 4 Portugal HD", "DAZN 5 Portugal HD", "DAZN 6 Portugal HD",
    "MATCH! Premier HD", "Sky Sports Main Event HD", "Sky Sport Premier League HD", "IRIB Varzesh HD",
    "Persiana Sport HD", "MBC Action HD", "TNT Sports 1 HD", "TNT Sports 2 HD", "TNT Sports HD",
    "MBC masrHD", "MBC masr2HD", "ssc1 hd", "ssc2 hd", "Shahid MBC",
]

SUPPORTED_LOWER = [c.lower() for c in SUPPORTED_CHANNELS]

def is_supported_channel(name: str) -> bool:
    if not name:
        return False
    return any(s in name.lower() for s in SUPPORTED_LOWER)

# --- فرق (قاموس مبسط للربط بين عربي/إنجليزي) ---
TEAM_MAP = {
    "Manchester City": "مانشستر سيتي", "Arsenal": "أرسنال",
    "Manchester United": "مانشستر يونايتد", "Liverpool": "ليفربول",
    "Chelsea": "تشيلسي", "Tottenham Hotspur": "توتنهام", "Tottenham": "توتنهام",
    "Real Madrid": "ريال مدريد", "Barcelona": "برشلونة", "Atletico Madrid": "أتلتيكو مدريد",
    "Bayern Munich": "بايرن ميونخ", "Borussia Dortmund": "بوروسيا دورتموند",
    "Paris Saint-Germain": "باريس سان جيرمان", "PSG": "باريس سان جيرمان",
    "Inter Milan": "إنتر ميلان", "Inter": "إنتر ميلان", "AC Milan": "ميلان", "Milan": "ميلان",
    "Juventus": "يوفنتوس", "Napoli": "نابولي", "Roma": "روما",
    "Sporting CP": "سبورتينغ لشبونة", "Benfica": "بنفيكا", "Porto": "بورتو",
}

def translate_team_or_fallback(name_en: str) -> str:
    if name_en in TEAM_MAP:
        return TEAM_MAP[name_en]
    return name_en

def parse_title_to_teams(title: str):
    parts = re.split(r"\s+v(?:s)?\.?\s+", title or "", flags=re.I)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return (title or "").strip(), None

# --- قنوات يلا شوت ---
SPLIT_RE = re.compile(r"\s*(?:,|،|/|\||&| و | and )\s*", re.I)

def to_list_channels(val):
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        if not val.strip():
            return []
        return [p.strip() for p in SPLIT_RE.split(val) if p.strip()]
    return []

def collect_yalla_channels(yalla_match: dict) -> list:
    keys_try = [
        "channels_raw", "channels", "tv_channels",
        "channel", "channel_ar", "channel_en",
        "broadcasters", "broadcaster",
    ]
    out = []
    for k in keys_try:
        if k in yalla_match:
            out.extend(to_list_channels(yalla_match.get(k)))
    return unique_preserving(out)

def pick_primary_yalla_channel(chs: list[str]) -> str | None:
    if not chs:
        return None
    for c in chs:
        if is_bein_channel(c):
            return c.strip()
    return chs[0].strip()

# --- نبني فهرس liveonsat بالقنوات المدعومة فقط ---
def build_liveonsat_index(live_data: dict) -> dict:
    index = {}
    matches = (live_data or {}).get("matches", []) or []
    for m in matches:
        title = (m.get("title") or "").strip()
        home_en, away_en = parse_title_to_teams(title)
        if not home_en or not away_en:
            continue
        home_ar = translate_team_or_fallback(home_en)
        away_ar = translate_team_or_fallback(away_en)
        key = f"{normalize_text(home_ar)}-{normalize_text(away_ar)}"

        raw_channels = m.get("channels_raw") or m.get("channels") or []
        if isinstance(raw_channels, str):
            raw_channels = to_list_channels(raw_channels)

        cleaned = []
        for ch in raw_channels:
            if not ch:
                continue
            if is_bein_channel(ch):
                continue
            if is_supported_channel(ch):
                cleaned.append(re.sub(r"\s+", " ", str(ch)).strip())
        if cleaned:
            index[key] = unique_preserving(cleaned)
    return index

# --- الرئيسي ---
def filter_matches():
    # يلا شوت
    try:
        yresp = requests.get(YALLASHOOT_URL, timeout=20)
        yresp.raise_for_status()
        yalla = yresp.json()
    except Exception as e:
        print(f"ERROR fetching yallashoot: {e}")
        return

    yalla_matches = (yalla or {}).get("matches", []) or []

    # liveonsat
    try:
        with INPUT_PATH.open("r", encoding="utf-8") as f:
            live_data = json.load(f)
    except Exception as e:
        print(f"WARNING reading liveonsat: {e}")
        live_data = {}

    live_index = build_liveonsat_index(live_data)

    out_matches = []
    for m in yalla_matches:
        home_ar = (m.get("home") or m.get("home_team") or "").strip()
        away_ar = (m.get("away") or m.get("away_team") or "").strip()
        if not home_ar or not away_ar:
            continue

        y_chs = collect_yalla_channels(m)
        primary = pick_primary_yalla_channel(y_chs)
        yalla_only = [primary] if primary else []

        key = f"{normalize_text(home_ar)}-{normalize_text(away_ar)}"
        extra = live_index.get(key, [])

        channels = unique_preserving([*yalla_only, *extra])

        new_entry = {
            "competition": m.get("competition") or m.get("league") or m.get("tournament"),
            "kickoff_baghdad": m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff"),
            "home_team": home_ar,
            "away_team": away_ar,
            "channels_raw": channels,
            "home_logo": m.get("home_logo"),
            "away_logo": m.get("away_logo"),
            "status_text": m.get("status_text"),
            "result_text": m.get("result_text"),
        }
        out_matches.append(new_entry)

    output_data = {
        "date": yalla.get("date"),
        "source_url": YALLASHOOT_URL,
        "matches": out_matches,
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"Done. Wrote {len(out_matches)} matches.")

if __name__ == "__main__":
    filter_matches()

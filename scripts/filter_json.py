# scripts/filter_json.py
import json
import re
import unicodedata
from pathlib import Path
import requests

# محركات ترجمة/مطابقة متقدمة
try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None

# --- الإعدادات ---
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"   # نكمّل منه القنوات
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"
YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"

# عتبة التشابه الضبابي (تقدر تغيّرها من الـ ENV)
import os
FUZZY_THRESHOLD = int(os.getenv("LIVO_FUZZY_THRESHOLD", "88"))

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

def is_arabic(s: str) -> bool:
    return bool(AR_LETTERS_RE.search(s or ""))

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

# --- القنوات المدعومة في التطبيق (فلترة صارمة) ---
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
SUPPORTED_TOKENS = [c.lower() for c in SUPPORTED_CHANNELS]

def is_supported_channel(name: str) -> bool:
    if not name:
        return False
    n = name.lower()
    return any(tok in n for tok in SUPPORTED_TOKENS)

# --- قاموس أساسي سريع (لتقليل الترجمات) ---
TEAM_MAP_EN2AR = {
    # England
    "Manchester City": "مانشستر سيتي", "Arsenal": "أرسنال",
    "Manchester United": "مانشستر يونايتد", "Liverpool": "ليفربول",
    "Chelsea": "تشيلسي", "Tottenham Hotspur": "توتنهام", "Tottenham": "توتنهام",
    "Newcastle United": "نيوكاسل يونايتد", "Aston Villa": "أستون فيلا",
    # Spain
    "Real Madrid": "ريال مدريد", "Barcelona": "برشلونة",
    "Atletico Madrid": "أتلتيكو مدريد", "Athletic Bilbao": "أتلتيك بيلباو",
    "Real Sociedad": "ريال سوسيداد", "Sevilla": "إشبيلية", "Valencia": "فالنسيا",
    # Italy
    "Inter": "إنتر ميلان", "Inter Milan": "إنتر ميلان",
    "AC Milan": "ميلان", "Milan": "ميلان", "Juventus": "يوفنتوس", "Napoli": "نابولي", "Roma": "روما",
    # Germany/France
    "Bayern Munich": "بايرن ميونخ", "Borussia Dortmund": "بوروسيا دورتموند",
    "Paris Saint-Germain": "باريس سان جيرمان", "PSG": "باريس سان جيرمان",
    # Portugal
    "Benfica": "بنفيكا", "Porto": "بورتو", "Sporting CP": "سبورتينغ لشبونة", "Sporting": "سبورتينغ لشبونة",
}

TEAM_MAP_AR2EN = {
    v: k for k, v in TEAM_MAP_EN2AR.items()
}

def translate_en_to_ar(name: str) -> str:
    if not name:
        return ""
    if name in TEAM_MAP_EN2AR:
        return TEAM_MAP_EN2AR[name]
    if GoogleTranslator:
        try:
            # ترجمة آلية (بدون مفاتيح)
            t = GoogleTranslator(source="en", target="ar").translate(name)
            return (t or name).strip()
        except Exception:
            return name
    return name

def translate_ar_to_en(name: str) -> str:
    if not name:
        return ""
    if name in TEAM_MAP_AR2EN:
        return TEAM_MAP_AR2EN[name]
    if GoogleTranslator:
        try:
            t = GoogleTranslator(source="ar", target="en").translate(name)
            return (t or name).strip()
        except Exception:
            return name
    return name

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

# --- فهرس liveonsat بالقنوات المدعومة فقط ---
def build_liveonsat_index(live_data: dict) -> list:
    """
    نرجّع قائمة سجلات: [(home_en, away_en, channels_filtered)]
    حيث channels_filtered = قنوات مدعومة فقط (وبدون beIN)
    """
    out = []
    matches = (live_data or {}).get("matches", []) or []
    for m in matches:
        title = (m.get("title") or "").strip()
        home_en, away_en = parse_title_to_teams(title)
        if not home_en or not away_en:
            continue
        raw_channels = m.get("channels_raw") or m.get("channels") or []
        if isinstance(raw_channels, str):
            raw_channels = to_list_channels(raw_channels)
        filtered = []
        for ch in raw_channels:
            if not ch:
                continue
            if is_bein_channel(ch):
                continue  # نخلي beIN من يلا فقط
            if is_supported_channel(ch):
                filtered.append(re.sub(r"\s+", " ", str(ch)).strip())
        if filtered:
            out.append((home_en, away_en, unique_preserving(filtered)))
    return out

# --- مطابقة متقدّمة بين مباراة يلا (AR) ومباراة لايف أون سات (EN) ---
def match_live_to_yalla(home_ar: str, away_ar: str, lons_list: list) -> list:
    """
    نحاول نلاقي سجلات لايف أون سات لنفس المباراة:
      - نترجم EN->AR ونقارن بالعربي.
      - وإن فشل، نترجم AR->EN ونقارن بالإنجليزي.
      - نستخدم rapidfuzz لو متوفر لتقدير التشابه.
    نرجّع قائمة القنوات المجمّعة من كل التطابقات (بدون تكرار).
    """
    added_channels = []

    # تجهيز أشكال مطبّعة
    hy_ar = normalize_text(home_ar)
    ay_ar = normalize_text(away_ar)

    # ترجمة AR->EN لمقارنة إنجليزية
    home_en_from_ar = translate_ar_to_en(home_ar)
    away_en_from_ar = translate_ar_to_en(away_ar)
    hy_en = normalize_text(home_en_from_ar)
    ay_en = normalize_text(away_en_from_ar)

    def ok_ratio(a: str, b: str) -> int:
        if not a or not b:
            return 0
        if fuzz:
            return fuzz.token_set_ratio(a, b)
        # fallback بسيط بدون rapidfuzz
        return 100 if a == b else 0

    for (h_en, a_en, chans) in lons_list:
        # مساران: EN->AR ثم مقارنة بالعربي
        h_ar_guess = translate_en_to_ar(h_en)
        a_ar_guess = translate_en_to_ar(a_en)
        h_ar_norm = normalize_text(h_ar_guess)
        a_ar_norm = normalize_text(a_ar_guess)

        # قارن عربي-عربي (ترجمة EN->AR)
        r1 = min(ok_ratio(h_ar_norm, hy_ar), ok_ratio(a_ar_norm, ay_ar))
        r2 = min(ok_ratio(h_ar_norm, ay_ar), ok_ratio(a_ar_norm, hy_ar))  # معكوس
        match_ar = max(r1, r2)

        # مسار بديل: قارن إنجليزي-إنجليزي (ترجمة AR->EN)
        h_en_norm = normalize_text(h_en)
        a_en_norm = normalize_text(a_en)
        r3 = min(ok_ratio(h_en_norm, hy_en), ok_ratio(a_en_norm, ay_en))
        r4 = min(ok_ratio(h_en_norm, ay_en), ok_ratio(a_en_norm, hy_en))  # معكوس
        match_en = max(r3, r4)

        best = max(match_ar, match_en)

        if best >= FUZZY_THRESHOLD:
            added_channels.extend(chans)

    return unique_preserving(added_channels)

# --- الرئيسي ---
def filter_matches():
    # 1) يلا شوت
    try:
        yresp = requests.get(YALLASHOOT_URL, timeout=25)
        yresp.raise_for_status()
        yalla = yresp.json()
    except Exception as e:
        print(f"[x] ERROR fetching yallashoot: {e}")
        return

    yalla_matches = (yalla or {}).get("matches", []) or []
    if not yalla_matches:
        print("[!] yallashoot returned 0 matches.")
        output_data = {"date": yalla.get("date"), "source_url": YALLASHOOT_URL, "matches": []}
        with OUTPUT_PATH.open("w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        return

    # 2) liveonsat (محلي)
    try:
        with INPUT_PATH.open("r", encoding="utf-8") as f:
            live_data = json.load(f)
    except Exception as e:
        print(f"[!] WARNING reading liveonsat: {e}")
        live_data = {}

    lons_list = build_liveonsat_index(live_data)

    # 3) دمج
    out_matches = []
    added_cnt = 0
    for m in yalla_matches:
        home_ar = (m.get("home") or m.get("home_team") or "").strip()
        away_ar = (m.get("away") or m.get("away_team") or "").strip()
        if not home_ar or not away_ar:
            continue

        # قناة أساسية من يلا شوت
        y_chs = collect_yalla_channels(m)
        primary = pick_primary_yalla_channel(y_chs)
        yalla_only = [primary] if primary else []

        # قنوات مكملة من liveonsat (مطابقة ذكية)
        extra = match_live_to_yalla(home_ar, away_ar, lons_list)
        if extra:
            added_cnt += 1

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

    print(f"[✓] Done. Wrote {len(out_matches)} matches. Added extra channels for {added_cnt} matches using smart AR↔EN matching (threshold={FUZZY_THRESHOLD}).")
    if GoogleTranslator is None:
        print("[!] deep-translator not available — install it in requirements.txt for best matching.")
    if fuzz is None:
        print("[!] rapidfuzz not available — install it in requirements.txt to enable fuzzy matching.")

if __name__ == "__main__":
    filter_matches()

# scripts/filter_json.py
import json
import re
import unicodedata
from pathlib import Path
import requests

# --- الإعدادات الأساسية (نفسها) ---
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"        # نكمّل منه القنوات فقط
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"
YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"  # المصدر الأساسي لكل المباريات

# --- أدوات مساعدة للتنظيف ---
AR_LETTERS_RE = re.compile(r'[\u0600-\u06FF]')
EMOJI_MISC_RE = re.compile(r'[\u2600-\u27BF\U0001F300-\U0001FAFF]+')
BEIN_RE = re.compile(r'bein\s*sports?', re.IGNORECASE)

def strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

def normalize_text(text: str) -> str:
    """تطبيع عام (ينفع للأسماء بالعربي أو الإنجليزي)"""
    if not text:
        return ""
    text = str(text)
    text = EMOJI_MISC_RE.sub('', text)
    text = re.sub(r'\(.*?\)', '', text)
    text = strip_accents(text)
    text = text.lower()
    text = text.replace("&", "and")
    text = re.sub(r'\bfc\b|\bsc\b|\bcf\b', '', text)
    text = text.replace(" ", "").replace("-", "").replace("_", "")
    text = text.replace("ال", "")
    text = re.sub(r'[^a-z0-9\u0600-\u06FF]', '', text)
    return text.strip()

def is_empty(v):
    return v is None or v == "" or v == [] or v == {}

def safe_update(target: dict, source: dict, fields: list[str], overwrite: bool = False):
    for f in fields:
        src_val = source.get(f)
        if is_empty(src_val):
            continue
        if overwrite:
            target[f] = src_val
        else:
            if is_empty(target.get(f)):
                target[f] = src_val

def unique_preserving(seq):
    seen = set()
    out = []
    for x in seq:
        key = str(x).lower().strip()
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out

def is_bein_channel(name: str) -> bool:
    return bool(BEIN_RE.search(name or ""))

# --- قاموس مبسط لترجمة أندية إنجليزية -> عربي (عشان نقدر نطابق liveonsat باليلا بالعربي) ---
TEAM_NAME_MAP = {
    # (نفس جزء من القاموس السابق — كفاية للمطابقة الشائعة)
    "Manchester City": "مانشستر سيتي", "Arsenal": "أرسنال",
    "Manchester United": "مانشستر يونايتد", "Liverpool": "ليفربول",
    "Chelsea": "تشيلسي", "Tottenham Hotspur": "توتنهام هوتسبير", "Tottenham": "توتنهام",
    "Newcastle United": "نيوكاسل يونايتد", "Aston Villa": "أستون فيلا",
    "Real Madrid": "ريال مدريد", "Barcelona": "برشلونة",
    "Bayern Munich": "بايرن ميونخ", "Borussia Dortmund": "بوروسيا دورتموند",
    "Paris Saint-Germain": "باريس سان جيرمان", "PSG": "باريس سان جيرمان",
    "Inter Milan": "إنتر ميلان", "Inter": "إنتر ميلان", "AC Milan": "ميلان",
    "Juventus": "يوفنتوس",
    "Sporting CP": "سبورتينغ لشبونة", "Sporting": "سبورتينغ لشبونة",
    "Benfica": "بنفيكا", "Porto": "بورتو",
}

TEAM_ALIASES = {"Milan": "ميلان", "Atletico Madrid": "أتلتيكو مدريد"}

def translate_team_or_fallback(name_en: str) -> str:
    """نبسّط مطابقة liveonsat (الإنجليزي) مع يلا (العربي): نرجّع العربي إذا نعرف، وإلا نرجّع الإنجليزي نفسه."""
    name_en = (name_en or "").strip()
    if not name_en:
        return ""
    if name_en in TEAM_NAME_MAP:
        return TEAM_NAME_MAP[name_en]
    norm = normalize_text(name_en)
    for k, v in {**TEAM_NAME_MAP, **TEAM_ALIASES}.items():
        if normalize_text(k) == norm:
            return v
    return name_en

def parse_title_to_teams(title: str):
    parts = re.split(r'\s+v(?:s)?\.?\s+', title or "", flags=re.IGNORECASE)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return (title or "").strip(), None

# --- قنوات وتنظيف ---
CHANNEL_BLOCKLIST = {s.lower(): True for s in [
    "Astro Football HD", "ST World Football HD", "SuperSport Football HD",
]}
def is_blocked_channel(name: str) -> bool:
    return (name or "").lower().strip() in CHANNEL_BLOCKLIST

# (اختياري) قائمة مفاتيح قنوات معروفة — نستخدمها كفلتر خفيف لتقليل الضجيج من liveonsat
CHANNEL_KEYWORDS = [
    "beIN Sports", "MATCH! Futbol", "Football HD",
    "Sport TV", "ESPN", "DAZN", "MATCH! Premier", "Sky Sports",
    "IRIB Varzesh", "Persiana Sport", "MBC Action", "TNT Sports",
    "SSC", "Shahid", "STARZPLAY", "Canal+", "Viaplay", "Prime Video",
]

SPLIT_RE = re.compile(r'\s*(?:,|،|/|\||&| و | and )\s*', re.IGNORECASE)

def to_list_channels(val):
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        if not val.strip():
            return []
        parts = [p.strip() for p in SPLIT_RE.split(val) if p.strip()]
        return parts if parts else [val.strip()]
    return []

def collect_yalla_channels(yalla_match: dict) -> list:
    keys_try = [
        "channels_raw", "channels", "tv_channels",
        "channel", "channel_ar", "channel_en",
        "broadcasters", "broadcaster"
    ]
    out = []
    for k in keys_try:
        if k in yalla_match:
            out.extend(to_list_channels(yalla_match.get(k)))
    out = [c.strip() for c in out if c and c.strip()]
    out = [c for c in out if not is_blocked_channel(c)]
    return unique_preserving(out)

def pick_primary_yalla_channel(chs: list[str]) -> str | None:
    """نختار قناة وحدة من يلا: نفضّل beIN، وإلا أول قناة."""
    if not chs:
        return None
    for c in chs:
        if is_bein_channel(c):
            return c.strip()
    return chs[0].strip()

# --- نبني فهرس liveonsat بالقنوات فقط ---
def build_liveonsat_index(live_data: dict) -> dict:
    """
    key = normalize_text(ar_home) + '-' + normalize_text(ar_away)
    القيمة: قائمة قنوات (بعد تنظيف/فلترة، بدون beIN)
    """
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

        # اجمع قنوات liveonsat (قد تكون في channels_raw أو غيرها)
        raw_channels = m.get("channels_raw") or m.get("channels") or []
        if isinstance(raw_channels, str):
            raw_channels = to_list_channels(raw_channels)
        cleaned = []
        for ch in raw_channels:
            if not ch:
                continue
            if is_bein_channel(ch):
                continue  # beIN نخليها من يلا فقط
            if is_blocked_channel(ch):
                continue
            # فلتر خفيف بالكيووردز حتى ما نجيب أي نص عشوائي
            ch_l = ch.lower()
            if any(kw.lower() in ch_l for kw in CHANNEL_KEYWORDS):
                cleaned.append(re.sub(r'\s+', ' ', str(ch)).strip())
        if cleaned:
            index[key] = unique_preserving(cleaned)
    return index

def filter_matches_inverted():
    # 1) حمّل يلا شوت (المصدر الأساسي)
    try:
        yresp = requests.get(YALLASHOOT_URL, timeout=20)
        yresp.raise_for_status()
        yalla = yresp.json()
    except requests.exceptions.RequestException as e:
        print(f"ERROR: fetching yallashoot failed: {e}")
        return

    yalla_matches = (yalla or {}).get("matches", []) or []
    if not yalla_matches:
        print("WARNING: yallashoot returned 0 matches.")
        output_data = {"date": yalla.get("date"), "source_url": YALLASHOOT_URL, "matches": []}
        with OUTPUT_PATH.open("w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        return

    # 2) حمّل liveonsat المحلي لنكمل منه القنوات
    live_data = {}
    try:
        with INPUT_PATH.open("r", encoding="utf-8") as f:
            live_data = json.load(f)
    except Exception as e:
        print(f"WARNING: Could not read liveonsat file ({INPUT_PATH}): {e}")

    live_index = build_liveonsat_index(live_data)

    # 3) ابنِ خريطة يلا شوت (مفتاح المطابقة عربي-عربي)
    def yalla_key(h_ar: str, a_ar: str) -> str:
        return f"{normalize_text(h_ar)}-{normalize_text(a_ar)}"

    # 4) ادمج: لكل مباراة من يلا -> قناة واحدة من يلا + تكملة قنوات من liveonsat
    out_matches = []
    for m in yalla_matches:
        home_ar = (m.get("home") or m.get("home_team") or "").strip()
        away_ar = (m.get("away") or m.get("away_team") or "").strip()
        if not home_ar or not away_ar:
            # إذا أسماء ناقصة، نتجنبها (نقدر نحاول مفاتيح ثانية، بس نخليها بسيطة)
            continue

        # جمع قنوات يلا + اختيار قناة وحيدة
        y_chs = collect_yalla_channels(m)
        primary = pick_primary_yalla_channel(y_chs)
        yalla_only = [primary] if primary else []

        # قنوات إضافية من liveonsat بحسب نفس المباراة (مطابقة بالعربي)
        key = yalla_key(home_ar, away_ar)
        extra = live_index.get(key, [])

        # قائمة نهائية للقنوات: قناة يلا المختارة + قنوات liveonsat (بدون تكرار)
        channels = unique_preserving([*yalla_only, *extra])

        # كوّن السجل النهائي — بدون ترجمة/فلترة بطولات
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
        "matches": out_matches
    }

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"Done. Wrote {len(out_matches)} matches from yallashoot with extra channels from liveonsat (beIN kept from yalla only).")

if __name__ == "__main__":
    filter_matches_inverted()

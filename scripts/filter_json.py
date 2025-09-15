# scripts/filter_json.py
import json
import re
import unicodedata
from pathlib import Path
import requests
import os

# ===== ترجمة/مطابقة متقدمة (اختيارية) =====
try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None

# ===== إعدادات =====
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"   # نكمّل منه القنوات
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"
YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"

# thresholds التجريبية بالترتيب
THRESHOLDS = [90, 84, 78, 72]

# ===== أدوات عامة =====
AR_LETTERS_RE = re.compile(r'[\u0600-\u06FF]')
EMOJI_MISC_RE = re.compile(r'[\u2600-\u27BF\U0001F300-\U0001FAFF]+')
BEIN_RE = re.compile(r'bein\s*sports?', re.I)

GARBAGE_TOKENS_RE = re.compile(
    r"""
    (\(\s*\$?\/?geo\/?R\s*\))|(\(\s*geo\/?R\s*\))|
    (\(\s*\$\/?geo\s*\))|(\$\/?geo\/?R)|
    (📺)|(\[online\])|(\[app\])
    """, re.I | re.X
)

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
    text = re.sub(r"\b(fc|sc|cf)\b", "", text)
    text = text.replace(" ", "").replace("-", "").replace("_", "")
    text = text.replace("ال", "")
    # بدائل عربية شائعة
    text = text.replace("ى", "ي").replace("ة", "ه")
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

def clean_channel_display(name: str) -> str:
    if not name:
        return ""
    s = str(name)
    s = EMOJI_MISC_RE.sub("", s)
    s = GARBAGE_TOKENS_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def is_bein_channel(name: str) -> bool:
    return bool(BEIN_RE.search(name or ""))

# ===== القنوات المدعومة (فلترة صارمة) =====
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
_supported_tokens = set()
for c in SUPPORTED_CHANNELS:
    c_low = c.lower()
    _supported_tokens.add(c_low)
    _supported_tokens.add(c_low.replace(" hd", ""))
SUPPORTED_TOKENS = list(_supported_tokens)

def is_supported_channel(name: str) -> bool:
    if not name:
        return False
    n = name.lower()
    return any(tok in n for tok in SUPPORTED_TOKENS)

# ===== قاموس فرق موسّع (المذكورة + مشهورة) =====
TEAM_MAP_EN2AR = {
    # Sample you gave
    "Hellas Verona": "هيلاس فيرونا", "Cremonese": "كريمونيزي",

    # Italy
    "Como": "كومو", "Genoa": "جنوى", "Monza": "مونزا", "Fiorentina": "فيورنتينا", "Lazio": "لاتسيو", "Atalanta": "أتالانتا",
    "Inter": "إنتر ميلان", "Inter Milan": "إنتر ميلان", "AC Milan": "ميلان", "Milan": "ميلان", "Juventus": "يوفنتوس", "Napoli": "نابولي", "Roma": "روما",
    # Spain
    "Espanyol": "إسبانيول", "Mallorca": "ريال مايوركا", "Real Mallorca": "ريال مايوركا",
    "Real Madrid": "ريال مدريد", "Barcelona": "برشلونة", "Atletico Madrid": "أتلتيكو مدريد",
    # France
    "Guingamp": "جانجون", "Montpellier": "مونبلييه",
    # KSA / Qatar / UAE / Iraq / UZB / MOR
    "Al Ahli": "الأهلي السعودي", "Al-Ahli": "الأهلي السعودي",
    "Al Ittihad": "الاتحاد", "Al-Ittihad": "الاتحاد",
    "Al Sadd": "السد",
    "Al Gharafa": "الغرافة", "Al-Gharafa": "الغرافة",
    "Sharjah": "الشارقة", "Al Wahda": "الوحدة", "Al-Wahda": "الوحدة",
    "Al Shorta": "الشرطة", "Al-Shorta": "الشرطة",
    "Nasaf Qarshi": "ناساف كارشي", "Nasaf": "ناساف كارشي",
    "Ittihad Tanger": "اتحاد طنجة", "IR Tanger": "اتحاد طنجة", "Olympic Safi": "أولمبيك آسفي", "OC Safi": "أولمبيك آسفي",
}
# عكس القاموس + إضافات عربية مباشرة
TEAM_MAP_AR2EN = {v: k for k, v in TEAM_MAP_EN2AR.items()}
TEAM_MAP_AR2EN.update({
    "الأهلي السعودي": "Al Ahli",
    "الاتحاد": "Al Ittihad",
    "السد": "Al Sadd",
    "الغرافة": "Al Gharafa",
    "الشارقة": "Sharjah",
    "الوحدة": "Al Wahda",
    "الشرطة": "Al Shorta",
    "ناساف كارشي": "Nasaf Qarshi",
    "اتحاد طنجة": "Ittihad Tanger",
    "أولمبيك آسفي": "Olympic Safi",
    "جانجون": "Guingamp",
    "مونبلييه": "Montpellier",
    "إسبانيول": "Espanyol",
    "ريال مايوركا": "Mallorca",
    "كومو": "Como",
    "جنوى": "Genoa",
    "هيلاس فيرونا": "Hellas Verona",
    "كريمونيسي": "Cremonese",
})

def translate_en_to_ar(name: str) -> str:
    if not name:
        return ""
    if name in TEAM_MAP_EN2AR:
        return TEAM_MAP_EN2AR[name]
    if GoogleTranslator:
        try:
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
            left, right = parts[0].strip(), parts[1].strip()
            if left and right:
                return left, right
    return None, None

def extract_liveonsat_match_teams(m: dict) -> tuple[str | None, str | None]:
    home = (m.get("home") or m.get("home_team"))
    away = (m.get("away") or m.get("away_team"))
    if home and away:
        return str(home).strip(), str(away).strip()
    title = (m.get("title") or "").strip()
    h, a = parse_title_to_teams_generic(title)
    return h, a

# يلا شوت: قنوات
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
    keys_try = ["channels_raw","channels","tv_channels","channel","channel_ar","channel_en","broadcasters","broadcaster"]
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

# فهرس liveonsat: (home_en, away_en, [channels])
def build_liveonsat_entries(live_data: dict) -> list[tuple[str,str,list[str]]]:
    entries = []
    matches = (live_data or {}).get("matches", []) or []
    for m in matches:
        h_en, a_en = extract_liveonsat_match_teams(m)
        if not h_en or not a_en:
            continue
        raw_channels = []
        for ck in ("channels_raw","channels","tv_channels","broadcasters","broadcaster"):
            if ck in m and m[ck]:
                raw = m[ck]
                if isinstance(raw, list):
                    raw_channels.extend([str(x) for x in raw])
                elif isinstance(raw, str):
                    raw_channels.extend(to_list_channels(raw))

        filtered = []
        for ch in raw_channels:
            if not ch:
                continue
            ch_clean = clean_channel_display(ch)
            if not ch_clean:
                continue
            if is_bein_channel(ch_clean):
                continue  # beIN من يلا فقط
            if is_supported_channel(ch_clean):
                filtered.append(ch_clean)
        filtered = unique_preserving(filtered)
        if filtered:
            entries.append((str(h_en).strip(), str(a_en).strip(), filtered))
    return entries

def ok_ratio(a: str, b: str) -> int:
    if not a or not b:
        return 0
    if fuzz:
        return fuzz.token_set_ratio(a, b)
    return 100 if a == b else 0

def best_match_channels(home_ar: str, away_ar: str, lons_entries: list[tuple[str,str,list[str]]]) -> list[str]:
    """
    نختار أفضل تطابق عبر عدة عتبات. ندمج قنوات كل السجلات التي تتجاوز العتبة الأعلى التي أمكن تحقيقها.
    """
    hy_ar = normalize_text(home_ar); ay_ar = normalize_text(away_ar)
    # AR->EN
    home_en_from_ar = translate_ar_to_en(home_ar); away_en_from_ar = translate_ar_to_en(away_ar)
    hy_en = normalize_text(home_en_from_ar); ay_en = normalize_text(away_en_from_ar)

    scored = []
    for (h_en, a_en, chans) in lons_entries:
        # EN->AR
        h_ar_guess = translate_en_to_ar(h_en); a_ar_guess = translate_en_to_ar(a_en)
        h_ar_norm = normalize_text(h_ar_guess); a_ar_norm = normalize_text(a_ar_guess)
        r1 = min(ok_ratio(h_ar_norm, hy_ar), ok_ratio(a_ar_norm, ay_ar))
        r2 = min(ok_ratio(h_ar_norm, ay_ar), ok_ratio(a_ar_norm, hy_ar))
        match_ar = max(r1, r2)

        # EN مباشرة مع EN (AR->EN)
        h_en_norm = normalize_text(h_en); a_en_norm = normalize_text(a_en)
        r3 = min(ok_ratio(h_en_norm, hy_en), ok_ratio(a_en_norm, ay_en))
        r4 = min(ok_ratio(h_en_norm, ay_en), ok_ratio(a_en_norm, hy_en))
        match_en = max(r3, r4)

        best = max(match_ar, match_en)
        scored.append((best, chans))

    if not scored:
        return []

    # أعلى نتيجة حققتها أي مباراة
    top_score = max(s for s, _ in scored)
    # اختَر أعلى عتبة <= top_score
    used_thr = None
    for t in THRESHOLDS:
        if top_score >= t:
            used_thr = t
            break
    if used_thr is None:
        return []

    # اجمع كل القنوات التي درجة تطابقها >= العتبة المختارة
    out = []
    for s, ch in scored:
        if s >= used_thr:
            out.extend(ch)
    return unique_preserving(out)

# ===== الرئيسي =====
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
        print("[!] yallashoot empty.")
        with OUTPUT_PATH.open("w", encoding="utf-8") as f:
            json.dump({"date": yalla.get("date"), "source_url": YALLASHOOT_URL, "matches": []}, f, ensure_ascii=False, indent=2)
        return

    # 2) liveonsat محلي
    try:
        with INPUT_PATH.open("r", encoding="utf-8") as f:
            live_data = json.load(f)
    except Exception as e:
        print(f"[!] WARNING reading liveonsat: {e}")
        live_data = {}

    lons_entries = build_liveonsat_entries(live_data)

    # 3) دمج
    out_matches = []
    used_extra = 0
    for m in yalla_matches:
        home_ar = (m.get("home") or m.get("home_team") or "").strip()
        away_ar = (m.get("away") or m.get("away_team") or "").strip()
        if not home_ar or not away_ar:
            continue

        # قناة أساسية من يلا
        y_chs = collect_yalla_channels(m)
        primary = pick_primary_yalla_channel(y_chs)
        yalla_only = [primary] if primary else []

        # قنوات إضافية من liveonsat (أفضل تطابق)
        extra = best_match_channels(home_ar, away_ar, lons_entries)
        if extra:
            used_extra += 1

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

    output = {"date": yalla.get("date"), "source_url": YALLASHOOT_URL, "matches": out_matches}
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[✓] Done. Matches: {len(out_matches)} | Added-extra-from-liveonsat: {used_extra} | thresholds={THRESHOLDS}")
    if GoogleTranslator is None:
        print("[!] deep-translator not installed — install it for best matching.")
    if fuzz is None:
        print("[!] rapidfuzz not installed — install it to enable fuzzy matching.")

if __name__ == "__main__":
    filter_matches()

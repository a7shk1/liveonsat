# scripts/filter_json.py
# -*- coding: utf-8 -*-
import json
import re
import unicodedata
from pathlib import Path
import requests
import os

# ===== ترجمة اختيارية (fallback) =====
try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

# ===== إعدادات =====
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"        # نكمّل منه القنوات
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"
YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"

# ===== أدوات عامة =====
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
    text = re.sub(r"\b(fc|sc|cf|u\d+)\b", "", text)  # شيل لاحقات شائعة
    text = text.replace("ال", "")
    # بدائل عربية شائعة
    text = text.replace("ى", "ي").replace("ة", "ه").replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ـ", "")  # تطويل
    text = text.replace(" ", "").replace("-", "").replace("_", "")
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

def to_list_channels(val):
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        s = val.strip()
        if not s: return []
        parts = re.split(r"\s*(?:,|،|/|\||&| و | and )\s*", s, flags=re.I)
        return [p for p in parts if p]
    return []

def clean_channel_display(name: str) -> str:
    if not name: return ""
    s = str(name)
    s = EMOJI_MISC_RE.sub("", s)
    s = re.sub(r"\s*\((?:\$?\/?geo\/?R|geo\/?R|\$\/?geo)\)\s*", "", s, flags=re.I)
    s = re.sub(r"📺|\[online\]|\[app\]", "", s, flags=re.I)
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
    cl = c.lower()
    _supported_tokens.add(cl)
    _supported_tokens.add(cl.replace(" hd", ""))
SUPPORTED_TOKENS = list(_supported_tokens)

def is_supported_channel(name: str) -> bool:
    if not name: return False
    n = name.lower()
    return any(tok in n for tok in SUPPORTED_TOKENS)

# =====================================================================
# قاموس ضخم يدوي (أندية عربية + أوروبية + منتخبات) — موسّع للغاية
# ملاحظة: تقدر تضيف له لاحقًا بحرية، السكربت يستخدمه أولًا قبل أي ترجمة
# =====================================================================

EN2AR = {
    # ----- منتخبات عربية -----
    "Iraq": "العراق", "Saudi Arabia": "السعودية", "Qatar": "قطر", "United Arab Emirates": "الإمارات",
    "UAE": "الإمارات", "Kuwait": "الكويت", "Bahrain": "البحرين", "Oman": "عُمان", "Jordan": "الأردن",
    "Syria": "سوريا", "Lebanon": "لبنان", "Palestine": "فلسطين", "Yemen": "اليمن", "Egypt": "مصر",
    "Libya": "ليبيا", "Tunisia": "تونس", "Algeria": "الجزائر", "Morocco": "المغرب",
    "Somalia": "الصومال", "Sudan": "السودان", "Mauritania": "موريتانيا",

    # ----- منتخبات عالمية مشهورة -----
    "Brazil": "البرازيل", "Argentina": "الأرجنتين", "Germany": "ألمانيا", "France": "فرنسا",
    "Spain": "إسبانيا", "Italy": "إيطاليا", "England": "إنجلترا", "Portugal": "البرتغال",
    "Netherlands": "هولندا", "Belgium": "بلجيكا", "Croatia": "كرواتيا", "Uruguay": "أوروجواي",
    "USA": "الولايات المتحدة", "United States": "الولايات المتحدة", "Mexico": "المكسيك",
    "Japan": "اليابان", "South Korea": "كوريا الجنوبية", "Australia": "أستراليا",

    # ----- أندية سعودية -----
    "Al Hilal": "الهلال", "Al-Hilal": "الهلال",
    "Al Nassr": "النصر", "Al-Nassr": "النصر",
    "Al Ittihad": "الاتحاد", "Al-Ittihad": "الاتحاد",
    "Al Ahli": "الأهلي السعودي", "Al-Ahli": "الأهلي السعودي",
    "Al Shabab": "الشباب", "Al-Shabab": "الشباب",
    "Al Ettifaq": "الاتفاق", "Al-Ettifaq": "الاتفاق",
    "Al Fayha": "الفيحاء", "Al-Fayha": "الفيحاء",
    "Al Raed": "الرائد", "Al-Raed": "الرائد",
    "Al Taawoun": "التعاون", "Al-Taawoun": "التعاون",
    "Abha": "أبها", "Damac": "ضمك", "Al Fateh": "الفتح", "Al-Fateh": "الفتح",
    "Al Okhdood": "الأخدود", "Al-Okhdood": "الأخدود",
    "Al Riyadh": "الرياض", "Al-Riyadh": "الرياض",
    "Al Wehda": "الوحدة", "Al-Wehda": "الوحدة",
    "Al Qadsiah": "القادسية", "Al-Qadsiah": "القادسية",

    # ----- أندية قطر -----
    "Al Sadd": "السد", "Al-Sadd": "السد",
    "Al Duhail": "الدحيل", "Al-Duhail": "الدحيل",
    "Al Gharafa": "الغرافة", "Al-Gharafa": "الغرافة",
    "Al Rayyan": "الريان", "Al-Rayyan": "الريان",
    "Qatar SC": "قطر", "Al Arabi": "العربي", "Al-Arabi": "العربي",
    "Al Wakrah": "الوكرة", "Al-Wakrah": "الوكرة",

    # ----- أندية الإمارات -----
    "Al Ain": "العين", "Al-Ain": "العين",
    "Al Wahda": "الوحدة", "Al-Wahda": "الوحدة",
    "Al Jazira": "الجزيرة", "Al-Jazira": "الجزيرة",
    "Shabab Al Ahli": "شباب الأهلي", "Al Nasr Dubai": "النصر الإماراتي",
    "Sharjah": "الشارقة", "Khor Fakkan": "خورفكان", "Bani Yas": "بني ياس",

    # ----- أندية العراق -----
    "Al Shorta": "الشرطة", "Al-Shorta": "الشرطة",
    "Al Zawraa": "الزوراء", "Al-Zawraa": "الزوراء",
    "Al Quwa Al Jawiya": "القوة الجوية", "Al-Quwa Al-Jawiya": "القوة الجوية",
    "Naft Al Wasat": "نفط الوسط", "Al Najaf": "النجف",
    "Karbalaa": "كربلاء", "Duhok": "دهوك", "Erbil": "أربيل", "Al Mina'a": "الميناء", "Al-Minaa": "الميناء",

    # ----- أندية المغرب -----
    "Wydad": "الوداد", "Raja": "الرجاء", "FUS Rabat": "الفتح الرباطي",
    "RS Berkane": "نهضة بركان", "Hassania Agadir": "حسنية أكادير",
    "Ittihad Tanger": "اتحاد طنجة", "OC Safi": "أولمبيك آسفي", "Olympic Safi": "أولمبيك آسفي",

    # ----- أندية تونس -----
    "Esperance": "الترجي", "Etoile du Sahel": "النجم الساحلي",
    "Club Africain": "النادي الإفريقي", "CS Sfaxien": "الصفاقسي",

    # ----- أندية الجزائر -----
    "USM Alger": "اتحاد العاصمة", "JS Kabylie": "شبيبة القبائل",
    "MC Alger": "مولودية الجزائر",

    # ----- أندية مصر -----
    "Al Ahly": "الأهلي", "Zamalek": "الزمالك", "Pyramids": "بيراميدز",
    "Ismaily": "الإسماعيلي", "Al Masry": "المصري", "Smouha": "سموحة",

    # ----- أندية الأردن/سوريا/لبنان -----
    "Al Faisaly": "الفيصلي", "Al Wehdat": "الوحدات",
    "Al Jazeera Amman": "الجزيرة (الأردن)", "Shabab Al Ordon": "شباب الأردن",
    "Al Jaish": "الجيش", "Al Karamah": "الكرامة",
    "Al Ahed": "العهد", "Al Nejmeh": "النجمة",

    # ----- أندية أوروبية كبيرة -----
    "Real Madrid": "ريال مدريد", "Barcelona": "برشلونة", "Atletico Madrid": "أتلتيكو مدريد",
    "Sevilla": "إشبيلية", "Valencia": "فالنسيا", "Villarreal": "فياريال", "Real Sociedad": "ريال سوسيداد",
    "Espanyol": "إسبانيول", "Real Mallorca": "ريال مايوركا", "Mallorca": "ريال مايوركا",
    "Bayern Munich": "بايرن ميونخ", "Borussia Dortmund": "بوروسيا دورتموند",
    "RB Leipzig": "لايبزيغ", "Bayer Leverkusen": "باير ليفركوزن",
    "Inter": "إنتر ميلان", "Inter Milan": "إنتر ميلان",
    "AC Milan": "ميلان", "Milan": "ميلان", "Juventus": "يوفنتوس", "Napoli": "نابولي", "Roma": "روما", "Lazio": "لاتسيو", "Fiorentina": "فيورنتينا", "Atalanta": "أتالانتا", "Torino": "تورينو", "Udinese": "أودينيزي", "Sassuolo": "ساسولو", "Monza": "مونزا", "Como": "كومو", "Genoa": "جنوى", "Hellas Verona": "هيلاس فيرونا", "Cremonese": "كريمونيزي",
    "Paris Saint-Germain": "باريس سان جيرمان", "PSG": "باريس سان جيرمان",
    "Marseille": "مارسيليا", "Lyon": "ليون", "Monaco": "موناكو", "Lille": "ليل", "Nice": "نيس", "Rennes": "رين", "Brest": "بريست", "Strasbourg": "ستراسبورغ", "Montpellier": "مونبلييه", "Guingamp": "جانجون",
    "Manchester City": "مانشستر سيتي", "Manchester United": "مانشستر يونايتد", "Arsenal": "أرسنال", "Liverpool": "ليفربول",
    "Chelsea": "تشيلسي", "Tottenham Hotspur": "توتنهام", "Tottenham": "توتنهام", "Newcastle United": "نيوكاسل يونايتد", "Aston Villa": "أستون فيلا", "Everton": "إيفرتون", "West Ham United": "وست هام يونايتد", "Wolves": "ولفرهامبتون", "Wolverhampton": "ولفرهامبتون",
    "Ajax": "أياكس", "PSV Eindhoven": "آيندهوفن", "Feyenoord": "فاينورد",
    "Benfica": "بنفيكا", "Porto": "بورتو", "Sporting CP": "سبورتينغ لشبونة", "Sporting": "سبورتينغ لشبونة",
}

# عكس القاموس
AR2EN = {v: k for k, v in EN2AR.items()}

def translate_en_to_ar(name: str) -> str:
    if not name: return ""
    if name in EN2AR: return EN2AR[name]
    if GoogleTranslator:
        try:
            return (GoogleTranslator(source="en", target="ar").translate(name) or name).strip()
        except Exception:
            return name
    return name

def translate_ar_to_en(name: str) -> str:
    if not name: return ""
    if name in AR2EN: return AR2EN[name]
    if GoogleTranslator:
        try:
            return (GoogleTranslator(source="ar", target="en").translate(name) or name).strip()
        except Exception:
            return name
    return name

# ===== parsing =====
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
    return parse_title_to_teams_generic(title)

# ===== بناء liveonsat entries بالقنوات المسموحة فقط =====
def build_liveonsat_entries(live_data: dict):
    entries = []
    matches = (live_data or {}).get("matches", []) or []
    for m in matches:
        h_en, a_en = extract_liveonsat_match_teams(m)
        if not h_en or not a_en:
            continue

        # قنوات من عدة حقول
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
            ch = clean_channel_display(ch)
            if not ch: continue
            if is_bein_channel(ch):  # beIN من يلا فقط
                continue
            if is_supported_channel(ch):
                filtered.append(ch)
        filtered = unique_preserving(filtered)
        if filtered:
            entries.append({
                "home_en": str(h_en).strip(),
                "away_en": str(a_en).strip(),
                "home_ar": translate_en_to_ar(str(h_en).strip()),
                "away_ar": translate_en_to_ar(str(a_en).strip()),
                "channels": filtered
            })
    return entries

# ===== المطابقة الصارمة بعد الترجمة =====
def equal_norm(a: str, b: str) -> bool:
    return normalize_text(a) == normalize_text(b)

def match_channels_strict(home_ar_y: str, away_ar_y: str, lons_entries: list) -> list:
    """
    يطابق صارمًا باستخدام الترجمة:
      - نقارن:
        1) AR_yalla == (EN_live → AR)  لكل من home/away (والعكس بالترتيب)
        2) (AR_yalla → EN) == EN_live   لكل من home/away (والعكس بالترتيب)
    أي تطابق كامل يُقبل.
    """
    if not home_ar_y or not away_ar_y:
        return []

    # ترجمات yalla->EN مرّة وحدة
    home_en_y = translate_ar_to_en(home_ar_y)
    away_en_y = translate_ar_to_en(away_ar_y)

    out = []
    for e in lons_entries:
        h_en = e["home_en"]; a_en = e["away_en"]
        h_ar = e["home_ar"]; a_ar = e["away_ar"]

        # شرط A: قارن عربي لعربي (EN_live مترجم للعربي)
        a_ok = equal_norm(home_ar_y, h_ar) and equal_norm(away_ar_y, a_ar)
        b_ok = equal_norm(home_ar_y, a_ar) and equal_norm(away_ar_y, h_ar)

        # شرط B: قارن إنجليزي لإنجليزي (yalla مترجم للإنجليزي)
        c_ok = equal_norm(home_en_y, h_en) and equal_norm(away_en_y, a_en)
        d_ok = equal_norm(home_en_y, a_en) and equal_norm(away_en_y, h_en)

        if a_ok or b_ok or c_ok or d_ok:
            out.extend(e["channels"])

    return unique_preserving(out)

# ===== قنوات يلا شوت =====
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

        # قنوات إضافية من liveonsat عبر مطابقة صارمة بعد الترجمة
        extra = match_channels_strict(home_ar, away_ar, lons_entries)
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

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump({"date": yalla.get("date"), "source_url": YALLASHOOT_URL, "matches": out_matches}, f, ensure_ascii=False, indent=2)

    print(f"[✓] Done. Matches: {len(out_matches)} | Added-extra-from-liveonsat: {used_extra}")
    if GoogleTranslator is None:
        print("[!] deep-translator not installed — fallback to dictionary only.")

if __name__ == "__main__":
    filter_matches()

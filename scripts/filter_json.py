# scripts/filter_json.py
import json
import re
import unicodedata
from pathlib import Path
import requests

# --- الإعدادات الأساسية ---
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"
YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"

# --- أدوات مساعدة للتنظيف ---
AR_LETTERS_RE = re.compile(r'[\u0600-\u06FF]')
EMOJI_MISC_RE = re.compile(r'[\u2600-\u27BF\U0001F300-\U0001FAFF]+')
BEIN_RE = re.compile(r'bein\s*sports?', re.IGNORECASE)

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
        key = x.lower().strip()
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out

def contains_ignore_case(seq, item):
    il = item.lower()
    return any(il == s.lower() for s in seq)

def is_bein_channel(name: str) -> bool:
    return bool(BEIN_RE.search(name or ""))

# --- ✨ قائمة البطولات النهائية (مثبتة) ✨ ---
TRANSLATION_MAP = {
    "English Premier League": "الدوري الإنجليزي الممتاز", "Spanish La Liga (Primera)": "الدوري الإسباني",
    "Italian Serie A": "الدوري الإيطالي", "German 1. Bundesliga": "الدوري الألماني", "French Ligue 1": "الدوري الفرنسي",
    "English FA Cup": "كأس الاتحاد الإنجليزي", "Carabao Cup": "كأس كاراباو", "EFL Cup": "كأس الرابطة الإنجليزية",
    "Community Shield": "الدرع الخيرية الإنجليزية", "Copa del Rey": "كأس ملك إسبانيا", "Supercopa": "كأس السوبر الإسباني",
    "Italian Cup (Coppa Italia)": "كأس إيطاليا", "Supercoppa Italiana": "كأس السوبر الإيطالي",
    "DFB-Pokal": "كأس ألمانيا", "DFL-Supercup": "كأس السوبر الألماني", "Coupe de France": "كأس فرنسا",
    "Trophée des Champions": "كأس الأبطال الفرنسي", "Champions League": "دوري أبطال أوروبا", "Europa League": "الدوري الأوروبي",
    "Conference League": "دوري المؤتمر الأوروبي", "Club World Cup": "كأس العالم للأندية",
    "World Cup": "كأس العالم", "WC Qualifier": "تصفيات كأس العالم", "UEFA Euro": "بطولة أمم أوروبا (اليورو)",
    "Copa America": "كوبا أمريكا", "Africa Cup of Nations": "كأس الأمم الأفريقية", "AFCON": "كأس الأمم الأفريقية",
    "AFC Asian Cup": "كأس آسيا", "Nations League": "دوري الأمم", "Arab Cup": "كأس العرب",
    "Saudi Professional League": "الدوري السعودي للمحترفين",
}
LEAGUE_KEYWORDS = list(TRANSLATION_MAP.keys())

# --- ✨ قاموس الفرق (موسع + بدائل) ✨ ---
TEAM_NAME_MAP = {
    # Saudi Arabia
    "Al-Hilal": "الهلال", "Al Hilal": "الهلال",
    "Al-Nassr": "النصر", "Al Nassr": "النصر",
    "Al-Ittihad": "الاتحاد", "Al Ittihad": "الاتحاد",
    "Al-Ahli": "الأهلي", "Al Ahli": "الأهلي",
    "Al-Shabab": "الشباب", "Al Shabab": "الشباب",
    "Al-Ettifaq": "الاتفاق", "Al Ettifaq": "الاتفاق", "Al Ittifaq": "الاتفاق",
    "Al-Taawoun": "التعاون", "Al Taawoun": "التعاون",
    "Damac": "ضمك",
    "Al-Fateh": "الفتح", "Al Fateh": "الفتح",
    "Al-Raed": "الرائد", "Al Raed": "الرائد",
    "Al-Khaleej": "الخليج", "Al Khaleej": "الخليج",
    "Abha": "أبها",
    "Al-Fayha": "الفيحاء", "Al Fayha": "الفيحاء",
    "Al-Wehda": "الوحدة", "Al Wehda": "الوحدة",
    "Al-Okhdood": "الأخدود", "Al Okhdood": "الأخدود",
    "Al-Hazem": "الحزم", "Al Hazem": "الحزم",
    "Al-Riyadh": "الرياض", "Al Riyadh": "الرياض",
    "Al Qadsiah": "القادسية", "Al-Qadsiah": "القادسية",
    "Neom": "نيوم", "Al Najma": "النجمة", "Al Kholood": "الخلود", "Al-Kholood": "الخلود",

    # England
    "Manchester City": "مانشستر سيتي", "Arsenal": "أرسنال",
    "Manchester United": "مانشستر يونايتد", "Liverpool": "ليفربول",
    "Chelsea": "تشيلسي", "Tottenham Hotspur": "توتنهام هوتسبير", "Tottenham": "توتنهام",
    "Newcastle United": "نيوكاسل يونايتد", "Aston Villa": "أستون فيلا",
    "West Ham United": "وست هام يونايتد", "Brighton & Hove Albion": "برايتون",
    "Fulham": "فولهام", "Crystal Palace": "كريستال بالاس",
    "Brentford": "برينتفورد", "Wolverhampton Wanderers": "ولفرهامبتون",
    "Everton": "إيفرتون", "Nottingham Forest": "نوتنغهام فورست",
    "Bournemouth": "بورنموث", "Ipswich Town": "إيبسويتش تاون",
    "Leicester City": "ليستر سيتي", "Southampton": "ساوثهامبتون", "Burnley": "بيرنلي",

    # Spain
    "Real Madrid": "ريال مدريد", "Barcelona": "برشلونة", "Atlético Madrid": "أتلتيكو مدريد", "Atletico Madrid": "أتلتيكو مدريد",
    "Girona": "جيرونا", "Athletic Bilbao": "أتلتيك بيلباو", "Real Sociedad": "ريال سوسيداد",
    "Real Betis": "ريال بيتيس", "Valencia": "فالنسيا", "Villarreal": "فياريال",
    "Getafe": "خيتافي", "Osasuna": "أوساسونا", "Sevilla": "إشبيلية",
    "Celta Vigo": "سيلتا فيغو", "Celta": "سيلتا فيغو",
    "Rayo Vallecano": "رايو فاليكانو", "Las Palmas": "لاس بالماس",
    "Alavés": "ألافيس", "Alaves": "ألافيس", "Mallorca": "ريال مايوركا", "Levante": "ليفانتي",

    # Italy
    "Inter": "إنتر ميلان", "Inter Milan": "إنتر ميلان",
    "AC Milan": "ميلان", "Milan": "ميلان",
    "Juventus": "يوفنتوس", "Bologna": "بولونيا", "Roma": "روما",
    "Atalanta": "أتالانتا", "Napoli": "نابولي", "Fiorentina": "فيورنتينا",
    "Lazio": "لاتسيو", "Torino": "تورينو",
    "Genoa": "جنوى", "Monza": "مونزا", "Lecce": "ليتشي",
    "Udinese": "أودينيزي", "Sassuolo": "ساسولو", "Pisa": "بيزا",

    # Germany
    "Bayer Leverkusen": "باير ليفركوزن", "VfB Stuttgart": "شتوتغارت", "Stuttgart": "شتوتغارت",
    "Bayern Munich": "بايرن ميونخ", "RB Leipzig": "لايبزيغ", "Borussia Dortmund": "بوروسيا دورتموند",
    "Eintracht Frankfurt": "آينتراخت فرانكفورت", "Werder Bremen": "فيردر بريمن",
    "St. Pauli": "سانت باولي", "Augsburg": "أوغسبورغ",
    "Borussia Mönchengladbach": "بوروسيا مونشنغلادباخ",
    "Monchengladbach": "بوروسيا مونشنغلادباخ", "Mönchengladbach": "بوروسيا مونشنغلادباخ", "Gladbach": "بوروسيا مونشنغلادباخ",

    # France
    "Paris Saint-Germain": "باريس سان جيرمان", "PSG": "باريس سان جيرمان",
    "Paris Saint Germain": "باريس سان جيرمان", "Paris St Germain": "باريس سان جيرمان",
    "AS Monaco": "موناكو", "Monaco": "موناكو", "Marseille": "مارسيليا",
    "Lille": "ليل", "Toulouse": "تولوز", "Lens": "لانس",
    "Brest": "بريست", "Paris FC": "باريس إف سي",
    "Metz": "ميتز", "Nice": "نيس", "Strasbourg": "ستراسبورغ",
    "Le Havre": "لوهافر", "Rennes": "رين", "Lyon": "ليون",
    "Montpellier": "مونبلييه", "Nantes": "نانت", "Reims": "ريمس",
    "Saint-Étienne": "سانت إتيان", "Saint-Etienne": "سانت إتيان",
    "Clermont": "كليرمون", "Lorient": "لوريان", "Angers": "أنجيه",

    # Netherlands
    "PSV Eindhoven": "آيندهوفن", "Feyenoord": "فاينورد", "Ajax": "أياكس",

    # Portugal
    "Sporting CP": "سبورتينغ لشبونة", "Sporting": "سبورتينغ لشبونة",
    "Benfica": "بنفيكا", "Porto": "بورتو", "Braga": "سبورتينغ براغا",

    # Turkey
    "Galatasaray": "غلطة سراي", "Fenerbahçe": "فنربخشة", "Fenerbahce": "فنربخشة",

    # Egypt
    "Al Ahly": "الأهلي", "Zamalek": "الزمالك", "Pyramids FC": "بيراميدز",

    # Brazil & Argentina
    "Flamengo": "فلامنغو", "Palmeiras": "بالميراس", "Boca Juniors": "بوكا جونيورز", "River Plate": "ريفر بليت",
}

TEAM_ALIASES = {
    "Gladbach": "بوروسيا مونشنغلادباخ",
}

# --- ✨ قنوات + تنظيف ✨ ---
CHANNEL_KEYWORDS = [
    # ملاحظة: قنوات beIN نضيفها فقط من yallashoot
    "beIN Sports 1 HD", "beIN Sports 2 HD", "beIN Sports 3 HD",
    "MATCH! Futbol 1", "MATCH! Futbol 2", "MATCH! Futbol 3",
    "Football HD","Sport TV1 Portugal HD", "Sport TV2 Portugal HD",
    "ESPN 1 Brazil", "ESPN 2 Brazil", "ESPN 3 Brazil", "ESPN 4 Brazil", "ESPN 5 Brazil", "ESPN 6 Brazil", "ESPN 7 Brazil",
    "DAZN 1 Portugal HD", "DAZN 2 Portugal HD", "DAZN 3 Portugal HD", "DAZN 4 Portugal HD", "DAZN 5 Portugal HD", "DAZN 6 Portugal HD",
    "MATCH! Premier HD", "Sky Sports Main Event HD", "Sky Sport Premier League HD", "IRIB Varzesh HD",
    "Persiana Sport HD", "MBC Action HD", "TNT Sports 1 HD", "TNT Sports 2 HD", "TNT Sports HD",
    "MBC masrHD", "MBC masr2HD", "ssc1 hd", "ssc2 hd", "Shahid MBC",
]

def clean_channel_name(name: str) -> str:
    if not name: return ""
    name = EMOJI_MISC_RE.sub('', name)
    name = re.sub(r'\s*\((?:Astro|UAE|KSA|QA|OM|BH|KW|.*)?\)\s*', '', name, flags=re.IGNORECASE)
    name = name.replace("$/geo/R", "").replace("$/geo", "")
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def translate_team_or_fallback(name_en: str) -> str:
    name_en = (name_en or "").strip()
    if not name_en: return ""
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

# --- اسم البطولة بالعربي ---
WEEK_PATTERNS = [
    (re.compile(r'week\s*(\d+)', re.IGNORECASE), "الأسبوع {n}"),
    (re.compile(r'matchday\s*(\d+)', re.IGNORECASE), "الجولة {n}"),
    (re.compile(r'round\s*(\d+)', re.IGNORECASE), "الدور {n}"),
]

def arabic_competition_name(competition_en: str) -> str:
    comp = competition_en or ""
    base_ar = None
    for kw in LEAGUE_KEYWORDS:
        if kw.lower() in comp.lower():
            base_ar = TRANSLATION_MAP[kw]
            break
    if not base_ar:
        return comp
    suffix = ""
    for pat, fmt in WEEK_PATTERNS:
        m = pat.search(comp)
        if m:
            suffix = " - " + fmt.format(n=m.group(1))
            break
    return f"{base_ar}{suffix}"

# --- مطابقة yallashoot: صارمة ---
def in_yalla(yalla_map: dict, home_ar: str, away_ar: str):
    k1 = f"{normalize_text(home_ar)}-{normalize_text(away_ar)}"
    k2 = f"{normalize_text(away_ar)}-{normalize_text(home_ar)}"
    if k1 in yalla_map:
        return yalla_map[k1]
    if k2 in yalla_map:
        return yalla_map[k2]
    return None

# ---- NEW: اجمع قنوات yalla (تشمل حقل "channel" المفرد) ----
SPLIT_RE = re.compile(r'\s*(?:,|،|/|\||&| و | and )\s*', re.IGNORECASE)

def to_list_channels(val):
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        if not val.strip():
            return []
        # فك أي فواصل شائعة
        parts = [p.strip() for p in SPLIT_RE.split(val) if p.strip()]
        return parts if parts else [val.strip()]
    return []

def collect_yalla_channels(yalla_match: dict) -> list:
    # نجرب مفاتيح مختلفة شائعة في yalla
    keys_try = [
        "channels_raw", "channels", "tv_channels",
        "channel", "channel_ar", "channel_en",
        "broadcasters", "broadcaster"
    ]
    out = []
    for k in keys_try:
        if k in yalla_match:
            out.extend(to_list_channels(yalla_match.get(k)))
    # إزالة فراغات زائدة وحفظ الترتيب
    out = [c.strip() for c in out if c and c.strip()]
    return unique_preserving(out)

def filter_matches_by_league():
    # --- حمل yallashoot ---
    yallashoot_map = {}
    try:
        response = requests.get(YALLASHOOT_URL, timeout=15)
        response.raise_for_status()
        yallashoot_data = response.json()
        for match in yallashoot_data.get("matches", []):
            home = (match.get("home") or "").strip()
            away = (match.get("away") or "").strip()
            if home and away:
                k = f"{normalize_text(home)}-{normalize_text(away)}"
                yallashoot_map[k] = match
        print(f"Successfully created a map of {len(yallashoot_map)} matches from yallashoot.")
    except requests.exceptions.RequestException as e:
        print(f"WARNING: Could not fetch extra data. Error: {e}")

    # --- اقرأ الإدخال ---
    try:
        with INPUT_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"ERROR: Could not read input file. {e}")
        return

    all_matches = data.get("matches", [])
    if not all_matches:
        return

    filtered_list = []
    for match_data in all_matches:
        competition_en = match_data.get("competition", "") or ""
        if not competition_en or "women" in competition_en.lower():
            continue

        # فلترة البطولات
        is_wanted_league = any(keyword.lower() in competition_en.lower() for keyword in LEAGUE_KEYWORDS)
        if not is_wanted_league:
            continue

        # اسم البطولة بالعربي
        competition_ar = arabic_competition_name(competition_en)

        # فرق (من العنوان)
        title_en = match_data.get("title", "") or ""
        home_en, away_en = parse_title_to_teams(title_en)
        if not home_en or not away_en:
            continue
        home_team = translate_team_or_fallback(home_en)
        away_team = translate_team_or_fallback(away_en)

        # --- الشرط: لازم تكون نفس المباراة موجودة في yallashoot ---
        found = in_yalla(yallashoot_map, home_team, away_team)
        if not found:
            print(f"[SKIP] Not in yallashoot: {home_team} vs {away_team}")
            continue

        # قنوات (غير beIN) من الملف الأول
        original_channels = match_data.get("channels_raw", []) or []
        non_bein_channels = []
        for ch in original_channels:
            ch_str = str(ch or "")
            if is_bein_channel(ch_str):
                continue  # تجاهل beIN من الملف الأول
            ch_l = ch_str.lower()
            for kw in CHANNEL_KEYWORDS:
                if kw.lower() in ch_l:
                    non_bein_channels.append(clean_channel_name(ch_str))
                    break

        # beIN من yallashoot فقط (كما هي)
        bein_from_yalla = []
        yalla_channels = collect_yalla_channels(found)
        for ch in yalla_channels:
            if is_bein_channel(ch):
                bein_from_yalla.append(ch.strip())

        # دمج نهائي
        channels = unique_preserving(non_bein_channels + bein_from_yalla)

        # إضافات قنوات حسب الدوري
        if "السعودي" in competition_ar and not contains_ignore_case(channels, "Thmanyah 1 HD"):
            channels.append("Thmanyah 1 HD")
        if "الإيطالي" in competition_ar and not contains_ignore_case(channels, "STARZPLAY Sports 1"):
            channels.append("STARZPLAY Sports 1")
        # الدوري الفرنسي: ضمّن beIN SPORTS 4 HD دائمًا
        if "الدوري الفرنسي" in competition_ar and not contains_ignore_case(channels, "beIN SPORTS 4 HD"):
            channels.append("beIN SPORTS 4 HD")

        new_match_entry = {
            "competition": competition_ar,
            "kickoff_baghdad": match_data.get("kickoff_baghdad"),
            "home_team": home_team,
            "away_team": away_team,
            "channels_raw": channels,
            "home_logo": None,
            "away_logo": None,
            "status_text": None,
            "result_text": None,
        }

        # نكمّل النواقص فقط من yallashoot
        safe_update(
            new_match_entry,
            found,
            fields=["home_logo", "away_logo", "status_text", "result_text"],
            overwrite=False
        )

        filtered_list.append(new_match_entry)

    output_data = {
        "date": data.get("date"),
        "source_url": data.get("source_url"),
        "matches": filtered_list
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print("Process complete. (Strict intersection with yallashoot; beIN from yalla only; Ligue 1 adds beIN SPORTS 4 HD)")

if __name__ == "__main__":
    filter_matches_by_league()

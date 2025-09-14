# scripts/filter_json.py
import json
import re
import unicodedata
from pathlib import Path
import requests
from difflib import SequenceMatcher
from googletrans import Translator

# --- الإعدادات الأساسية ---
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"
YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"

# --- أدوات مساعدة للتنظيف ---
AR_LETTERS_RE = re.compile(r'[\u0600-\u06FF]')
EMOJI_MISC_RE = re.compile(r'[\u2600-\u27BF\U0001F300-\U0001FAFF]+')

def strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

def normalize_text(text):
    if not text:
        return ""
    text = str(text)
    text = EMOJI_MISC_RE.sub('', text)                 # شيل إيموجي ورموز
    text = re.sub(r'\(.*?\)', '', text)                # شيل الأقواس
    text = strip_accents(text)                         # شيل الأكسنتس (ö->o)
    text = text.lower()
    text = text.replace("&", "and")
    text = re.sub(r'\bfc\b|\bsc\b|\bcf\b', '', text)   # شيل لاحقات شائعة
    text = text.replace(" ", "").replace("-", "").replace("_", "")
    text = text.replace("ال", "")                      # مساعد للمطابقة العربية
    text = re.sub(r'[^a-z0-9\u0600-\u06FF]', '', text) # حروف وأرقام فقط
    return text.strip()

def is_arabic(s: str) -> bool:
    return bool(AR_LETTERS_RE.search(s or ""))

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

# --- ✨ قاموس الفرق النهائي (مثبت + توسعة) ✨ ---
TEAM_NAME_MAP = {
    # Saudi Arabia (مع بدائل كتابة)
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
    "Neom": "نيوم", "Al Kholood": "الخلود", "Al-Kholood": "الخلود",

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
    "Monchengladbach": "بوروسيا مونشنغلادباخ", "Mönchengladbach": "بوروسيا مونشنغلادباخ",

    # France
    "Paris Saint-Germain": "باريس سان جيرمان", "PSG": "باريس سان جيرمان",
    "AS Monaco": "موناكو", "Monaco": "موناكو", "Marseille": "مارسيليا",

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

# بدائل قصيرة إضافية للمطابقة
TEAM_ALIASES = {
    "Gladbach": "بوروسيا مونشنغلادباخ",
}

# --- ✨ قائمة القنوات (الكلمات المفتاحية) + تنظيف العرض ✨ ---
CHANNEL_KEYWORDS = [
    "beIN Sports 1 HD", "beIN Sports 2 HD", "beIN Sports 3 HD", "MATCH! Futbol 1", "MATCH! Futbol 2",
    "MATCH! Futbol 3", "Football HD (tjk)", "Sport TV1 Portugal HD", "Sport TV2 Portugal HD",
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

# --- ترجمة آمنة (مع سقوط آمن) ---
def translate_text_safe(text_en, translator, cache, manual_map):
    text_en = (text_en or "").strip()
    if not text_en:
        return ""
    # محاولة مطابقة القاموس (مع aliases)
    for k, v in {**manual_map, **TEAM_ALIASES}.items():
        if normalize_text(k) == normalize_text(text_en):
            return v

    if text_en not in cache:
        try:
            res = translator.translate(text_en, dest='ar')
            cache[text_en] = res.text
        except Exception:
            cache[text_en] = text_en  # سقوط آمن
    out = cache[text_en]
    # لو الترجمة ليست عربية (أو ترجمة غير منطقية)، رجّع الأصل
    if not is_arabic(out):
        return text_en
    return out

def parse_and_translate_title(title, translator, cache):
    parts = re.split(r'\s+v(?:s)?\.?\s+', title or "", flags=re.IGNORECASE)
    if len(parts) == 2:
        home_en, away_en = parts[0].strip(), parts[1].strip()
        # أولوية القواميس اليدوية
        home_ar = translate_text_safe(home_en, translator, cache, TEAM_NAME_MAP)
        away_ar = translate_text_safe(away_en, translator, cache, TEAM_NAME_MAP)
        return home_ar, away_ar
    # لو ما قدر يفصل بفاصلة vs
    single = translate_text_safe(title or "", translator, cache, TEAM_NAME_MAP)
    return single, None

# --- بناء اسم بطولة عربي نظيف من competition_en ---
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
        return comp  # رجّع كما هو إذا مو ضمن القوائم

    suffix = ""
    for pat, fmt in WEEK_PATTERNS:
        m = pat.search(comp)
        if m:
            suffix = " - " + fmt.format(n=m.group(1))
            break
    return f"{base_ar}{suffix}"

# --- مطابقة yallashoot مع تقارب بسيط ---
def best_lookup(yalla_map, key1: str, key2: str):
    # محاولة مباشرة
    if key1 in yalla_map:
        return yalla_map[key1]
    if key2 in yalla_map:
        return yalla_map[key2]
    # تقارب بالـ difflib
    best_key, best_score = None, 0.0
    for k in yalla_map.keys():
        s = max(SequenceMatcher(None, key1, k).ratio(),
                SequenceMatcher(None, key2, k).ratio())
        if s > best_score:
            best_score, best_key = s, k
    if best_score >= 0.75 and best_key:
        return yalla_map.get(best_key)
    return None

def filter_matches_by_league():
    translator = Translator()
    translation_cache = {}

    # --- تحميل yallashoot ---
    yallashoot_map = {}
    yalla_keys_debug = []
    try:
        response = requests.get(YALLASHOOT_URL, timeout=15)
        response.raise_for_status()
        yallashoot_data = response.json()
        for match in yallashoot_data.get("matches", []):
            home = match.get("home", "").strip()
            away = match.get("away", "").strip()
            if home and away:
                k = f"{normalize_text(home)}-{normalize_text(away)}"
                yallashoot_map[k] = match
                yalla_keys_debug.append(k)
        print(f"Successfully created a map of {len(yallashoot_map)} matches from yallashoot.")
    except requests.exceptions.RequestException as e:
        print(f"WARNING: Could not fetch extra data. Error: {e}")

    # --- قراءة الإدخال ---
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

        # قبول الدوري إذا يحتوي أي كلمة مفتاح
        is_wanted_league = any(keyword.lower() in competition_en.lower() for keyword in LEAGUE_KEYWORDS)
        if not is_wanted_league:
            continue

        # قنوات: فلترة + تنظيف العرض + إزالة التكرار
        original_channels = match_data.get("channels_raw", []) or []
        filtered_channels = []
        for ch in original_channels:
            for kw in CHANNEL_KEYWORDS:
                if kw.lower() in (ch or "").lower():
                    clean = clean_channel_name(ch)
                    filtered_channels.append(clean)
                    break
        filtered_channels = list(dict.fromkeys(filtered_channels))  # unique مع الحفاظ على الترتيب

        if not filtered_channels:
            # إذا ما لقى ولا قناة من قائمتك، تجاهل؟
            # أو خليه يكمل؟ نخليه يكمل لأنك ترغب بالمباريات المهمة ولو بقناة قليلة
            pass

        try:
            # بطولة عربية نظيفة
            competition_ar = arabic_competition_name(competition_en)

            # ترجمة/تحويل عناوين الفرق
            title_en = match_data.get("title", "") or ""
            home_team_ar, away_team_ar = parse_and_translate_title(title_en, translator, translation_cache)

            # إضافات قنوات بحسب الدوري
            if "السعودي" in competition_ar and "Thmanyah 1 HD" not in filtered_channels:
                filtered_channels.append("Thmanyah 1 HD")
            if "الإيطالي" in competition_ar and "STARZPLAY Sports 1" not in filtered_channels:
                filtered_channels.append("STARZPLAY Sports 1")

            # بناء الإدخال الجديد
            new_match_entry = {
                "competition": competition_ar,
                "kickoff_baghdad": match_data.get("kickoff_baghdad"),
                "home_team": home_team_ar,
                "away_team": away_team_ar,
                "channels_raw": sorted(list(dict.fromkeys(filtered_channels))),
                "home_logo": None,
                "away_logo": None,
                "status_text": None,
                "result_text": None,
            }

            # محاولة إكمال الشعارات/الحالة من yallashoot
            if home_team_ar and away_team_ar:
                key1 = f"{normalize_text(home_team_ar)}-{normalize_text(away_team_ar)}"
                key2 = f"{normalize_text(away_team_ar)}-{normalize_text(home_team_ar)}"
                found = best_lookup(yallashoot_map, key1, key2)
                if found:
                    new_match_entry.update({
                        "home_logo": found.get("home_logo"),
                        "away_logo": found.get("away_logo"),
                        "status_text": found.get("status_text"),
                        "result_text": found.get("result_text"),
                    })
                else:
                    print("\n" + "="*20)
                    print(f"[DEBUG] Match not found for: {home_team_ar} vs {away_team_ar}")
                    print(f"  - Generated Keys: '{key1}' OR '{key2}'")
                    similar_keys = [key for key in yalla_keys_debug
                                    if normalize_text(home_team_ar) in key or normalize_text(away_team_ar) in key]
                    if similar_keys:
                        print(f"  - Did you mean one of: {similar_keys[:5]}")
                    print("="*20 + "\n")

            filtered_list.append(new_match_entry)

        except Exception as e:
            print(f"Warning: Could not process match '{match_data.get('title')}'. Error: {e}")

    output_data = {
        "date": data.get("date"),
        "source_url": data.get("source_url"),
        "matches": filtered_list
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"Process complete. Kept and processed {len(filtered_list)} matches.")

if __name__ == "__main__":
    filter_matches_by_league()

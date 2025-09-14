# scripts/filter_json.py
import json
import re
from pathlib import Path
from googletrans import Translator

# --- الإعدادات الأساسية ---
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"


# --- ✨ القاموس اليدوي لترجمة نظيفة للدوريات ✨ ---
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
    "Saudi Professional League": "دوري المحترفين السعودي",
}
LEAGUE_KEYWORDS = list(TRANSLATION_MAP.keys())


# --- ✨ قاموس الفرق الموسع (أوروبا والسعودية) ✨ ---
TEAM_NAME_MAP = {
    # Saudi Pro League
    "Al-Hilal": "الهلال", "Al-Nassr": "النصر", "Al-Ittihad": "الاتحاد", "Al-Ahli": "الأهلي",
    "Al-Shabab": "الشباب", "Al-Ettifaq": "الاتفاق", "Al-Taawoun": "التعاون", "Damac": "ضمك",
    "Al-Fateh": "الفتح", "Al-Raed": "الرائد", "Al-Khaleej": "الخليج", "Abha": "أبها",
    "Al-Fayha": "الفيحاء", "Al-Wehda": "الوحدة", "Al-Okhdood": "الأخدود", "Al-Hazem": "الحزم",
    "Al-Riyadh": "الرياض", "Al Qadsiah": "القادسية", "Neom": "نيوم", "Al Kholood": "الخلود",
    # Premier League
    "Manchester City": "مانشستر سيتي", "Arsenal": "أرسنال", "Manchester United": "مانشستر يونايتد",
    "Newcastle United": "نيوكاسل يونايتد", "Liverpool": "ليفربول", "Brighton & Hove Albion": "برايتون",
    "Aston Villa": "أستون فيلا", "Tottenham Hotspur": "توتنهام هوتسبير", "Brentford": "برينتفورد",
    "Fulham": "فولام", "Crystal Palace": "كريستال بالاس", "Chelsea": "تشيلسي",
    "Wolverhampton Wanderers": "ولفرهامبتون", "West Ham United": "وست هام يونايتد",
    "Bournemouth": "بورنموث", "Nottingham Forest": "نوتنغهام فورست", "Everton": "إيفرتون",
    "Leicester City": "ليستر سيتي", "Ipswich Town": "إيبسويتش تاون", "Southampton": "ساوثهامبتون",
    # La Liga
    "Barcelona": "برشلونة", "Real Madrid": "ريال مدريد", "Atlético Madrid": "أتلتيكو مدريد",
    "Real Sociedad": "ريال سوسيداد", "Villarreal": "فياريال", "Real Betis": "ريال بيتيس",
    "Athletic Bilbao": "أتلتيك بيلباو", "Osasuna": "أوساسونا", "Girona": "جيرونا",
    "Rayo Vallecano": "رايو فاليكانو", "Sevilla": "إشبيلية", "Mallorca": "ريال مايوركا",
    "Celta Vigo": "سيلتا فيغو", "Valencia": "فالنسيا", "Getafe": "خيتافي", "Las Palmas": "لاس بالماس",
    "Leganés": "ليغانيس", "Real Valladolid": "بلد الوليد",
    # Serie A
    "Napoli": "نابولي", "Lazio": "لاتسيو", "Inter": "إنتر ميلان", "AC Milan": "ميلان",
    "Atalanta": "أتالانتا", "Roma": "روما", "Juventus": "يوفنتوس", "Fiorentina": "فيورنتينا",
    "Bologna": "بولونيا", "Torino": "تورينو", "Monza": "مونزا", "Udinese": "أودينيزي",
    "Sassuolo": "ساسوولو", "Empoli": "إمبولي", "Lecce": "ليتشي", "Parma": "بارما", "Como": "كومو", "Venezia": "فينيسيا",
    # Bundesliga
    "Bayern Munich": "بايرن ميونخ", "Borussia Dortmund": "بوروسيا دورتموند", "RB Leipzig": "لايبزيغ",
    "Bayer Leverkusen": "باير ليفركوزن", "Eintracht Frankfurt": "آينتراخت فرانكفورت",
    "VfB Stuttgart": "شتوتغارت", "FC St. Pauli": "سانت باولي", "Holstein Kiel": "هولشتاين كيل",
    # Ligue 1
    "Paris Saint-Germain": "باريس سان جيرمان", "Lens": "لانس", "Marseille": "مارسيليا",
    "AS Monaco": "موناكو", "Lille": "ليل", "Lyon": "ليون",
}

CHANNEL_KEYWORDS = [
    "beIN Sports 1 HD", "beIN Sports 2 HD", "beIN Sports 3 HD", "MATCH! Futbol 1", "MATCH! Futbol 2",
    "MATCH! Futbol 3", "Football HD (tjk)", "Sport TV1 Portugal HD", "Sport TV2 Portugal HD",
    "ESPN 1 Brazil", "ESPN 2 Brazil", "ESPN 3 Brazil", "ESPN 4 Brazil", "ESPN 5 Brazil", "ESPN 6 Brazil", "ESPN 7 Brazil",
    "DAZN 1 Portugal HD", "DAZN 2 Portugal HD", "DAZN 3 Portugal HD", "DAZN 4 Portugal HD", "DAZN 5 Portugal HD", "DAZN 6 Portugal HD",
    "MATCH! Premier HD", "Sky Sports Main Event HD", "Sky Sport Premier League HD", "IRIB Varzesh HD",
    "Persiana Sport HD", "MBC Action HD", "TNT Sports 1 HD", "TNT Sports 2 HD", "TNT Sports HD",
    "MBC masrHD", "MBC masr2HD", "ssc1 hd", "ssc2 hd", "Shahid MBC",
]


def translate_text(text, translator, cache, manual_map):
    text_stripped = text.strip()
    # البحث أولاً في القاموس اليدوي عن تطابق كامل أو جزئي
    for key, value in manual_map.items():
        if key.lower() in text_stripped.lower():
            return value
    # إذا لم يوجد، استخدم الترجمة الآلية مع الكاش
    if text_stripped not in cache:
        cache[text_stripped] = translator.translate(text_stripped, dest='ar').text
    return cache[text_stripped]

def parse_and_translate_title(title, translator, cache, team_map):
    teams_en = re.split(r'\s+v(?:s)?\s+', title, flags=re.IGNORECASE)
    if len(teams_en) == 2:
        home_team_en, away_team_en = teams_en[0].strip(), teams_en[1].strip()
        home_team_ar = translate_text(home_team_en, translator, cache, team_map)
        away_team_ar = translate_text(away_team_en, translator, cache, team_map)
        return home_team_ar, away_team_ar
    else:
        return translate_text(title, translator, cache, {}), None

def filter_matches_by_league():
    translator = Translator()
    translation_cache = {}
    try:
        with INPUT_PATH.open("r", encoding="utf-8") as f: data = json.load(f)
    except Exception as e:
        print(f"ERROR: Could not read input file. {e}")
        return
    all_matches = data.get("matches", [])
    if not all_matches: return
    
    filtered_list = []
    for match_data in all_matches:
        competition_en = match_data.get("competition", "")
        if not competition_en or "women" in competition_en.lower(): continue
        
        is_wanted_league = any(keyword.lower() in competition_en.lower() for keyword in LEAGUE_KEYWORDS)
        if not is_wanted_league: continue

        original_channels = match_data.get("channels_raw", [])
        filtered_channels = list(dict.fromkeys([ch for ch in original_channels for kw in CHANNEL_KEYWORDS if kw.lower() in ch.lower()]))
        
        if filtered_channels:
            try:
                competition_ar = translate_text(competition_en, translator, translation_cache, TRANSLATION_MAP)
                title_en = match_data.get("title", "")
                home_team_ar, away_team_ar = parse_and_translate_title(title_en, translator, translation_cache, TEAM_NAME_MAP)

                # ✨ الإضافة الجديدة: إضافة قنوات ثابتة حسب الدوري ✨
                if "سعودي" in competition_ar and "Thmanyah 1 HD" not in filtered_channels:
                    filtered_channels.append("Thmanyah 1 HD")
                if "الإيطالي" in competition_ar and "STARZPLAY Sports 1" not in filtered_channels:
                    filtered_channels.append("STARZPLAY Sports 1")

                new_match_entry = {
                    "competition": competition_ar,
                    "kickoff_baghdad": match_data.get("kickoff_baghdad"),
                    "home_team": home_team_ar,
                    "away_team": away_team_ar,
                    "channels_raw": sorted(filtered_channels) # ترتيب القنوات أبجديًا
                }
                filtered_list.append(new_match_entry)

            except Exception as e:
                print(f"Warning: Could not process match '{match_data.get('title')}'. Error: {e}")
    
    output_data = { "date": data.get("date"), "source_url": data.get("source_url"), "matches": filtered_list }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"Process complete. Kept and processed {len(filtered_list)} matches.")

if __name__ == "__main__":
    filter_matches_by_league()

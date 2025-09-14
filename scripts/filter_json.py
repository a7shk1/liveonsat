# scripts/filter_json.py
import json
import re
from pathlib import Path
import requests  # <-- استيراد المكتبة الجديدة
from googletrans import Translator

# --- الإعدادات الأساسية ---
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"
YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"


# --- القواميس اليدوية للترجمة والفلترة ---
TRANSLATION_MAP = {
    "English Premier League": "الدوري الإنجليزي الممتاز", "Spanish La Liga (Primera)": "الدوري الإسباني",
    "Italian Serie A": "الدوري الإيطالي", "German 1. Bundesliga": "الدوري الألماني", "French Ligue 1": "الدوري الفرنسي",
    # ... باقي الدوريات والكؤوس
    "Champions League": "دوري أبطال أوروبا", "Saudi Professional League": "دوري المحترفين السعودي",
}
LEAGUE_KEYWORDS = list(TRANSLATION_MAP.keys())

TEAM_NAME_MAP = {
    # Saudi Pro League
    "Al-Hilal": "الهلال", "Al-Nassr": "النصر", "Al-Ittihad": "الاتحاد", "Al-Ahli": "الأهلي",
    "Al-Shabab": "الشباب", "Al-Ettifaq": "الاتفاق", "Al-Taawoun": "التعاون", "Damac": "ضمك",
    "Al-Fateh": "الفتح", "Al-Raed": "الرائد", "Al-Khaleej": "الخليج", "Abha": "أبها",
    "Al-Fayha": "الفيحاء", "Al-Wehda": "الوحدة", "Al-Okhdood": "الأخدود", "Al-Hazem": "الحزم",
    "Al-Riyadh": "الرياض", "Al Qadsiah": "القادسية", "Neom": "نيوم", "Al Kholood": "الخلود",
    # European Leagues
    "Barcelona": "برشلونة", "Real Madrid": "ريال مدريد", "Liverpool": "ليفربول", "Manchester City": "مانشستر سيتي",
    "Manchester United": "مانشستر يونايتد", "Arsenal": "أرسنال", "Chelsea": "تشيلسي", "AC Milan": "ميلان", "Inter": "إنتر ميلان",
    "Juventus": "يوفنتوس", "Roma": "روما", "Bayern Munich": "بايرن ميونخ", "Borussia Dortmund": "بوروسيا دورتموند",
    "Paris Saint-Germain": "باريس سان جيرمان", "Osasuna": "أوساسونا", "Torino": "تورينو"
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
    for key, value in manual_map.items():
        if key.lower() in text_stripped.lower():
            return value
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

    # --- ✨ الخطوة 1: جلب بيانات yallashoot وإنشاء خريطة بحث سريعة ✨ ---
    yallashoot_map = {}
    try:
        print(f"Fetching extra data from: {YALLASHOOT_URL}")
        response = requests.get(YALLASHOOT_URL, timeout=10)
        response.raise_for_status()
        yallashoot_data = response.json()
        for match in yallashoot_data.get("matches", []):
            home = match.get("home_team_ar", "").strip()
            away = match.get("away_team_ar", "").strip()
            if home and away:
                match_key = f"{home}-{away}"
                yallashoot_map[match_key] = match
        print(f"Successfully created a map of {len(yallashoot_map)} matches from yallashoot.")
    except requests.exceptions.RequestException as e:
        print(f"🟡 WARNING: Could not fetch data from yallashoot URL. Extra data will be missing. Error: {e}")

    try:
        with INPUT_PATH.open("r", encoding="utf-8") as f: data = json.load(f)
    except Exception as e:
        print(f"❌ ERROR: Could not read input file. {e}")
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

                if "سعودي" in competition_ar: filtered_channels.append("Thmanyah 1 HD")
                if "الإيطالي" in competition_ar: filtered_channels.append("STARZPLAY Sports 1")

                new_match_entry = {
                    "competition": competition_ar,
                    "kickoff_baghdad": match_data.get("kickoff_baghdad"),
                    "home_team": home_team_ar,
                    "away_team": away_team_ar,
                    "channels_raw": sorted(list(dict.fromkeys(filtered_channels))),
                    # --- ✨ الخطوة 2: البحث عن البيانات الإضافية وإضافتها ✨ ---
                    "home_logo": None,
                    "away_logo": None,
                    "status_text": None,
                    "result_text": None,
                }
                
                if home_team_ar and away_team_ar:
                    lookup_key = f"{home_team_ar}-{away_team_ar}"
                    found_match = yallashoot_map.get(lookup_key)
                    if found_match:
                        new_match_entry["home_logo"] = found_match.get("home_logo")
                        new_match_entry["away_logo"] = found_match.get("away_logo")
                        new_match_entry["status_text"] = found_match.get("status_text")
                        new_match_entry["result_text"] = found_match.get("result_text")

                filtered_list.append(new_match_entry)

            except Exception as e:
                print(f"Warning: Could not process match '{match_data.get('title')}'. Error: {e}")
    
    output_data = { "date": data.get("date"), "source_url": data.get("source_url"), "matches": filtered_list }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"Process complete. Kept and processed {len(filtered_list)} matches.")

if __name__ == "__main__":
    filter_matches_by_league()

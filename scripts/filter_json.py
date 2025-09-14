import json
import re
from pathlib import Path
from googletrans import Translator

REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"

TRANSLATION_MAP = {
    "English Premier League": "الدوري الإنجليزي الممتاز",
    "Spanish La Liga (Primera)": "الدوري الإسباني",
    "Italian Serie A": "الدوري الإيطالي",
    "German 1. Bundesliga": "الدوري الألماني",
    "French Ligue 1": "الدوري الفرنسي",
    "English League Cup": "كأس الرابطة الإنجليزية",
    "Carabao Cup": "كأس كاراباو",
    "EFL Cup": "كأس الرابطة الإنجليزية",
    "Community Shield": "الدرع الخيرية الإنجليزية",
    "Copa del Rey": "كأس ملك إسبانيا",
    "Supercopa": "كأس السوبر الإسباني",
    "Italian Cup (Coppa Italia)": "كأس إيطاليا",
    "Supercoppa Italiana": "كأس السوبر الإيطالي",
    "DFB-Pokal": "كأس ألمانيا",
    "DFL-Supercup": "كأس السوبر الألماني",
    "Coupe de France": "كأس فرنسا",
    "Trophée des Champions": "كأس الأبطال الفرنسي",
    "Champions League": "دوري أبطال أوروبا",
    "Europa League": "الدوري الأوروبي",
    "Conference League": "دوري المؤتمر الأوروبي",
    "Club World Cup": "كأس العالم للأندية",
    "World Cup": "كأس العالم",
    "WC Qualifier": "تصفيات كأس العالم",
    "UEFA Euro": "بطولة أمم أوروبا (اليورو)",
    "Copa America": "كوبا أمريكا",
    "Africa Cup of Nations": "كأس الأمم الأفريقية",
    "AFCON": "كأس الأمم الأفريقية",
    "AFC Asian Cup": "كأس آسيا",
    "Nations League": "دوري الأمم",
    "Arab Cup": "كأس العرب",
    "Saudi Professional League": "دوري المحترفين السعودي",
}
LEAGUE_KEYWORDS = list(TRANSLATION_MAP.keys())

CHANNEL_KEYWORDS = [
    "beIN Sports 1 HD", "beIN Sports 2 HD", "beIN Sports 3 HD", "MATCH! Futbol 1", "MATCH! Futbol 2",
    "MATCH! Futbol 3", "Football HD (tjk)", "Sport TV1 Portugal HD", "Sport TV2 Portugal HD",
    "ESPN 1 Brazil", "ESPN 2 Brazil", "ESPN 3 Brazil", "ESPN 4 Brazil", "ESPN 5 Brazil", "ESPN 6 Brazil", "ESPN 7 Brazil",
    "DAZN 1 Portugal HD", "DAZN 2 Portugal HD", "DAZN 3 Portugal HD", "DAZN 4 Portugal HD", "DAZN 5 Portugal HD", "DAZN 6 Portugal HD",
    "MATCH! Premier HD", "Sky Sports Main Event HD", "Sky Sport Premier League HD", "IRIB Varzesh HD",
    "Persiana Sport HD", "MBC Action HD", "TNT Sports 1 HD", "TNT Sports 2 HD", "TNT Sports HD",
    "MBC masrHD", "MBC masr2HD", "ssc1 hd", "ssc2 hd", "Shahid MBC",
]

def translate_with_map_fallback(text, translator, cache, t_map):
    for key, value in t_map.items():
        if key.lower() in text.lower():
            return value
    if text not in cache:
        cache[text] = translator.translate(text, dest='ar').text
    return cache[text]

def parse_and_translate_title(title, translator, cache):
    teams = re.split(r'\s+v(?:s)?\s+', title, flags=re.IGNORECASE)
    if len(teams) == 2:
        home_team, away_team = teams
        if home_team not in cache:
            cache[home_team] = translator.translate(home_team.strip(), dest='ar').text
        if away_team not in cache:
            cache[away_team] = translator.translate(away_team.strip(), dest='ar').text
        return cache[home_team], cache[away_team]
    else:
        if title not in cache:
            cache[title] = translator.translate(title, dest='ar').text
        return cache[title], None

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
        
        for keyword in LEAGUE_KEYWORDS:
            if keyword.lower() in competition_en.lower():
                original_channels = match_data.get("channels_raw", [])
                filtered_channels = list(dict.fromkeys([ch for ch in original_channels for kw in CHANNEL_KEYWORDS if kw.lower() in ch.lower()]))
                
                if filtered_channels:
                    try:
                        competition_ar = translate_with_map_fallback(competition_en, translator, translation_cache, TRANSLATION_MAP)
                        title_en = match_data.get("title", "")
                        home_team_ar, away_team_ar = parse_and_translate_title(title_en, translator, translation_cache)

                        new_match_entry = {
                            "competition": competition_ar,
                            "kickoff_baghdad": match_data.get("kickoff_baghdad"),
                            "home_team": home_team_ar,
                            "away_team": away_team_ar,
                            "channels_raw": filtered_channels
                        }
                        filtered_list.append(new_match_entry)

                    except Exception as e:
                        print(f"Warning: Could not process match '{match_data.get('title')}'. Error: {e}")
                break
    
    output_data = { "date": data.get("date"), "source_url": data.get("source_url"), "matches": filtered_list }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"Process complete. Kept and processed {len(filtered_list)} matches.")

if __name__ == "__main__":
    filter_matches_by_league()

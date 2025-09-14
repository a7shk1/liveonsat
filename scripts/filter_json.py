# scripts/filter_json.py
import json
from pathlib import Path
from googletrans import Translator

# --- الإعدادات الأساسية ---
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"


# --- ✨ القائمة السحرية 1: فلترة الدوريات ✨ ---
LEAGUE_KEYWORDS = [
    "English Premier League", "Spanish La Liga (Primera)", "Italian Serie A",
    "German 1. Bundesliga", "French Ligue 1", "English League Cup", "Carabao Cup",
    "EFL Cup", "Community Shield", "Copa del Rey", "Supercopa", "Italian Cup (Coppa Italia)",
    "Supercoppa Italiana", "DFB-Pokal", "DFL-Supercup", "Coupe de France",
    "Trophée des Champions", "Champions League", "Europa League", "Conference League",
    "Club World Cup", "World Cup", "WC Qualifier", "UEFA Euro", "Copa America",
    "Africa Cup of Nations", "AFCON", "AFC Asian Cup", "Nations League", "Arab Cup",
    "Saudi Professional League",
]


# --- ✨ القائمة السحرية 2: قائمة القنوات الحرفية (تم تحديثها حسب طلبك) ✨ ---
CHANNEL_KEYWORDS = [
    "beIN Sports 1 HD",
    "beIN Sports 2 HD",
    "beIN Sports 3 HD",
    "MATCH! Futbol 1",
    "MATCH! Futbol 2",
    "MATCH! Futbol 3",
    "Football HD (tjk)",
    "Sport TV1 Portugal HD",
    "Sport TV2 Portugal HD",
    "ESPN 1 Brazil",
    "ESPN 2 Brazil",
    "ESPN 3 Brazil",
    "ESPN 4 Brazil",
    "ESPN 5 Brazil",
    "ESPN 6 Brazil",
    "ESPN 7 Brazil",
    "DAZN 1 Portugal HD",
    "DAZN 2 Portugal HD",
    "DAZN 3 Portugal HD",
    "DAZN 4 Portugal HD",
    "DAZN 5 Portugal HD",
    "DAZN 6 Portugal HD",
    "MATCH! Premier HD",
    "Sky Sports Main Event HD",
    "Sky Sport Premier League HD",
    "IRIB Varzesh HD",
    "Persiana Sport HD",
    "MBC Action HD",
    "TNT Sports 1 HD",
    "TNT Sports 2 HD",
    "TNT Sports HD",
    "MBC masrHD",
    "MBC masr2HD",
    "ssc1 hd",
    "ssc2 hd",
    "Shahid MBC",
]


def filter_matches_by_league():
    print("--- Starting Match Filtering Process ---")
    
    translator = Translator()
    translation_cache = {}

    try:
        with INPUT_PATH.open("r", encoding="utf-8") as f: data = json.load(f)
    except Exception as e:
        print(f"❌ ERROR: Could not read input file. {e}")
        return

    all_matches = data.get("matches", [])
    if not all_matches:
        print("🟡 WARNING: No matches to filter.")
        return
        
    print(f"Found {len(all_matches)} total matches to process.")

    filtered_list = []
    print("\nFiltering and Translating matches...")

    for match in all_matches:
        competition = match.get("competition", "")
        if not competition or "women" in competition.lower():
            continue

        for keyword in LEAGUE_KEYWORDS:
            if keyword.lower() in competition.lower():
                original_channels = match.get("channels_raw", [])
                filtered_channels = []
                for channel in original_channels:
                    for ch_keyword in CHANNEL_KEYWORDS:
                        if ch_keyword.lower() in channel.lower():
                            filtered_channels.append(channel)
                            break
                
                if filtered_channels:
                    match["channels_raw"] = filtered_channels
                    
                    # --- ✨ الترجمة محصورة هنا فقط ✨ ---
                    try:
                        # 1. ترجمة اسم البطولة
                        if competition not in translation_cache:
                            translated_comp = translator.translate(competition, dest='ar').text
                            translation_cache[competition] = translated_comp
                        match['competition'] = translation_cache[competition]

                        # 2. ترجمة عنوان المباراة
                        title = match.get("title", "")
                        if title:
                            match['title'] = translator.translate(title, dest='ar').text
                            
                        # (تمت إزالة كود ترجمة القنوات)
                            
                    except Exception as e:
                        print(f"⚠️ Warning: Could not translate '{match.get('title')}'. Using original text. Error: {e}")

                    filtered_list.append(match)
                break 
    
    print(f"\n✅ Process complete. Kept and translated {len(filtered_list)} matches.")

    output_data = { "date": data.get("date"), "source_url": data.get("source_url"), "matches": filtered_list }

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"✔️ Successfully saved final data to: {OUTPUT_PATH}")
    print("--- Process Finished ---")


if __name__ == "__main__":
    filter_matches_by_league()

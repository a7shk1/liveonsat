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
    "Copa del Rey": "كأس ملك إسبانيا", "Champions League": "دوري أبطال أوروبا", "Europa League": "الدوري الأوروبي",
    "Saudi Professional League": "دوري المحترفين السعودي", "World Cup": "كأس العالم",
    # يمكنك إضافة المزيد من الدوريات هنا بنفس الطريقة
}
LEAGUE_KEYWORDS = list(TRANSLATION_MAP.keys())


# --- ✨ القاموس الخاص لترجمة أسماء الفرق بدقة (يمكنك التعديل والإضافة هنا) ✨ ---
TEAM_NAME_MAP = {
    # الدوري الإسباني
    "Osasuna": "أوساسونا",
    "Celta Vigo": "سيلتا فيغو",
    "Girona": "جيرونا",
    "Levante": "ليفانتي",
    "Real Betis": "ريال بيتيس",
    "Rayo Vallecano": "رايو فاليكانو",
    "Barcelona": "برشلونة",
    "Valencia": "فالنسيا",
    "Real Madrid": "ريال مدريد",
    "Atlético Madrid": "أتلتيكو مدريد",

    # الدوري الإيطالي
    "Roma": "روما",
    "Torino": "تورينو",
    "Atalanta": "أتالانتا",
    "Lecce": "ليتشي",
    "Sassuolo": "ساسوولو",
    "Lazio": "لاتسيو",
    "AC Milan": "ميلان",
    "Bologna": "بولونيا",
    "Inter": "إنتر ميلان",
    "Juventus": "يوفنتوس",

    # الدوري الإنجليزي
    "Burnley": "بيرنلي",
    "Liverpool": "ليفربول",
    "Manchester City": "مانشستر سيتي",
    "Manchester United": "مانشستر يونايتد",
    "Chelsea": "تشيلسي",
    "Arsenal": "أرسنال",

    # الدوري الألماني
    "St. Pauli": "سانت باولي",
    "Augsburg": "أوغسبورغ",
    "Mönchengladbach": "بوروسيا مونشنغلادباخ",
    "Werder Bremen": "فيردر بريمن",
    "Bayern Munich": "بايرن ميونخ",
    "Borussia Dortmund": "بوروسيا دورتموند",

    # الدوري السعودي
    "Al Raed": "الرائد",
    "Al Najma": "النجمة",
    "Damac": "ضمك",
    "Neom": "نيوم",
    "Al Nassr": "النصر",
    "Al Khaleej": "الخليج", # تصحيح لـ "Kholood" أو "Khaleej"
    "Al Hilal": "الهلال",
    "Al Ittihad": "الاتحاد",
    "Al Ahli": "الأهلي",
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
    # البحث أولاً في القاموس اليدوي (للدوريات أو الفرق)
    for key, value in manual_map.items():
        if key.lower() in text.lower():
            return value
            
    # إذا لم يوجد، استخدم الترجمة الآلية مع الكاش
    if text not in cache:
        cache[text] = translator.translate(text, dest='ar').text
    return cache[text]

def parse_and_translate_title(title, translator, cache, team_map):
    teams_en = re.split(r'\s+v(?:s)?\s+', title, flags=re.IGNORECASE)
    if len(teams_en) == 2:
        home_team_en, away_team_en = teams_en[0].strip(), teams_en[1].strip()
        # ترجمة كل فريق باستخدام القاموس اليدوي أولاً
        home_team_ar = translate_text(home_team_en, translator, cache, team_map)
        away_team_ar = translate_text(away_team_en, translator, cache, team_map)
        return home_team_ar, away_team_ar
    else:
        # إذا فشل الفصل، نترجم العنوان كاملاً
        return translate_text(title, translator, cache, {}), None # نمرر قاموس فارغ لأنه ليس اسم فريق

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
        
        # تحقق من الدوريات المطلوبة
        is_wanted_league = any(keyword.lower() in competition_en.lower() for keyword in LEAGUE_KEYWORDS)
        if not is_wanted_league: continue

        # تحقق من القنوات المطلوبة
        original_channels = match_data.get("channels_raw", [])
        filtered_channels = list(dict.fromkeys([ch for ch in original_channels for kw in CHANNEL_KEYWORDS if kw.lower() in ch.lower()]))
        
        if filtered_channels:
            try:
                # 1. ترجمة البطولة
                competition_ar = translate_text(competition_en, translator, translation_cache, TRANSLATION_MAP)
                
                # 2. فصل وترجمة أسماء الفرق
                title_en = match_data.get("title", "")
                home_team_ar, away_team_ar = parse_and_translate_title(title_en, translator, translation_cache, TEAM_NAME_MAP)

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
    
    output_data = { "date": data.get("date"), "source_url": data.get("source_url"), "matches": filtered_list }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"Process complete. Kept and processed {len(filtered_list)} matches.")

if __name__ == "__main__":
    filter_matches_by_league()

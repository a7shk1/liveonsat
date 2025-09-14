# scripts/filter_json.py
import json
from pathlib import Path

# --- الإعدادات الأساسية ---
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"


# --- ✨ القائمة الكاملة والمحدثة بناءً على طلبك ✨ ---
LEAGUE_KEYWORDS = [
    # الدوريات الخمسة الكبرى
    "English Premier League",      # الدوري الإنجليزي
    "Spanish La Liga (Primera)",             # الدوري الإسباني
    "Italian Serie A",             # الدوري الإيطالي
    "German 1. Bundesliga",        # الدوري الألماني
    "French Ligue 1",              # الدوري الفرنسي

    # كؤوس إنجلترا
    "English League Cup",              # كأس الاتحاد الإنجليزي
    "Carabao Cup",                 # كأس الرابطة (كاراباو)
    "EFL Cup",                     # اسم آخر لكأس الرابطة
    "Community Shield",            # الدرع الخيرية

    # كؤوس إسبانيا
    "Copa del Rey",                # كأس ملك إسبانيا
    "Supercopa",                   # كأس السوبر الإسباني

    # كؤوس إيطاليا
    "Italian Cup (Coppa Italia)",                # كأس إيطاليا
    "Supercoppa Italiana",         # كأس السوبر الإيطالي

    # كؤوس ألمانيا
    "DFB-Pokal",                   # كأس ألمانيا
    "DFL-Supercup",                # كأس السوبر الألماني

    # كؤوس فرنسا
    "Coupe de France",             # كأس فرنسا
    "Trophée des Champions",       # كأس الأبطال الفرنسي (السوبر)

    # البطولات القارية للأندية
    "Champions League",            # دوري أبطال أوروبا
    "Europa League",               # الدوري الأوروبي
    "Conference League",           # دوري المؤتمر الأوروبي
    "Club World Cup",              # كأس العالم للأندية

    # بطولات المنتخبات الدولية
    "World Cup",                   # كأس العالم (يشمل التصفيات والملحق)
    "WC Qualifier",                # طريقة أخرى لكتابة تصفيات المونديال
    "UEFA Euro",                   # بطولة أمم أوروبا (اليورو)
    "Copa America",                # كوبا أمريكا
    "Africa Cup of Nations",       # كأس الأمم الأفريقية
    "AFCON",                       # اختصار كأس الأمم الأفريقية
    "AFC Asian Cup",               # كأس آسيا
    "Nations League",              # دوري الأمم الأوروبية
    "Arab Cup",                    # كأس العرب
    "Saudi Professional League",   # دوري المحترفين السعودي
]



# هذه هي قائمة القنوات الجديدة بناءً على طلبك
CHANNEL_KEYWORDS = [
    "beIN",              # لكل قنوات beIN Sports
    "MATCH! Futbol",     # لكل قنوات ماتش فوتبول
    "Football HD (tjk)",
    "Sport TV",          # لكل قنوات Sport TV Portugal
    "ESPN",              # لكل قنوات ESPN Brazil
    "DAZN",              # لكل قنوات DAZN
    "MATCH! Premier",
    "Sky Sports",        # لكل قنوات سكاي سبورتس
    "IRIB Varzesh",
    "Persiana Sport",
    "MBC",               # لكل قنوات MBC (Action, Masr)
    "TNT Sports",
    "ssc",               # لكل قنوات SSC
    "Shahid",
]


def filter_matches_by_league():
    print("--- Starting Match Filtering Process ---")
    
    try:
        print(f"Reading raw data from: {INPUT_PATH}")
        with INPUT_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ ERROR: Input file not found!")
        return
    except json.JSONDecodeError:
        print(f"❌ ERROR: Could not read the JSON file.")
        return

    all_matches = data.get("matches", [])
    if not all_matches:
        print("🟡 WARNING: The input file contains no matches to filter.")
        return
        
    print(f"Found {len(all_matches)} total matches to check.")

    filtered_list = []
    print("\nFiltering for leagues and channels...")

    for match in all_matches:
        competition = match.get("competition", "")
        if not competition:
            continue
        if "women" in competition.lower():
            continue

        # فلترة الدوريات
        for keyword in LEAGUE_KEYWORDS:
            if keyword.lower() in competition.lower():
                
                # فلترة القنوات
                original_channels = match.get("channels_raw", [])
                filtered_channels = []
                for channel in original_channels:
                    for ch_keyword in CHANNEL_KEYWORDS:
                        if ch_keyword.lower() in channel.lower():
                            filtered_channels.append(channel)
                            break
                
                if filtered_channels:
                    match["channels_raw"] = filtered_channels
                    filtered_list.append(match)

                break 
    
    print(f"\n✅ Filtering complete. Kept {len(filtered_list)} matches.")

    output_data = {
        "date": data.get("date"),
        "source_url": data.get("source_url"),
        "filtered_by_keywords": {
            "leagues": LEAGUE_KEYWORDS,
            "channels": CHANNEL_KEYWORDS
        },
        "matches": filtered_list,
    }

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"✔️ Successfully saved filtered matches to: {OUTPUT_PATH}")
    print("--- Process Finished ---")


if __name__ == "__main__":
    filter_matches_by_league()

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
    "Premier League",      # الدوري الإنجليزي
    "La Liga",             # الدوري الإسباني
    "Serie A",             # الدوري الإيطالي
    "Bundesliga",          # الدوري الألماني
    "Ligue 1",             # الدوري الفرنسي

    # كؤوس إنجلترا
    "FA Cup",              # كأس الاتحاد الإنجليزي
    "Carabao Cup",         # كأس الرابطة (كاراباو)
    "EFL Cup",             # اسم آخر لكأس الرابطة
    "Community Shield",    # الدرع الخيرية

    # كؤوس إسبانيا
    "Copa del Rey",        # كأس ملك إسبانيا
    "Supercopa",           # كأس السوبر الإسباني

    # كؤوس إيطاليا
    "Coppa Italia",        # كأس إيطاليا
    "Supercoppa Italiana", # كأس السوبر الإيطالي

    # كؤوس ألمانيا
    "DFB-Pokal",           # كأس ألمانيا
    "DFL-Supercup",        # كأس السوبر الألماني

    # كؤوس فرنسا
    "Coupe de France",     # كأس فرنسا
    "Trophée des Champions",# كأس الأبطال الفرنسي (السوبر)

    # البطولات القارية للأندية
    "Champions League",    # دوري أبطال أوروبا
    "Europa League",       # الدوري الأوروبي
    "Conference League",   # دوري المؤتمر الأوروبي
    "Club World Cup",      # كأس العالم للأندية

    # بطولات المنتخبات الدولية
    "World Cup",           # كأس العالم (يشمل التصفيات والملحق)
    "WC Qualifier",        # طريقة أخرى لكتابة تصفيات المونديال
    "UEFA Euro",           # بطولة أمم أوروبا (اليورو)
    "Copa America",        # كوبا أمريكا
    "Africa Cup of Nations",# كأس الأمم الأفريقية
    "AFCON",               # اختصار كأس الأمم الأفريقية
    "AFC Asian Cup",       # كأس آسيا
    "Nations League",      # دوري الأمم الأوروبية
    "Arab Cup",            # كأس العرب
]


def filter_matches_by_league():
    """
    تقرأ ملف الجيسون الخام، تفلتر المباريات حسب الكلمات المفتاحية للدوريات،
    وتحفظ النتائج في ملف جيسون جديد.
    """
    print("--- Starting Match Filtering Process ---")
    
    try:
        print(f"Reading raw data from: {INPUT_PATH}")
        with INPUT_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ ERROR: Input file not found! Please run the scraping script first.")
        return
    except json.JSONDecodeError:
        print(f"❌ ERROR: Could not read the JSON file. It might be empty or corrupted.")
        return

    all_matches = data.get("matches", [])
    if not all_matches:
        print("🟡 WARNING: The input file contains no matches to filter.")
        return
        
    print(f"Found {len(all_matches)} total matches to check.")

    filtered_list = []
    print("\nFiltering for leagues containing:")
    for keyword in LEAGUE_KEYWORDS:
        print(f"- {keyword}")

    for match in all_matches:
        # ✨ التصحيح 1: نقرأ اسم البطولة من حقل "competition"
        competition = match.get("competition", "")
        if not competition:
            continue

        for keyword in LEAGUE_KEYWORDS:
            # ✨ التصحيح 2: نقارن الكلمة المفتاحية مع حقل البطولة وليس عنوان المباراة
            if keyword.lower() in competition.lower():
                filtered_list.append(match)
                break
    
    print(f"\n✅ Filtering complete. Kept {len(filtered_list)} matches.")

    output_data = {
        "date": data.get("date"),
        "source_url": data.get("source_url"),
        "filtered_by_keywords": LEAGUE_KEYWORDS,
        "matches": filtered_list,
    }

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"✔️ Successfully saved filtered matches to: {OUTPUT_PATH}")
    print("--- Process Finished ---")


if __name__ == "__main__":
    filter_matches_by_league()

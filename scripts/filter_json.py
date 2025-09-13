# scripts/filter_json.py
import json
from pathlib import Path

# --- الإعدادات الأساسية ---
# تحديد المسارات بناءً على مكان السكربت
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"


# --- ✨ القائمة السحرية ✨ ---
# عدّل على هذه القائمة لتحديد الدوريات اللي تريدها فقط
# السكربت غير حساس لحالة الأحرف (كبيرة أو صغيرة)
LEAGUE_KEYWORDS = [
    "Premier League",      # الدوري الإنجليزي
    "La Liga",             # الدوري الإسباني
    "Serie A",             # الدوري الإيطالي
    "Bundesliga",          # الدوري الألماني
    "Ligue 1",             # الدوري الفرنسي
    "Champions League",    # دوري أبطال أوروبا
    "Europa League",       # الدوري الأوروبي
    "Saudi Pro League",    # دوري روشن السعودي
    "AFC Champions League" # دوري أبطال آسيا
]


def filter_matches_by_league():
    """
    تقرأ ملف الجيسون الخام، تفلتر المباريات حسب الكلمات المفتاحية للدوريات،
    وتحفظ النتائج في ملف جيسون جديد.
    """
    print("--- Starting Match Filtering Process ---")
    
    # 1. قراءة ملف الجيسون الأصلي
    try:
        print(f"Reading raw data from: {INPUT_PATH}")
        with INPUT_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ ERROR: Input file not found! Please run the scraping script first.")
        print(f"File expected at: {INPUT_PATH}")
        return
    except json.JSONDecodeError:
        print(f"❌ ERROR: Could not read the JSON file. It might be empty or corrupted.")
        return

    all_matches = data.get("matches", [])
    if not all_matches:
        print("🟡 WARNING: The input file contains no matches to filter.")
        return
        
    print(f"Found {len(all_matches)} total matches to check.")

    # 2. عملية الفلترة
    filtered_list = []
    print("\nFiltering for leagues containing:")
    for keyword in LEAGUE_KEYWORDS:
        print(f"- {keyword}")

    for match in all_matches:
        # نتأكد أن المباراة تحتوي على عنوان
        title = match.get("title")
        if not title:
            continue

        # نبحث عن الكلمات المفتاحية في العنوان
        for keyword in LEAGUE_KEYWORDS:
            if keyword.lower() in title.lower():
                filtered_list.append(match)
                # إذا وجدنا تطابق، ننتقل للمباراة التالية مباشرةً لتجنب التكرار
                break
    
    print(f"\n✅ Filtering complete. Kept {len(filtered_list)} matches.")

    # 3. تجهيز البيانات الجديدة للحفظ
    output_data = {
        "date": data.get("date"),
        "source_url": data.get("source_url"),
        "filtered_by_keywords": LEAGUE_KEYWORDS, # لتوثيق الدوريات اللي تم الفلترة على أساسها
        "matches": filtered_list,
    }

    # 4. حفظ النتائج في ملف جيسون جديد
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"✔️ Successfully saved filtered matches to: {OUTPUT_PATH}")
    print("--- Process Finished ---")


if __name__ == "__main__":
    filter_matches_by_league()

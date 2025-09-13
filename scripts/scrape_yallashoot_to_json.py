# scripts/scrape_yallashoot_to_json.py
# يجلب مباريات اليوم من يلا شوت ويكتب matches/today.json بدون قنوات (سنضيفها لاحقاً من LiveOnSat)

import json
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "matches"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "today.json"

DEFAULT_URL = "https://www.yalla1shoot.com/matches-today_1/"
FORCE_URL = os.environ.get("FORCE_URL") or DEFAULT_URL

def _text(el):
    try:
        return (el.inner_text() or "").strip()
    except Exception:
        return ""

def _attr(el, name):
    try:
        return el.get_attribute(name) or ""
    except Exception:
        return ""

def normalize_time_to_baghdad(t):
    # يقبل 21:00 أو 9:00 PM الخ — يخرج HH:MM 24h
    s = (t or "").strip()
    if not s:
        return ""
    m = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm|AM|PM)?", s)
    if not m:
        return ""
    hh, mm, ap = m.group(1), m.group(2), m.group(3)
    h = int(hh)
    if ap:
        ap = ap.lower()
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
    return f"{h:02d}:{mm}"

def scrape():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(locale="ar-IQ", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")
        page = ctx.new_page()
        page.set_default_timeout(45000)
        page.goto(FORCE_URL, wait_until="domcontentloaded")

        # عامة: نلتقط الكروت اللي تحتوي معلومات المباراة
        # نحاول أنماط عدة لضمان العمل حتى لو تغيّر الDOM
        cards = []
        selectors = [
            ".match-card, .match, .single-match, .game, .item, .live-match",  # احتمالات عامة
            "article, li, div.card, div.box, div.row"                        # fallback
        ]
        seen = set()
        for sel in selectors:
            for el in page.query_selector_all(sel):
                html = (el.inner_html() or "").lower()
                # heuristics: لازم يحتوي فريقين ووقت
                if not (("vs" in html or " - " in html or " ضد " in html or "–" in html or "v " in html) and (":" in html)):
                    continue
                if el in seen:
                    continue
                seen.add(el)
                cards.append(el)

        matches = []
        for el in cards:
            # أسماء الفرق (عربي) – نحاول انتقاء أكثر نصّين بروزاً
            team_texts = []
            for tsel in ["a", "span", "div", "h3", "h2"]:
                for t in el.query_selector_all(tsel):
                    txt = _text(t)
                    if txt and len(txt) <= 40 and re.search(r"[\u0600-\u06FF]", txt):  # عربي
                        team_texts.append(txt)
            team_texts = list(dict.fromkeys(team_texts))  # unique

            # حاول استخراج اسمين مختلفين
            home = away = ""
            if len(team_texts) >= 2:
                home, away = team_texts[0], team_texts[1]
            else:
                # fallback: ابحث داخل HTML
                raw = (el.text_content() or "").strip()
                m = re.search(r"([\u0600-\u06FF][\u0600-\u06FF\s]+)\s*[-–]\s*([\u0600-\u06FF][\u0600-\u06FF\s]+)", raw)
                if m:
                    home, away = m.group(1).strip(), m.group(2).strip()

            # الوقت
            time_baghdad = ""
            txt_all = (el.text_content() or "")
            mtime = re.search(r"(\d{1,2}:\d{2}\s*(AM|PM|am|pm)?)", txt_all)
            if mtime:
                time_baghdad = normalize_time_to_baghdad(mtime.group(1))

            # الحالة/النتيجة
            status_text = ""
            result_text = ""
            # حالات معروفة من يلا شوت
            for kw in ["جارية الان", "انتهت", "لم تبدأ", "NS", "FT", "HT", "LIVE"]:
                if kw in txt_all:
                    status_text = kw
                    break
            mres = re.search(r"(\d+\s*[-:]\s*\d+)", txt_all)
            if mres:
                result_text = mres.group(1).replace(" ", "")

            # الشعارين (اختياري)
            logos = [ _attr(img, "src") for img in el.query_selector_all("img") ]
            home_logo = logos[0] if len(logos) > 0 else ""
            away_logo = logos[1] if len(logos) > 1 else ""

            # البطولة
            competition = ""
            for csel in ["small", ".comp", ".league", ".tournament", ".competition"]:
                cnode = el.query_selector(csel)
                if cnode:
                    competition = _text(cnode)
                    break
            if not competition:
                # ابحث في النص عن شيء مثل "الدوري ..."
                mcomp = re.search(r"(الدوري|كأس|السوبر|تصفيات|ودية)[\u0600-\u06FF\s,]+", txt_all)
                if mcomp:
                    competition = mcomp.group(0).strip()

            # فلترة إذا ماصار عدنا فريقين
            if not home or not away:
                continue

            # حالة مختصرة
            status = "NS"
            if "انتهت" in status_text or status_text == "FT":
                status = "FT"
            elif "جارية" in status_text or status_text.upper() == "LIVE":
                status = "LIVE"

            # هوية
            date_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
            _id = f"{home.replace(' ','')}-{away.replace(' ','')}-{date_str}"

            matches.append({
                "id": _id,
                "home": home,
                "away": away,
                "home_logo": home_logo,
                "away_logo": away_logo,
                "time_baghdad": time_baghdad,
                "status": status,
                "status_text": status_text or "",
                "result_text": result_text or "",
                "channel": [],     # سنملؤها بعد الدمج
                "competition": competition or "",
                "_source": "yalla1shoot"
            })

        ctx.close()
        browser.close()

    # اكتب JSON
    out = {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "source_url": FORCE_URL,
        "matches": matches
    }
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[YallaShoot] wrote {OUT_PATH} with {len(matches)} matches.")

if __name__ == "__main__":
    scrape()

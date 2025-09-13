# scripts/scrape_liveonsat_only.py
import re
import json
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "matches"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "liveonsat_raw.json"

URL = "https://liveonsat.com/2day.php"

HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "accept-language": "en-US,en;q=0.9,ar;q=0.8",
    "cache-control": "no-cache",
    "pragma": "no-cache",
}

def fetch_html(url: str, retries: int = 3, timeout: int = 45) -> str:
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            time.sleep(1 + i * 2)
    raise last_err

def text_clean(s: str) -> str:
    if not s:
        return ""
    # نحافظ على الاسم كما بالموقع، فقط نشيل الفراغات الزائدة والإيموجي المرفقة
    return (
        s.replace("📺", "")
         .replace("[$]", "")
         .strip()
    )

def guess_match_title(block: BeautifulSoup) -> str:
    """
    نبحث داخل نفس الكتلة عن سطر فيه ' v ' (مثل: Brentford v Chelsea).
    إذا لم نجد، نرجع نصًا فاضيًا.
    """
    txt = " ".join(block.get_text(" ", strip=True).split())
    # الترتيب: league line ثم title ثم ST ثم القنوات. نلتقط أقرب عنوان قبل ST.
    # نجرّب أولاً التقاط كل العناوين المحتملة:
    cands = re.findall(r"([^\n\r]+?\s+v\s+[^\n\r]+?)", txt, flags=re.IGNORECASE)
    if cands:
        # ناخذ أقصر/أوضح واحدة (غالباً تكون الحقيقية)
        cands = sorted(set(cands), key=len)
        return cands[0]
    return ""

def split_home_away(title: str):
    m = re.search(r"(.+?)\s+v\s+(.+)", title, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, None

def parse_liveonsat(html: str):
    """
    يرجع قائمة مباريات:
    [
      {
        "match_title": "Brentford v Chelsea",
        "home": "Brentford",
        "away": "Chelsea",
        "time_st": "22:00",
        "channels": ["beIN Sports MENA 1 HD", "Sky Sports Premier League HD", ...]
      },
      ...
    ]
    """
    soup = BeautifulSoup(html, "html.parser")

    # الفكرة: كل مجموعة قنوات لها div.fLeft_time_live (يحمل ST: HH:MM) ومعه div.fLeft_live فيه عدة جداول قنوات.
    # هنمشي على كل div.fLeft_time_live ونربطه بأقرب كتلة عليا تحتويه (حتى نستخرج عنوان المباراة والقنوات).
    results_map = {}  # key: (title, time) -> list channels

    time_divs = soup.select("div.fLeft_time_live")
    for tdiv in time_divs:
        raw_time = tdiv.get_text(strip=True) or ""
        mt = re.search(r"ST:\s*(\d{1,2}:\d{2})", raw_time)
        if not mt:
            continue
        time_st = mt.group(1)

        # ابحث عن div.fLeft_live ضمن نفس الكتلة
        live_div = None
        parent = tdiv.parent
        for _ in range(6):
            if parent is None:
                break
            live_div = parent.select_one("div.fLeft_live")
            if live_div:
                break
            parent = parent.parent

        if not live_div:
            live_div = tdiv.find_next("div", class_="fLeft_live")
        if not live_div:
            continue

        # القنوات: كل <a> داخل الجداول
        channels = []
        for a in live_div.select("table a"):
            name = text_clean(a.get_text(" ", strip=True))
            if name:
                channels.append(name)
        # إزالة التكرار مع الحفاظ على الترتيب
        seen = set()
        uniq_channels = []
        for c in channels:
            if c not in seen:
                seen.add(c)
                uniq_channels.append(c)

        # عنوان المباراة: نحاول من نفس كتلة parent العليا
        block = parent if parent else tdiv
        match_title = guess_match_title(block)
        if not match_title:
            # fallback: شوف قبل div الوقت بقليل
            prev_txt = " ".join((tdiv.find_previous(string=True) or "").split())
            pm = re.search(r"(.+?)\s+v\s+(.+)", prev_txt, flags=re.IGNORECASE)
            if pm:
                match_title = pm.group(0).strip()

        key = (match_title, time_st)
        if key in results_map:
            # دمج قنوات لو تكررت نفس الخانة
            existing = results_map[key]
            for c in uniq_channels:
                if c not in existing:
                    existing.append(c)
        else:
            results_map[key] = uniq_channels

    # صياغة النتيجة النهائية
    matches = []
    for (title, time_st), chans in results_map.items():
        home, away = split_home_away(title) if title else (None, None)
        matches.append({
            "match_title": title or None,
            "home": home,
            "away": away,
            "time_st": time_st,
            "channels": chans
        })

    # ترتيب اختياري: حسب الوقت ثم العنوان
    def sort_key(m):
        return (m["time_st"] or "99:99", m["match_title"] or "")
    matches.sort(key=sort_key)
    return matches

def main():
    print("[LiveOnSat] GET", URL)
    html = fetch_html(URL, retries=3, timeout=45)
    print("[LiveOnSat] parsing ...")
    matches = parse_liveonsat(html)
    out = {
        "source": URL,
        "count": len(matches),
        "matches": matches
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[write] {OUT_PATH}  (matches={len(matches)})")

if __name__ == "__main__":
    main()

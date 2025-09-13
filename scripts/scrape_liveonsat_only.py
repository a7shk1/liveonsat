# scripts/scrape_liveonsat_only.py
# يجلب كل المباريات والقنوات من LiveOnSat (صفحة اليوم) ويكتب matches/liveonsat_raw.json

import json
import re
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "matches"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "liveonsat_raw.json"

URL = "https://liveonsat.com/2day.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Referer": "https://liveonsat.com/",
    "Cache-Control": "no-cache",
}

def fetch_requests(url: str, retries=3, timeout=45) -> str:
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r.text
            if r.status_code in (403, 406, 429):
                last_err = Exception(f"Blocked with status {r.status_code}")
            else:
                r.raise_for_status()
        except Exception as e:
            last_err = e
        time.sleep(2 + i)
    if last_err:
        raise last_err
    raise RuntimeError("Failed to fetch")

def fetch_playwright(url: str, timeout_ms=45000) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(user_agent=HEADERS["User-Agent"], locale="en-GB")
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        page.goto(url, wait_until="domcontentloaded")
        html = page.content()
        ctx.close()
        browser.close()
        return html

def fetch_html(url: str) -> str:
    # جرب Requests أولاً، وإن اتمنعنا نستخدم Playwright
    try:
        print(f"[LiveOnSat] GET {url}")
        return fetch_requests(url)
    except Exception as e:
        print(f"[LiveOnSat] requests blocked ({e}), fallback to Playwright…")
        return fetch_playwright(url)

def text_clean(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def parse(html: str):
    soup = BeautifulSoup(html, "html.parser")

    items = []
    # كل بلوك قنوات يكون تحت div.fLeft_live وبجانبه وقت ST داخل div.fLeft_time_live
    for live_block in soup.select("div.fLeft_live"):
        # الوقت
        time_div = live_block.find_previous_sibling("div", class_="fLeft_time_live")
        st = text_clean(time_div.get_text()) if time_div else ""
        # ST: 22:00 → 22:00
        kickoff = ""
        m = re.search(r"(\d{1,2}:\d{2})", st)
        if m:
            kickoff = m.group(1)

        # العنوان (المباراة)
        # عادةً اسم المباراة يكون أعلى ضمن نفس المجموعة داخل div.fLeft أو ما قبله
        # نبحث للخلف عن نص فيه " v " أو " vs "
        title = ""
        cur = live_block
        for _ in range(5):
            cur = cur.find_previous(string=lambda t: isinstance(t, str) and (" v " in t or " vs " in t))
            if cur:
                title = text_clean(cur)
                break
        if not title:
            # fallback: جرّب ضمن parent
            parent = live_block.parent
            if parent:
                fulltxt = text_clean(parent.get_text(" "))
                # التقط أول سطر يحوي v
                for line in fulltxt.split("  "):
                    if " v " in line or " vs " in line:
                        title = text_clean(line)
                        break

        # القنوات
        channels = []
        for a in live_block.select("a"):
            label = text_clean(a.get_text())
            if not label:
                continue
            # تجاهل نصوص التنقّل/الفارغة
            if len(label) < 2:
                continue
            channels.append(label)
        channels = list(dict.fromkeys(channels))  # unique-kept order

        if not channels:
            continue

        # إن ما وجدنا عنوان واضح، نبني عنوانًا بسيطًا
        if not title:
            title = f"ST: {kickoff} " + " ".join(channels[:3])

        # خزن العنصر
        items.append({
            "title": title,
            "kickoff_baghdad": kickoff,
            "channels_raw": channels
        })

    return items

def main():
    html = fetch_html(URL)
    items = parse(html)
    out = {
        "source_url": URL,
        "matches": items
    }
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[LiveOnSat] wrote {OUT_PATH} with {len(items)} items.")

if __name__ == "__main__":
    main()

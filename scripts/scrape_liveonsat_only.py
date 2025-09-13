# scripts/scrape_liveonsat_only.py
import os, json, datetime as dt, random, time, re
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# إعدادات عامة
BAGHDAD_TZ = ZoneInfo("Asia/Baghdad")
DEFAULT_URL = "https://liveonsat.com/2day.php"

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "matches"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "liveonsat_raw.json"

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/127.0.0.0 Chrome/127.0.0.0 Safari/537.36",
]

def get_html_with_playwright(url: str, timeout_ms: int = 60000) -> str:
    ua = random.choice(UA_POOL)
    print(f"[LiveOnSat] Playwright GET {url} with UA={ua[:30]}...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-gpu",
        ])
        ctx = browser.new_context(
            user_agent=ua,
            locale="en-GB",
            timezone_id="Asia/Baghdad",
            viewport={"width": 1366, "height": 900},
            java_script_enabled=True,
        )
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        page.goto("https://google.com", wait_until="domcontentloaded")
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except PWTimeout:
            pass
        for y in (400, 1000, 1800, 2600, 3600):
            page.evaluate(f"window.scrollTo(0, {y});")
            time.sleep(0.2)
        html = page.content()
        browser.close()
        return html

def clean_text(t: str) -> str:
    if not t: return ""
    return re.sub(r"\s+", " ", t).strip()

def parse_liveonsat(html: str):
    soup = BeautifulSoup(html, "html.parser")
    matches = []

    blocks = soup.select("div.fLeft div.fLeft_live")
    for live_block in blocks:
        root = live_block.parent  # div.fLeft

        # الوقت: نقرأ النص كما هو بعد ST:
        kickoff = None
        time_div = root.select_one("div.fLeft_time_live")
        if time_div:
            txt = clean_text(time_div.get_text())
            m = re.search(r"ST:\s*([0-2]?\d:[0-5]\d)", txt)
            if m:
                kickoff = m.group(1)

        # العنوان (Team v Team)
        title = ""
        prev = root.previous_sibling
        hop = 0
        while prev and hop < 8 and not title:
            if hasattr(prev, "get_text"):
                txt = clean_text(prev.get_text())
                if " v " in txt or " vs " in txt or " V " in txt:
                    for line in re.split(r"[\r\n]+", txt):
                        l = clean_text(line)
                        if " v " in l or " vs " in l or " V " in l:
                            title = l
                            break
            prev = prev.previous_sibling
            hop += 1

        if not title:
            parent = root.parent
            tries = 0
            while parent and tries < 3 and not title:
                txt = clean_text(parent.get_text())
                m2 = re.search(r"([^\n]+ v [^\n]+)", txt)
                if m2:
                    title = clean_text(m2.group(1))
                    break
                parent = parent.parent
                tries += 1

        # القنوات
        ch_names = []
        for a in live_block.select("table td.chan_col a"):
            nm = clean_text(a.get_text())
            if nm:
                ch_names.append(nm)
        if not ch_names:
            for td in live_block.select("table td.chan_col"):
                nm = clean_text(td.get_text())
                if nm:
                    ch_names.append(nm)

        matches.append({
            "title": title or None,
            "kickoff": kickoff or None,     # بس اسمها kickoff
            "channels_raw": ch_names,
        })

    return matches

def main():
    url = os.environ.get("FORCE_URL") or DEFAULT_URL
    print(f"[LiveOnSat] GET {url}")
    html = get_html_with_playwright(url, timeout_ms=90000)
    items = parse_liveonsat(html)
    today = dt.datetime.now(BAGHDAD_TZ).date().isoformat()

    out = {
        "date": today,
        "source_url": url,
        "matches": items,
        "_note": "kickoff is taken exactly from ST on site (GMT+03).",
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[write] {OUT_PATH} with {len(items)} matches.")

if __name__ == "__main__":
    main()

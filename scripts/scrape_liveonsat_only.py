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
    # شوية يوزر-أجنتس حديثة (Chrome/Edge)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/127.0.0.0 Chrome/127.0.0.0 Safari/537.36",
]

def get_html_with_playwright(url: str, timeout_ms: int = 90000) -> str:
    """
    نجيب الـ HTML عبر Playwright/Chromium ونجبر التوقيت على Asia/Baghdad.
    """
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
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,ar;q=0.5",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Upgrade-Insecure-Requests": "1",
            },
        )

        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)

        try:
            page.goto("https://google.com", wait_until="domcontentloaded")
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            # --- ✨ التعديل النهائي بناءً على الـ HTML الصحيح ✨ ---
            print("[LiveOnSat] Forcing timezone to Asia/Baghdad (GMT+3)...")
            # هذا هو الـ ID الصحيح لقائمة التوقيت اللي أرسلتها
            selector = '#selecttz'
            
            # 1. ننتظر حتى تظهر قائمة التوقيت بشكل مؤكد
            print(f"[LiveOnSat] Waiting for timezone selector '{selector}' to be visible...")
            page.wait_for_selector(selector, state='visible', timeout=15000)

            # 2. نختار التوقيت بناءً على القيمة الدقيقة 'Asia/Baghdad'
            print("[LiveOnSat] Selecting timezone by value: 'Asia/Baghdad'...")
            page.select_option(selector, value='Asia/Baghdad')

            # 3. ننتظر الشبكة تهدأ لضمان تحديث الأوقات
            print("[LiveOnSat] Waiting for network to idle after timezone change...")
            page.wait_for_load_state("networkidle", timeout=20000)
            print("[LiveOnSat] Timezone successfully set to Asia/Baghdad.")
            # --- نهاية التعديل ---

        except Exception as e:
            print(f"[LiveOnSat] FATAL ERROR: Could not set timezone. Taking a screenshot.")
            error_screenshot_path = "liveonsat_error.png"
            page.screenshot(path=error_screenshot_path)
            print(f"[LiveOnSat] Screenshot saved to '{error_screenshot_path}'. Aborting.")
            browser.close()
            # نرجع HTML فارغ أو نطلق استثناء لمنع تحليل بيانات خاطئة
            return "<html><body>Timezone Error</body></html>"

        # لو الصفحة قصيرة، ننزل شوي لتفعيل lazy content
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
    """
    نقرأ القنوات كما تظهر على الموقع (نفس الأسماء).
    """
    soup = BeautifulSoup(html, "html.parser")

    if "Timezone Error" in soup.get_text():
        print("[parse] Skipping parsing due to timezone setting error.")
        return []

    blocks = soup.select("div.fLeft div.fLeft_live")
    matches = []

    for live_block in blocks:
        root = live_block.parent
        time_div = root.select_one("div.fLeft_time_live")
        st_text = clean_text(time_div.get_text()) if time_div else ""
        kickoff = ""
        if st_text:
            m = re.search(r"ST:\s*([0-2]?\d:[0-5]\d)", st_text)
            if m:
                kickoff = m.group(1)

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

        if ch_names:
            matches.append({
                "title": title or "Unknown Match",
                "kickoff_baghdad": kickoff or None,
                "channels_raw": ch_names,
            })

    return matches

def main():
    url = os.environ.get("FORCE_URL") or DEFAULT_URL
    print(f"[LiveOnSat] GET {url}")
    html = get_html_with_playwright(url)

    items = parse_liveonsat(html)
    if not items and "Timezone Error" in html:
        print("[main] No matches found due to an earlier critical error.")
        return

    today = dt.datetime.now(BAGHDAD_TZ).date().isoformat()
    out = {
        "date": today,
        "source_url": url,
        "matches": items,
        "_note": "channels_raw are copied exactly as shown on LiveOnSat with GMT+3 (Asia/Baghdad) timezone.",
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[write] {OUT_PATH} with {len(items)} matches.")

if __name__ == "__main__":
    main()

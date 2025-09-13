# scripts/scrape_liveonsat_only.py
import os, json, datetime as dt, random, time, re
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, expect

# إعدادات عامة
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

def get_html_with_playwright(url: str, timeout_ms: int = 90000) -> str:
    """
    نجيب الـ HTML عبر Playwright ونتأكد من تغيير التوقيت بشكل فعلي.
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
        )
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            print("[LiveOnSat] Starting timezone change procedure...")
            tz_selector_id = '#selecttz'
            first_match_time_selector = "div.fLeft_time_live"
            page.wait_for_selector(tz_selector_id, state='visible', timeout=15000)
            page.wait_for_selector(first_match_time_selector, state='visible', timeout=15000)
            first_time_element = page.locator(first_match_time_selector).first
            initial_time_text = first_time_element.text_content(timeout=5000)
            print(f"[LiveOnSat] Initial time found: '{initial_time_text.strip()}'")
            print(f"[LiveOnSat] Selecting 'Asia/Baghdad' from '{tz_selector_id}'...")
            page.select_option(tz_selector_id, value='Asia/Baghdad')
            print("[LiveOnSat] Waiting for the on-page time to physically update...")
            expect(first_time_element).not_to_have_text(initial_time_text, timeout=20000)
            final_time_text = first_time_element.text_content(timeout=5000)
            print(f"[LiveOnSat] Time successfully updated to: '{final_time_text.strip()}'")
        except Exception as e:
            print(f"[LiveOnSat] FATAL ERROR during timezone verification. Taking a screenshot.")
            print(f"Error details: {e}")
            error_screenshot_path = "liveonsat_error.png"
            page.screenshot(path=error_screenshot_path)
            print(f"[LiveOnSat] Screenshot saved to '{error_screenshot_path}'. Aborting.")
            browser.close()
            return "<html><body>Timezone Error</body></html>"
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
    يقرأ الصفحة، يلتقط عنوان البطولة أولاً ثم يضيفه لكل مباراة تابعة له.
    """
    soup = BeautifulSoup(html, "html.parser")
    if "Timezone Error" in soup.get_text():
        print("[parse] Skipping parsing due to timezone setting error.")
        return []

    matches = []
    current_competition = ""  # متغير لحفظ اسم البطولة الحالية

    # ✨ التعديل الأساسي هنا: نختار عناوين البطولات وبلوكات المباريات معًا بالترتيب
    for element in soup.select('span.comp_head, div.fLeft_live'):
        
        # إذا كان العنصر هو عنوان بطولة، نحفظه وننتقل للعنصر التالي
        if element.name == 'span' and 'comp_head' in element.get('class', []):
            current_competition = clean_text(element.get_text())
            continue

        # إذا كان العنصر هو بلوك مباراة، نبدأ باستخراج تفاصيله
        if element.name == 'div' and 'fLeft_live' in element.get('class', []):
            live_block = element
            root = live_block.parent

            # استخراج وقت المباراة
            time_div = root.select_one("div.fLeft_time_live")
            st_text = clean_text(time_div.get_text()) if time_div else ""
            kickoff = ""
            if st_text:
                m = re.search(r"ST:\s*([0-2]?\d:[0-5]\d)", st_text)
                if m: kickoff = m.group(1)

            # استخراج عنوان المباراة (الفريقين)
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
                if title: break
                prev = prev.previous_sibling
                hop += 1

            # استخراج القنوات
            ch_names = []
            for a in live_block.select("table td.chan_col a"):
                nm = clean_text(a.get_text())
                if nm: ch_names.append(nm)
            if not ch_names:
                for td in live_block.select("table td.chan_col"):
                    nm = clean_text(td.get_text())
                    if nm: ch_names.append(nm)

            # تجميع بيانات المباراة مع إضافة اسم البطولة
            if ch_names:
                matches.append({
                    "competition": current_competition or None,
                    "title": title or "Unknown Match",
                    "kickoff_baghdad": kickoff or None,
                    "channels_raw": ch_names,
                })

    return matches

def main():
    url = os.environ.get("FORCE_URL") or DEFAULT_URL
    print(f"[LiveOnSat] GET {url}")
    html = get_html_with_playwright(url)
    if "Timezone Error" in html:
        print("[main] Aborting due to critical error during scraping.")
        return
    items = parse_liveonsat(html)
    today = dt.date.today().isoformat()
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

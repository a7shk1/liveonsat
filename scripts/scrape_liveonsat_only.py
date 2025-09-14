# scripts/scrape_liveonsat_only.py
import os, json, datetime as dt, random, time, re
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, expect

DEFAULT_URL = "https://liveonsat.com/2day.php"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "matches"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "liveonsat_raw.json"
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

def get_html_with_playwright(url: str, timeout_ms: int = 90000) -> str:
    ua = random.choice(UA_POOL)
    print(f"[LiveOnSat] Playwright GET {url} with UA={ua[:30]}...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-gpu"])
        ctx = browser.new_context(user_agent=ua, locale="en-GB", timezone_id="Asia/Baghdad", viewport={"width": 1366, "height": 900}, java_script_enabled=True)
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            tz_selector_id = '#selecttz'
            first_match_time_selector = "div.fLeft_time_live"
            page.wait_for_selector(tz_selector_id, state='visible', timeout=15000)
            page.wait_for_selector(first_match_time_selector, state='visible', timeout=15000)
            first_time_element = page.locator(first_match_time_selector).first
            initial_time_text = first_time_element.text_content(timeout=5000)
            page.select_option(tz_selector_id, value='Asia/Baghdad')
            expect(first_time_element).not_to_have_text(initial_time_text, timeout=20000)
            print("[LiveOnSat] Timezone successfully updated.")
        except Exception as e:
            print(f"[LiveOnSat] FATAL ERROR during timezone verification: {e}")
            page.screenshot(path="liveonsat_error.png")
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
    soup = BeautifulSoup(html, "html.parser")
    if "Timezone Error" in soup.get_text(): return []
    matches = []
    current_competition = ""
    all_elements = soup.select('span.comp_head, div.fLeft')
    title_block = None
    for element in all_elements:
        if element.name == 'span' and 'comp_head' in element.get('class', []):
            current_competition = clean_text(element.get_text())
            title_block = None
            continue
        if element.name == 'div' and 'fLeft' in element.get('class', []):
            if element.find('div', class_='fLeft_live'):
                if title_block:
                    title = clean_text(title_block.get_text())
                    live_block = element.find('div', class_='fLeft_live')
                    time_div = element.find("div", class_="fLeft_time_live")
                    kickoff = ""
                    if time_div:
                        st_text = clean_text(time_div.get_text())
                        m = re.search(r"ST:\s*([0-2]?\d:[0-5]\d)", st_text)
                        if m: kickoff = m.group(1)
                    ch_names = [clean_text(a.get_text()) for a in live_block.select("table td.chan_col a") if clean_text(a.get_text())]
                    if not ch_names:
                        ch_names = [clean_text(td.get_text()) for td in live_block.select("table td.chan_col") if clean_text(td.get_text())]
                    if ch_names:
                        matches.append({"competition": current_competition or None, "title": title, "kickoff_baghdad": kickoff or None, "channels_raw": ch_names})
                    title_block = None
            else:
                txt = element.get_text()
                if " v " in txt or " vs " in txt or " V " in txt:
                    title_block = element
                else:
                    title_block = None
    return matches

def main():
    url = os.environ.get("FORCE_URL") or DEFAULT_URL
    html = get_html_with_playwright(url)
    items = parse_liveonsat(html)
    today = dt.date.today().isoformat()
    out = {"date": today, "source_url": url, "matches": items}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[write] {OUT_PATH} with {len(items)} matches.")

if __name__ == "__main__":
    main()

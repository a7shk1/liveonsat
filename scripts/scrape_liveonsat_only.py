# scripts/scrape_liveonsat_only.py
import os, json, datetime as dt, random, time, re
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# الأفضل للموبايل لأن HTML أبسط وأقل تغيّر
DEFAULT_URL = "https://m.liveonsat.com/2day.php"

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "matches"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_PATH = OUT_DIR / "liveonsat_raw.json"
DEBUG_HTML = OUT_DIR / "liveonsat_debug.html"
DEBUG_PNG = OUT_DIR / "liveonsat_debug.png"
ERROR_PNG = OUT_DIR / "liveonsat_error.png"

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

ST_REGEX = r"ST:\s*[0-2]?\d:[0-5]\d"
TITLE_REGEX = re.compile(r"\b(vs|v)\b", re.IGNORECASE)


def clean_text(t: str) -> str:
    if not t:
        return ""
    t = t.replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def get_html_with_playwright(url: str, timeout_ms: int = 90000) -> str:
    """
    يجيب HTML من LiveOnSat (الموبايل أو الديسكتوب).
    ما يعتمد على #selecttz نهائياً (لان تغيّر/اختفى مرات).
    ينتظر وجود ST: HH:MM كإشارة إن البيانات تحمّلت.
    """
    ua = random.choice(UA_POOL)
    debug = os.environ.get("DEBUG_LIVEONSAT") == "1"

    print(f"[LiveOnSat] Playwright GET {url} UA={ua[:35]}... debug={debug}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-gpu"],
        )
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

            # انتظر أي ST: 12:34
            page.wait_for_selector(f"text=/{ST_REGEX}/", timeout=25000)

            # سكرول بسيط (احتياط)
            for y in (600, 1400, 2400, 3400):
                page.evaluate(f"window.scrollTo(0, {y});")
                time.sleep(0.2)

            html = page.content()

            if debug:
                DEBUG_HTML.write_text(html, encoding="utf-8")
                page.screenshot(path=str(DEBUG_PNG), full_page=True)
                print("[LiveOnSat] Saved debug html/png.")

            browser.close()
            return html

        except Exception as e:
            print(f"[LiveOnSat] FATAL ERROR: {e}")
            if debug:
                try:
                    page.screenshot(path=str(ERROR_PNG), full_page=True)
                except Exception:
                    pass
            browser.close()
            return "<html><body>FETCH_ERROR</body></html>"


def parse_liveonsat(html: str):
    """
    Parser جديد يعتمد على النص:
    competition -> title (v/vs) -> ST: -> channels...
    """
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text("\n")

    if "FETCH_ERROR" in page_text:
        return []

    # سطور نظيفة
    raw_lines = page_text.splitlines()
    lines = []
    for l in raw_lines:
        l = clean_text(l)
        if not l:
            continue
        # فلترة شوية ضوضاء شائعة
        if l in ("Image", "HOME", "Full Site", "Daily TV"):
            continue
        if l.startswith("Website Last updated"):
            continue
        if l.startswith("Please Note:"):
            continue
        lines.append(l)

    matches = []

    current_comp = None
    current_title = None
    kickoff = None
    channels = []

    def flush():
        nonlocal current_title, kickoff, channels
        if current_title and channels:
            matches.append(
                {
                    "competition": current_comp,
                    "title": current_title,
                    "kickoff_baghdad": kickoff,
                    "channels_raw": channels[:],
                }
            )
        current_title = None
        kickoff = None
        channels = []

    for l in lines:
        # وقت
        if l.startswith("ST:"):
            m = re.search(r"ST:\s*([0-2]?\d:[0-5]\d)", l)
            if m:
                kickoff = m.group(1)
            continue

        # مباراة
        if TITLE_REGEX.search(l):
            flush()
            current_title = l
            continue

        # بطولة (غالباً بيها " - " مثل Week/Round أو اسم دوري - جولة)
        # لا تعتبرها بطولة إذا احنا داخل مباراة (حتى لا نخرب القنوات)
        if (" - " in l) and (not current_title) and (not l.startswith("ST:")):
            current_comp = l
            continue

        # قنوات: أي سطر بعد عنوان المباراة
        if current_title:
            # تجاهل سطور مو قنوات أحياناً
            if l.lower() in ("watch", "details", "more", "back"):
                continue
            channels.append(l)

    flush()
    return matches


def main():
    url = os.environ.get("FORCE_URL") or os.environ.get("LOS_URL") or DEFAULT_URL

    html = get_html_with_playwright(url)
    items = parse_liveonsat(html)

    today = dt.date.today().isoformat()
    out = {"date": today, "source_url": url, "matches": items}

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[write] {OUT_PATH} with {len(items)} matches.")


if __name__ == "__main__":
    main()

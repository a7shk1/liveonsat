# scripts/scrape_liveonsat.py
import os, json, datetime as dt, random, time, re
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup, Tag, NavigableString
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

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

SPACES = re.compile(r"\s+")
ST_RE = re.compile(r"\bST:\s*([0-2]?\d:[0-5]\d)\b", re.IGNORECASE)
COMP_HINTS = re.compile(
    r"(Liga|League|Cup|Copa|Super|Supercup|Supercopa|Troph|Bundesliga|Serie|Ligue|Primera|Pro|Nations|EURO|World|Qualif|Conference)",
    re.IGNORECASE,
)

def clean_text(t: str) -> str:
    if not t: return ""
    return SPACES.sub(" ", t).strip()

def get_html_with_playwright(url: str, timeout_ms: int = 90000) -> str:
    ua = random.choice(UA_POOL)
    print(f"[LiveOnSat] GET {url} …")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-gpu",
        ])
        ctx = browser.new_context(
            user_agent=ua,
            locale="en-GB",
            timezone_id="Asia/Baghdad",  # الصفحة أصلاً تعرض GMT+03 (ST)
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
        for y in (400, 1000, 1800, 2600, 3600, 4600, 5400):
            page.evaluate(f"window.scrollTo(0, {y});"); time.sleep(0.12)
        html = page.content()
        browser.close()
        return html

def nearest_competition(block: Tag, max_hops: int = 20) -> str | None:
    """
    نلتقط أقرب عنوان بطولة فوق .blockfix: نص بسيط يحتوي تلميحات (League/Cup/Primera…)
    """
    cur: Tag | None = block
    hops = 0
    while cur and hops < max_hops:
        prev = cur.previous_sibling
        while prev:
            txt = clean_text(prev.get_text() if isinstance(prev, Tag) else str(prev))
            if txt and COMP_HINTS.search(txt) and "ST:" not in txt and len(txt) <= 160:
                return txt
            if isinstance(prev, Tag):
                # عناصر بارزة داخل السابق
                for tag in ("b", "strong", "font", "span", "td", "div"):
                    for el in prev.find_all(tag):
                        t2 = clean_text(el.get_text())
                        if t2 and COMP_HINTS.search(t2) and "ST:" not in t2 and len(t2) <= 160:
                            return t2
            prev = prev.previous_sibling
        cur = cur.parent if isinstance(cur, Tag) else None
        hops += 1
    return None

def parse_liveonsat(html: str):
    soup = BeautifulSoup(html, "html.parser")
    matches = []

    # كل بلوك مباراة بالشكل اللي أرسلته (.blockfix)
    for block in soup.select("div.blockfix"):
        # عنوان المباراة
        title_div = block.select_one("div.fix_text div.fLeft")
        title = clean_text(title_div.get_text()) if title_div else None

        # وقت ST القريب داخل نفس البلوك
        time_div = block.select_one("div.fLeft_time_live")
        kickoff = None
        if time_div:
            m = ST_RE.search(clean_text(time_div.get_text()))
            if m: kickoff = m.group(1)

        # القنوات
        ch_names: list[str] = []
        # أولاً: <a> داخل خلايا chan_col
        for a in block.select("div.fLeft_live table td.chan_col a"):
            nm = clean_text(a.get_text())
            if nm: ch_names.append(nm)
        # لو ماكو <a> نلتقط نص الخلية نفسها
        if not ch_names:
            for td in block.select("div.fLeft_live table td.chan_col"):
                nm = clean_text(td.get_text())
                if nm: ch_names.append(nm)

        # البطولة (اختياري): أقرب عنوان فوق البلوك
        competition = nearest_competition(block)

        # خزّن فقط إذا عندنا على الأقل قنوات أو عنوان (نتجنّب الضوضاء)
        if title or ch_names or kickoff:
            matches.append({
                "competition": competition,
                "title": title,
                "kickoff_baghdad": kickoff,      # نفس ST بدون تحويل (الموقع GMT+03)
                "channels_raw": ch_names,        # أسماء القنوات كما بالموقع
            })

    return matches

def main():
    url = os.environ.get("FORCE_URL") or DEFAULT_URL
    html = get_html_with_playwright(url, timeout_ms=90000)
    items = parse_liveonsat(html)

    today = dt.datetime.now(BAGHDAD_TZ).date().isoformat()
    out = {
        "date": today,
        "source_url": url,
        "matches": items,
        "_note": "channels_raw are copied exactly as shown on LiveOnSat (ST is GMT+03).",
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[write] {OUT_PATH} with {len(items)} matches.")

if __name__ == "__main__":
    main()

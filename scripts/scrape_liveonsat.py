# scripts/scrape_liveonsat.py
import os, json, time, random, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BAGHDAD_TZ = ZoneInfo("Asia/Baghdad")
DEFAULT_URL = os.environ.get("FORCE_URL") or "https://liveonsat.com/2day.php"

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "matches"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "liveonsat_raw.json"
DBG_HTML = OUT_DIR / "liveonsat_debug.html"

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/127.0.0.0 Chrome/127.0.0.0 Safari/537.36",
]

JS_EXTRACT = r"""
() => {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const out = [];

  // 1) القالب الأساسي: blockfix
  const blocks = Array.from(document.querySelectorAll("div.blockfix"));
  const grabFromBlock = (block) => {
    // Title
    const title = clean(block.querySelector("div.fix_text div.fLeft")?.textContent || "");

    // ST time
    const stRaw = clean(block.querySelector("div.fLeft_time_live")?.textContent || "");
    const st = (stRaw.match(/ST:\s*([0-2]?\d:[0-5]\d)/i) || [])[1] || "";

    // Channels
    const chans = [];
    block.querySelectorAll("div.fLeft_live table td.chan_col a").forEach(a => {
      const t = clean(a.textContent);
      if (t) chans.push(t);
    });
    if (chans.length === 0) {
      block.querySelectorAll("div.fLeft_live table td.chan_col").forEach(td => {
        const t = clean(td.textContent);
        if (t) chans.push(t);
      });
    }

    // Competition (أقرب عنوان فوق البلوك يحتوي تلميح بطولة)
    let comp = "";
    const hints = /(Liga|League|Cup|Copa|Super|Supercup|Supercopa|Troph|Bundesliga|Serie|Ligue|Primera|Pro|Nations|EURO|World|Qualif|Conference)/i;
    let cur = block;
    for (let hop = 0; hop < 20 && cur; hop++) {
      let p = cur.previousSibling;
      while (p) {
        if (p.textContent) {
          const txt = clean(p.textContent);
          if (txt && hints.test(txt) && !/ST:\s*\d{1,2}:\d{2}/i.test(txt) && txt.length <= 160) {
            comp = txt;
            break;
          }
        }
        p = p.previousSibling;
      }
      if (comp) break;
      cur = cur.parentElement;
    }

    if (title || st || chans.length) {
      out.push({
        competition: comp || null,
        title: title || null,
        kickoff_baghdad: st || null,
        channels_raw: Array.from(new Set(chans)),
      });
    }
  };

  if (blocks.length) {
    blocks.forEach(grabFromBlock);
    return out;
  }

  // 2) Fallback: بعض الصفحات ما تستعمل blockfix (نفس البُنية الداخلية)
  const altBlocks = Array.from(document.querySelectorAll("div.fLeft_live")).map(el => el.closest("div.fLeft"));
  const seen = new Set();
  (altBlocks || []).forEach(root => {
    if (!root || seen.has(root)) return;
    seen.add(root);

    const title = clean(root.previousElementSibling?.querySelector("div.fix_text div.fLeft")?.textContent
      || root.parentElement?.querySelector("div.fix_text div.fLeft")?.textContent
      || "");

    const stRaw = clean(root.querySelector("div.fLeft_time_live")?.textContent || "");
    const st = (stRaw.match(/ST:\s*([0-2]?\d:[0-5]\d)/i) || [])[1] || "";

    const chans = [];
    root.querySelectorAll("div.fLeft_live table td.chan_col a").forEach(a => {
      const t = clean(a.textContent); if (t) chans.push(t);
    });
    if (chans.length === 0) {
      root.querySelectorAll("div.fLeft_live table td.chan_col").forEach(td => {
        const t = clean(td.textContent); if (t) chans.push(t);
      });
    }

    // competition بالـ fallback — نبحث للأعلى شوية
    let comp = "";
    const hints = /(Liga|League|Cup|Copa|Super|Supercup|Supercopa|Troph|Bundesliga|Serie|Ligue|Primera|Pro|Nations|EURO|World|Qualif|Conference)/i;
    let cur = root;
    for (let hop = 0; hop < 20 && cur; hop++) {
      let p = cur.previousSibling;
      while (p) {
        const txt = clean(p.textContent || "");
        if (txt && hints.test(txt) && !/ST:\s*\d{1,2}:\d{2}/i.test(txt) && txt.length <= 160) { comp = txt; break; }
        p = p.previousSibling;
      }
      if (comp) break;
      cur = cur.parentElement;
    }

    if (title || st || chans.length) {
      out.push({
        competition: comp || null,
        title: title || null,
        kickoff_baghdad: st || null,
        channels_raw: Array.from(new Set(chans)),
      });
    }
  });

  return out;
}
"""

def gradual_scroll(page):
    # تفعيل أي lazy content
    for y in (300, 900, 1500, 2200, 3000, 3800, 4600, 5400, 6200):
        page.evaluate(f"window.scrollTo(0, {y});")
        time.sleep(0.12)

def fetch_once(url: str):
    ua = random.choice(UA_POOL)
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
        page.set_default_timeout(90000)
        page.goto("https://google.com", wait_until="domcontentloaded")
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except PWTimeout:
            pass
        gradual_scroll(page)
        items = page.evaluate(JS_EXTRACT)
        html = page.content()
        browser.close()
    return items, html

def main():
    # محاولة 1: الديسكتوب
    items, html = fetch_once(DEFAULT_URL)

    # محاولة 2: نسخة الموبايل fallback إذا ما لقينا شي
    if not items:
        print("[info] no blocks found on desktop; trying mobile…")
        items, html = fetch_once("https://m.liveonsat.com/2day.php")

    # إذا بعده فارغ: خزّن الـ HTML للديبَغ حتى تقدر تشوفه بالريبو
    if not items:
        DBG_HTML.write_text(html, encoding="utf-8")
        print(f"[warn] no matches parsed. Wrote debug HTML to {DBG_HTML}")

    today = dt.datetime.now(BAGHDAD_TZ).date().isoformat()
    out = {
        "date": today,
        "source_url": DEFAULT_URL,
        "matches": items,
        "_note": "ST is already GMT+03 (Baghdad). channels_raw as shown on LiveOnSat.",
    }
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[write] {OUT_PATH} with {len(items)} matches.")

if __name__ == "__main__":
    main()

# scripts/scrape_yallashoot_to_json.py
import os, json, datetime as dt, time, re
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BAGHDAD_TZ = ZoneInfo("Asia/Baghdad")
DEFAULT_URL = "https://www.yalla1shoot.com/matches-today_1/"

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "matches"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "today.json"

# ---------- أدوات مساعدة ----------
def gradual_scroll(page, step=900, pause=0.25):
    last_h = 0
    while True:
        h = page.evaluate("() => document.body.scrollHeight")
        if h <= last_h:
            break
        for y in range(0, h, step):
            page.evaluate(f"window.scrollTo(0, {y});")
            time.sleep(pause)
        last_h = h

def normalize_status(ar_text: str) -> str:
    t = (ar_text or "").strip()
    if not t: return "NS"
    if "انتهت" in t or "نتهت" in t: return "FT"
    if "مباشر" in t or "الشوط" in t: return "LIVE"
    if "لم" in t and "تبدأ" in t: return "NS"
    return "NS"

def parse_liveonsat_by_time(html: str):
    """
    يرجّع dict مثل:
      {"22:00": ["beIN Sports MENA 1 HD", "Sky Sports Premier League HD", ...], "21:45": [...], ...}
    بدون أي فلترة.
    """
    soup = BeautifulSoup(html, "html.parser")
    time_to_channels = {}

    # كل بلوك بيه وقت ST: 22:00 وقائمة جداول قنوات ضمن .fLeft_live
    # نبحث عن كل العناصر اللي تحتوي نص يبدأ بـ "ST: "
    for tdiv in soup.select("div.fLeft_time_live"):
        raw = (tdiv.get_text(strip=True) or "")
        m = re.search(r"ST:\s*(\d{1,2}:\d{2})", raw)
        if not m:
            continue
        st_time = m.group(1)  # مثل 22:00

        # القنوات تكون داخل أخو/نفس العنصر ضمن div.fLeft_live
        live_div = None
        # جرّب نلقى sibling أو parent فيه fLeft_live
        parent = tdiv.parent
        for _ in range(3):
            if parent is None:
                break
            live_div = parent.select_one("div.fLeft_live")
            if live_div:
                break
            parent = parent.parent

        if not live_div:
            # fallback: فتّش عن div.fLeft_live الأقرب بعد tdiv
            live_div = tdiv.find_next("div", class_="fLeft_live")

        chans = []
        if live_div:
            # كل جدول بيه tr > td.chan_col > a نصّها هو اسم القناة
            for a in live_div.select("table a"):
                name = (a.get_text(" ", strip=True) or "").strip()
                if not name:
                    continue
                # نظّف رموز الإيموجي للوضوح بس خليه نفس الكتابة قدر الإمكان
                name = name.replace("📺", "").replace("[$]", "").strip()
                if name:
                    chans.append(name)

        if chans:
            # خزن بدون تكرار مع الحفاظ على الترتيب
            seen = set()
            uniq = []
            for c in chans:
                if c not in seen:
                    seen.add(c)
                    uniq.append(c)
            # دمج إذا كان نفس الوقت ظهر أكثر من مرة
            if st_time in time_to_channels:
                already = time_to_channels[st_time]
                for c in uniq:
                    if c not in already:
                        already.append(c)
            else:
                time_to_channels[st_time] = uniq

    return time_to_channels

def fetch_liveonsat_html(url="https://liveonsat.com/2day.php", timeout=45):
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36",
        "accept-language": "en-US,en;q=0.9,ar;q=0.8",
        "cache-control": "no-cache",
        "pragma": "no-cache",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text

# ---------- المرحلة 1: سحب بيانات يلا شوت كما كانت ----------
def scrape_yallashoot_cards(url: str):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 864},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36",
            locale="ar",
            timezone_id="Asia/Baghdad",
        )
        page = ctx.new_page()
        page.set_default_timeout(60000)

        print("[open]", url)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except PWTimeout:
            pass

        gradual_scroll(page)

        js = r"""
        () => {
          const cards = [];
          document.querySelectorAll('.AY_Inner').forEach((inner, idx) => {
            const root = inner.parentElement || inner;
            const qText = (sel) => {
              const el = root.querySelector(sel);
              return el ? el.textContent.trim() : "";
            };
            const qAttr = (sel, attr) => {
              const el = root.querySelector(sel);
              if (!el) return "";
              return el.getAttribute(attr) || el.getAttribute('data-' + attr) || "";
            };

            const home = qText('.MT_Team.TM1 .TM_Name');
            const away = qText('.MT_Team.TM2 .TM_Name');
            const homeLogo = qAttr('.MT_Team.TM1 .TM_Logo img', 'src') || qAttr('.MT_Team.TM1 .TM_Logo img', 'data-src');
            const awayLogo = qAttr('.MT_Team.TM2 .TM_Logo img', 'src') || qAttr('.MT_Team.TM2 .TM_Logo img', 'data-src');

            const time = qText('.MT_Data .MT_Time');
            const result = qText('.MT_Data .MT_Result');
            const status = qText('.MT_Data .MT_Stat');

            const infoLis = Array.from(root.querySelectorAll('.MT_Info li span')).map(x => x.textContent.trim());
            const channel = infoLis[0] || "";
            const commentator = infoLis[1] || "";
            const competition = infoLis[2] || "";

            cards.push({
              home, away, home_logo: homeLogo, away_logo: awayLogo,
              time_local: time, result_text: result, status_text: status,
              channel, commentator, competition
            });
          });
          return cards;
        }
        """
        cards = page.evaluate(js)
        browser.close()
    print(f"[YallaShoot] found {len(cards)} cards")
    return cards

# ---------- المرحلة 2: دمج قنوات LiveOnSat (بدون فلترة) ----------
ITALY_AR_KEYWORDS = ["الدوري الإيطالي", "إيطاليا"]

def integrate_channels(yalla_cards, liveonsat_time_map):
    def is_italian_league(ar_comp):
        t = (ar_comp or "").strip()
        return any(k in t for k in ITALY_AR_KEYWORDS)

    out_matches = []
    for c in yalla_cards:
        today = dt.datetime.now(BAGHDAD_TZ).date().isoformat()
        mid = f"{c['home'][:12]}-{c['away'][:12]}-{today}".replace(" ", "")

        # مطابقة على الوقت فقط (مبدئياً)
        time_baghdad = (c.get("time_local") or "").strip()
        chans = list(liveonsat_time_map.get(time_baghdad, []))

        # قاعدة خاصة للدوري الإيطالي
        if is_italian_league(c.get("competition", "")):
            # أضف starzplay1 و starzplay2 إذا مو موجودة
            prefix = ["starzplay1", "starzplay2"]
            for p in reversed(prefix):
                if p not in [x.lower() for x in chans]:
                    chans.insert(0, p)

        out_matches.append({
            "id": mid,
            "home": c["home"],
            "away": c["away"],
            "home_logo": c["home_logo"],
            "away_logo": c["away_logo"],
            "time_baghdad": time_baghdad,
            "status": normalize_status(c["status_text"]),
            "status_text": c["status_text"],
            "result_text": c["result_text"],
            # نخلي القنوات من لايف أون سات "كما هي" بدون فلترة، حتى نتأكد تشتغل
            "channel": chans,  # لاحقاً نرجّع نفعل فلترة/تطبيع أسماء القنوات
            "competition": c["competition"] or None,
            "_source": "yalla1shoot+liveonsat-time"
        })
    return out_matches

def scrape():
    url = os.environ.get("FORCE_URL") or DEFAULT_URL
    today = dt.datetime.now(BAGHDAD_TZ).date().isoformat()

    # 1) سحب اليلا شوت
    yalla_cards = scrape_yallashoot_cards(url)

    # 2) سحب لايف أون سات مرّة وحدة
    try:
        print("[LiveOnSat] fetch 2day.php ...")
        los_html = fetch_liveonsat_html("https://liveonsat.com/2day.php", timeout=45)
        los_time_map = parse_liveonsat_by_time(los_html)
        print(f"[LiveOnSat] time slots found: {len(los_time_map)}")
    except Exception as e:
        print("[LiveOnSat] FAIL:", e)
        los_time_map = {}

    # 3) دمج القنوات (بدون فلترة)
    matches = integrate_channels(yalla_cards, los_time_map)

    out = {
        "date": today,
        "source_url": url,
        "matches": matches
    }
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[write] {OUT_PATH} with {len(out['matches'])} matches.")

if __name__ == "__main__":
    scrape()

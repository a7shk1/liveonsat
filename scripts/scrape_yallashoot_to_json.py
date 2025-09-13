# scripts/scrape_yallashoot_to_json.py
import os, json, datetime as dt, time, re, unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from html import unescape
from difflib import SequenceMatcher
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BAGHDAD_TZ = ZoneInfo("Asia/Baghdad")
DEFAULT_URL = "https://www.yalla1shoot.com/matches-today_1/"

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "matches"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "today.json"

# ======================================================
# LiveOnSat utils
def _session_with_retries():
    s = requests.Session()
    retry = Retry(
        total=5, connect=5, read=5, status=5, backoff_factor=1.2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False
    )
    ad = HTTPAdapter(max_retries=retry)
    s.mount("http://", ad); s.mount("https://", ad)
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    return s

def fetch_liveonsat_html():
    url = os.environ.get("LOS_URL", "https://liveonsat.com/2day.php")
    s = _session_with_retries()
    r = s.get(url, timeout=(10, 60))
    r.raise_for_status()
    return r.text

def _normspace(s): return re.sub(r"\s+", " ", (s or "").strip())
def _strip_tags(s): return re.sub(r"<[^>]+>", "", s or "")

def parse_liveonsat_basic(html):
    results = []
    comp_pat = re.compile(r'<span\s+class="comp_head">(?P<comp>.*?)</span>', re.S)
    for m in comp_pat.finditer(html):
        comp = _strip_tags(m.group("comp"))
        start = m.end()
        nxt = comp_pat.search(html, start)
        end = nxt.start() if nxt else len(html)
        block = html[start:end]

        tm = re.search(r'<div\s+class="fLeft"[^>]*?>\s*([^<]*\sv\s[^<]*)</div>', block)
        fixture = _normspace(unescape(_strip_tags(tm.group(1))) if tm else "")
        home = away = ""
        if " v " in fixture:
            parts = [p.strip() for p in fixture.split(" v ", 1)]
            if len(parts) == 2:
                home, away = parts

        channels = []
        for live_area in re.finditer(r'<div\s+class="fLeft_live"[^>]*?>(?P<html>.*?)</div>', block, re.S):
            area = live_area.group("html")
            for a in re.finditer(r'<a[^>]+class="chan_live_.*?"[^>]*?>(?P<text>.*?)</a>', area, re.S):
                name = _normspace(unescape(_strip_tags(a.group("text"))))
                if name:
                    channels.append({"name": name})

        results.append({
            "competition": comp, "fixture": fixture,
            "home": home, "away": away, "channels": channels
        })
    return results

def _normalize_team(s):
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"\s+", " ", s)

# قاموس عربي→إنجليزي (موسع، زوده تدريجياً حسب الحاجة)
TEAM_MAP_AR2EN = {
    "الهلال": "Al Hilal", "القادسية": "Al Qadisiyah",
    "يوفنتوس": "Juventus", "إنتر ميلان": "Inter Milan", "انتر ميلان": "Inter Milan",
    "فيورنتينا": "Fiorentina", "نابولي": "Napoli", "ميلان": "AC Milan",
    "ايه سي ميلان": "AC Milan", "انتر": "Inter Milan", "روما": "Roma", "لاتسيو": "Lazio",
    "اتالانتا": "Atalanta", "تورينو": "Torino", "بولونيا": "Bologna", "جنوى": "Genoa", "كالياري": "Cagliari",
    "أتلتيكو مدريد": "Atletico Madrid", "اتلتيكو مدريد": "Atletico Madrid",
    "فياريال": "Villarreal",
    "بلد الوليد": "Real Valladolid", "ألميريا": "Almeria",
    "أتلتيك بلباو": "Athletic Bilbao", "اتلتيك بلباو": "Athletic Bilbao",
    "برينتفورد": "Brentford", "تشيلسي": "Chelsea", "وست هام يونايتد": "West Ham United",
    "توتنهام هوتسبر": "Tottenham Hotspur", "توتنهام": "Tottenham Hotspur",
    "بايرن ميونخ": "Bayern Munich", "هامبورج": "Hamburg", "هامبورغ": "Hamburg",
    "أوكسير": "Auxerre", "موناكو": "Monaco",
    "الجيش الملكي": "AS FAR Rabat", "اتحاد يعقوب المنصور": "Ittihad Yakoub Al Mansour",
    "الفتح الرباطي": "FUS Rabat", "الرجاء البيضاوي": "Raja Casablanca",
    "الزمالك": "Zamalek", "المصري": "Al Masry",
    "سيراميكا كليوباترا": "Ceramica Cleopatra", "سموحة": "Smouha",
    "ريال مدريد": "Real Madrid", "ريال سوسيداد": "Real Sociedad",
    "برشلونة": "Barcelona",
}

def _to_en(name):
    name = (name or "").strip()
    return TEAM_MAP_AR2EN.get(name, name)

def _similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def find_best_los_match(y_home, y_away, los_matches, threshold=0.72):
    candidates = [(y_home, y_away), (y_away, y_home)]
    best, best_score = None, -1.0
    for cand_home, cand_away in candidates:
        yh = _normalize_team(_to_en(cand_home))
        ya = _normalize_team(_to_en(cand_away))
        for m in los_matches:
            lh = _normalize_team(m.get("home", ""))
            la = _normalize_team(m.get("away", ""))
            s1 = _similar(f"{yh} {ya}", f"{lh} {la}")
            s2 = _similar(f"{yh} {ya}", _normalize_team(m.get("fixture", "")))
            score = max(s1, s2)
            if score > best_score:
                best, best_score = m, score
    return best if best_score >= threshold else None

# ======================================================
# Scraper (YallaShoot)
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

def scrape():
    url = os.environ.get("FORCE_URL") or DEFAULT_URL
    today = dt.datetime.now(BAGHDAD_TZ).date().isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 864},
            user_agent="Mozilla/5.0",
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
          document.querySelectorAll('.AY_Inner').forEach((inner) => {
            const root = inner.parentElement || inner;
            const qText = (sel) => { const el = root.querySelector(sel); return el ? el.textContent.trim() : ""; };
            const qAttr = (sel, attr) => { const el = root.querySelector(sel); return el ? (el.getAttribute(attr) || el.getAttribute('data-'+attr) || "") : ""; };

            const home = qText('.MT_Team.TM1 .TM_Name');
            const away = qText('.MT_Team.TM2 .TM_Name');
            const homeLogo = qAttr('.MT_Team.TM1 .TM_Logo img', 'src') || qAttr('.MT_Team.TM1 .TM_Logo img', 'data-src');
            const awayLogo = qAttr('.MT_Team.TM2 .TM_Logo img', 'src') || qAttr('.MT_Team.TM2 .TM_Logo img', 'data-src');

            const time = qText('.MT_Data .MT_Time');
            const result = qText('.MT_Data .MT_Result');
            const status = qText('.MT_Data .MT_Stat');

            const infoLis = Array.from(root.querySelectorAll('.MT_Info li span')).map(x => x.textContent.trim());
            const competition = infoLis[2] || "";

            cards.push({
              home, away, home_logo: homeLogo, away_logo: awayLogo,
              time_local: time, result_text: result, status_text: status,
              competition
            });
          });
          return cards;
        }
        """
        cards = page.evaluate(js)
        browser.close()

    def normalize_status(ar_text: str) -> str:
        t = (ar_text or "").strip()
        if not t: return "NS"
        if "انتهت" in t: return "FT"
        if "مباشر" in t or "الشوط" in t: return "LIVE"
        if "لم" in t and "تبدأ" in t: return "NS"
        return "NS"

    out = {"date": today, "source_url": url, "matches": []}
    for c in cards:
        mid = f"{c['home'][:12]}-{c['away'][:12]}-{today}".replace(" ", "")
        out["matches"].append({
            "id": mid,
            "home": c["home"],
            "away": c["away"],
            "home_logo": c["home_logo"],
            "away_logo": c["away_logo"],
            "time_baghdad": c["time_local"],
            "status": normalize_status(c["status_text"]),
            "status_text": c["status_text"],
            "result_text": c["result_text"],
            "channel": [],  # نعبيها من LiveOnSat (دائماً List)
            "competition": c["competition"],
            "_source": "yalla1shoot"
        })

    # ======== إحلال القنوات من LiveOnSat (RAW: بدون فلترة/تطبيع) ========
    try:
        los_html = fetch_liveonsat_html()
        los_list = parse_liveonsat_basic(los_html)
        replaced = 0
        for m in out["matches"]:
            los_m = find_best_los_match(m["home"], m["away"], los_list, threshold=0.72)
            chan_set = []
            if los_m:
                for ch in los_m.get("channels", []):
                    nm = (ch.get("name") or "").strip()
                    if nm:
                        chan_set.append(nm)  # 👈 نضيف الاسم كما هو من LiveOnSat

            # خاص: كل مباراة بالدوري الإيطالي → أضف starzplay1 و starzplay2
            if m.get("competition") and "ايطالي" in m["competition"]:
                for sp in ["starzplay1", "starzplay2"]:
                    if sp not in chan_set:
                        chan_set.append(sp)

            if not chan_set:
                print(f"[no-channels] {m['home']} vs {m['away']}  (comp={m.get('competition')})")

            m["channel"] = chan_set  # دائماً List
            if chan_set:
                replaced += 1

        print(f"[liveonsat] replaced channels for {replaced}/{len(out['matches'])} matches")
    except Exception as e:
        print(f"[liveonsat][warn]", e)

    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[write] {OUT_PATH} with {len(out['matches'])} matches.")

if __name__ == "__main__":
    scrape()

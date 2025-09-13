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
from bs4 import BeautifulSoup

BAGHDAD_TZ = ZoneInfo("Asia/Baghdad")
DEFAULT_URL = "https://www.yalla1shoot.com/matches-today_1/"

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "matches"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "today.json"

# ==============================
# Utils
def _session_with_retries():
    s = requests.Session()
    retry = Retry(
        total=6, connect=6, read=6, status=6,
        backoff_factor=1.2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "HEAD"])
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

def _norm(s): return re.sub(r"\s+", " ", (s or "").strip())
def _strip_tags(s): return re.sub(r"<[^>]+>", "", s or "")

def _normalize_team(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"\s+", " ", s)

TEAM_MAP_AR2EN = {
    "الهلال": "Al Hilal", "القادسية": "Al Qadisiyah",
    "يوفنتوس": "Juventus", "إنتر ميلان": "Inter Milan", "انتر ميلان": "Inter Milan",
    "فيورنتينا": "Fiorentina", "نابولي": "Napoli", "ميلان": "AC Milan", "ايه سي ميلان": "AC Milan",
    "روما": "Roma", "لاتسيو": "Lazio", "اتالانتا": "Atalanta", "تورينو": "Torino",
    "بولونيا": "Bologna", "جنوى": "Genoa", "كالياري": "Cagliari",
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

def _to_en(name: str) -> str:
    name = (name or "").strip()
    return TEAM_MAP_AR2EN.get(name, name)

def _similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def find_best_los_match(y_home, y_away, los_matches, threshold=0.72):
    yh = _normalize_team(_to_en(y_home))
    ya = _normalize_team(_to_en(y_away))
    best = None
    best_score = -1.0
    for m in los_matches:
        lh = _normalize_team(m.get("home", ""))
        la = _normalize_team(m.get("away", ""))
        s1 = _similar(f"{yh} {ya}", f"{lh} {la}")
        s2 = _similar(f"{yh} {ya}", _normalize_team(m.get("fixture", "")))
        score = max(s1, s2)
        if score > best_score:
            best = m; best_score = score
    return best if best_score >= threshold else None

# ==============================
# Parse LiveOnSat using the structure you sent (fLeft_live)
def parse_liveonsat(html: str):
    """
    يطلع List من المباريات:
    {
      'competition': 'Premier League - Week 4',
      'fixture': 'Brentford v Chelsea',
      'home': 'Brentford',
      'away': 'Chelsea',
      'channels': [ 'beIN Sports MENA 1 HD', 'DAZN 1 Portugal HD', ... ]
    }
    """
    soup = BeautifulSoup(html, "html.parser")

    # كل بلوك قنوات داخل fLeft_live. نطلع أقرب fixture موجود داخل نفس الحاوية.
    live_divs = soup.select("div.fLeft_live")
    results = []

    def find_fixture_container(live_div):
        # نصعد للأب ونفتش عن div.fLeft نصه يحتوي " v "
        node = live_div
        for _ in range(5):  # جرّب لحد 5 مستويات للأعلى
            parent = node.parent
            if not parent: break
            # دور على أي div.fLeft جوّا الـ parent نصه فيه v بين الفريقين
            for d in parent.find_all("div", class_="fLeft"):
                txt = _norm(d.get_text(" ", strip=True))
                if " v " in txt.lower():
                    return parent, txt
            node = parent
        return None, ""

    # نحتاج أيضًا التقاط اسم المسابقة إن وجدت قريبة (<span class="comp_head">)
    comp_heads = []
    for sp in soup.select("span.comp_head"):
        comp_heads.append((sp, _norm(sp.get_text(" ", strip=True))))

    def nearest_comp_text(container):
        # ابحث للأعلى عن أقرب comp_head نصّي
        node = container
        for _ in range(6):
            if not node: break
            # إذا sibling سابق يحتوي comp_head
            prev = node.previous_sibling
            steps = 0
            while prev and steps < 6:
                if getattr(prev, "select", None):
                    span = prev.select_one("span.comp_head")
                    if span:
                        return _norm(span.get_text(" ", strip=True))
                prev = prev.previous_sibling
                steps += 1
            node = node.parent
        return ""

    # اجمع كل العناصر
    for live in live_divs:
        container, fixture_txt = find_fixture_container(live)
        if not container or not fixture_txt:
            # fallback: جرّب أخذ أول div.fLeft فوق
            up = live
            for _ in range(5):
                up = up.parent
                if not up: break
                hint = up.select_one("div.fLeft")
                if hint:
                    t = _norm(hint.get_text(" ", strip=True))
                    if " v " in t.lower():
                        container = up; fixture_txt = t; break

        if not fixture_txt:
            continue

        # استخرج home / away
        fix = _strip_tags(unescape(fixture_txt))
        fixture = _norm(fix)
        home, away = "", ""
        if " v " in fixture.lower():
            parts = re.split(r"\sv\s", fixture, flags=re.I, maxsplit=1)
            if len(parts) == 2:
                home, away = parts[0].strip(), parts[1].strip()

        # القنوات: كل a داخل live يحمل class يبدأ بـ chan_live_
        channels = []
        for a in live.select("a"):
            cls = " ".join(a.get("class", []))
            if "chan_live" in cls:
                nm = _norm(unescape(a.get_text(" ", strip=True)))
                if nm:
                    channels.append(nm)

        # المسابقة الأقرب
        comp_text = nearest_comp_text(container)

        results.append({
            "competition": comp_text,
            "fixture": fixture,
            "home": home, "away": away,
            "channels": [{"name": c} for c in channels]
        })

    return results

# ==============================
# YallaShoot part (كما هو مع تعديلات بسيطة)
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

    print(f"[found] {len(cards)} cards")

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
            "channel": [],  # سنملؤها من LiveOnSat
            "competition": c["competition"],
            "_source": "yalla1shoot"
        })

    # ===== قنوات LiveOnSat (خام كما هي) =====
    try:
        los_html = fetch_liveonsat_html()
        los_matches = parse_liveonsat(los_html)

        replaced = 0
        for m in out["matches"]:
            los_m = find_best_los_match(m["home"], m["away"], los_matches, threshold=0.72)
            chan_list = []
            if los_m:
                for ch in los_m.get("channels", []):
                    nm = (ch.get("name") or "").strip()
                    if nm:
                        chan_list.append(nm)

            # خاص: الدوري الإيطالي → أضف starzplay1 و starzplay2
            comp = m.get("competition", "") or ""
            if "إيطالي" in comp or "ايطالي" in comp:
                for sp in ("starzplay1", "starzplay2"):
                    if sp not in chan_list:
                        chan_list.append(sp)

            m["channel"] = chan_list
            if chan_list:
                replaced += 1
            else:
                print(f"[no-channels] {m['home']} vs {m['away']} (comp={comp})")

        print(f"[liveonsat] set channels for {replaced}/{len(out['matches'])} matches")
    except Exception as e:
        print("[liveonsat][warn]", e)

    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[write] {OUT_PATH} with {len(out['matches'])} matches.")

if __name__ == "__main__":
    scrape()

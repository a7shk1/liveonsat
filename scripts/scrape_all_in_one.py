# scripts/scrape_yallashoot_with_liveonsat.py
import os, json, datetime as dt, time, re
from pathlib import Path
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BAGHDAD_TZ = ZoneInfo("Asia/Baghdad")

# Yalla1Shoot
YS_URL = "https://www.yalla1shoot.com/matches-today_1/"
# LiveOnSat (عدّله إذا عندك صفحة ثانية)
LOS_URL = os.environ.get("LIVEON_URL") or "https://liveonsat.com/quick_guide_foot.php"

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "matches"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "today.json"

# ---------------------- Utilities ----------------------
AR_DIAC = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0670\u0640]")
SPACES = re.compile(r"\s+")
PUNCT = re.compile(r"[^\w\u0600-\u06FF]+")

def ar_norm(s: str) -> str:
    if not s: return ""
    s = AR_DIAC.sub("", s)
    s = s.replace("أ","ا").replace("إ","ا").replace("آ","ا").replace("ى","ي").replace("ة","ه").replace("ؤ","و").replace("ئ","ي")
    s = PUNCT.sub(" ", s)
    s = SPACES.sub(" ", s).strip().lower()
    return s

def en_norm(s: str) -> str:
    if not s: return ""
    s = PUNCT.sub(" ", s)
    s = SPACES.sub(" ", s).strip().lower()
    return s

def norm_team(s: str) -> str:
    # جرّب عربي أولاً ثم إنجليزي
    a = ar_norm(s)
    b = en_norm(s)
    return a if len(a) >= len(b) else b

def hhmm_to_minutes(hhmm: str) -> Optional[int]:
    if not hhmm: return None
    m = re.search(r"(\d{1,2}):(\d{2})", hhmm)
    if not m: return None
    h, mnt = int(m.group(1)), int(m.group(2))
    return h*60 + mnt

def minutes_close(a: Optional[int], b: Optional[int], tol: int = 15) -> bool:
    if a is None or b is None: 
        return True  # لو الوقت مش متوفر، نعتمد على الأسماء فقط
    return abs(a - b) <= tol

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

# ---------------------- Data classes ----------------------
@dataclass
class MatchRow:
    home: str
    away: str
    time_baghdad: str  # "HH:MM"
    home_logo: str = ""
    away_logo: str = ""
    status_text: str = ""
    result_text: str = ""
    competition: Optional[str] = None
    commentator: Optional[str] = None
    channel: Optional[str] = None  # (مصدر YS – راح نهمله)
    channels_raw: List[str] = None # (من LiveOnSat)
    status: str = "NS"

    def match_key(self) -> Tuple[str, str]:
        return (norm_team(self.home), norm_team(self.away))

# ---------------------- Scrapers ----------------------
def scrape_yalla1shoot(ctx) -> List[MatchRow]:
    page = ctx.new_page()
    page.set_default_timeout(60000)
    print("[open YS]", YS_URL)
    page.goto(YS_URL, wait_until="domcontentloaded", timeout=60000)
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
          home, away, homeLogo, awayLogo,
          time, result, status,
          channel, commentator, competition
        });
      });
      return cards;
    }
    """
    raw = page.evaluate(js)
    out = []
    for c in raw:
        row = MatchRow(
            home=c["home"],
            away=c["away"],
            home_logo=c["homeLogo"],
            away_logo=c["awayLogo"],
            time_baghdad=c["time"],
            status_text=c["status"],
            result_text=c["result"],
            competition=c["competition"] or None,
            commentator=c["commentator"] or None,
            channel=c["channel"] or None,
            channels_raw=[],
            status=normalize_status(c["status"])
        )
        out.append(row)
    page.close()
    print(f"[YS] matches: {len(out)}")
    return out

def scrape_liveonsat(ctx) -> List[Dict]:
    """
    يرجّع قائمة عناصر فيها:
    {
      'home': str, 'away': str, 'time_baghdad': 'HH:MM', 'channels': [..],
      'competition': str (اختياري)
    }
    ملاحظة: عدّل الـ selectors حسب صفحتك لو اختلفت.
    """
    page = ctx.new_page()
    page.set_default_timeout(60000)
    print("[open LOS]", LOS_URL)
    page.goto(LOS_URL, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=25000)
    except PWTimeout:
        pass

    gradual_scroll(page)

    # محاولة أولى: صفوف ضمن جدول سريع (quick guide)
    js1 = r"""
    () => {
      const rows = [];
      // كثير من صفحات LOS تبني جدول فيه فرق ووقت وقنوات في خلايا متجاورة
      const tables = Array.from(document.querySelectorAll('table'));
      const hourRe = /(\d{1,2}):(\d{2})/;

      tables.forEach(tb => {
        Array.from(tb.querySelectorAll('tr')).forEach(tr => {
          const tds = Array.from(tr.querySelectorAll('td'));
          if (tds.length < 3) return;

          const textCells = tds.map(td => td.textContent.trim().replace(/\s+/g, ' '));

          // heuristic: ابحث عن وقت + نص فيه "vs" أو " - "
          const timeCell = textCells.find(x => hourRe.test(x)) || "";
          let fixtureCell = textCells.find(x => /vs| v | - /.test(x.toLowerCase())) || "";
          if (!fixtureCell) {
            // أحياناً الفريقين بخلية منفصلة
            fixtureCell = textCells.join(" • ");
          }

          // القنوات: اجمع أي سبانات/صور عنوانها قناة، وإلا النص المتبقي
          const chanNodes = tr.querySelectorAll('a, span, img, b, strong, i, u');
          const chans = Array.from(chanNodes)
            .map(n => (n.getAttribute?.('title') || n.textContent || '').trim())
            .map(s => s.replace(/\s+/g,' '))
            .filter(s => s && s.length > 1)
            .filter(s => !hourRe.test(s))  // استبعد الأوقات
            .filter(s => !/vs| v | - /.test(s.toLowerCase())); // استبعد fixture

          // استخرج الفرق
          let home = "", away = "";
          const splitters = [" vs ", " v ", " - ", "–", "—", " — ", " – "];
          for (const sp of splitters) {
            if (fixtureCell.toLowerCase().includes(sp.strip?.() || sp)) {
              const parts = fixtureCell.split(sp);
              if (parts.length >= 2) {
                home = parts[0].trim();
                away = parts[1].trim();
                break;
              }
            }
          }
          if (!home || !away) {
            // fallback بسيط: التقط أول كلمتين كبيرتين بينهما فاصل
            const m = fixtureCell.match(/([^\|•]+)[\|•-]+([^\|•]+)/);
            if (m) { home = m[1].trim(); away = m[2].trim(); }
          }

          // الوقت (Baghdad): نفترض الصفحة تعرض توقيت محلي ثابت، إن أردت ممكن تغيّر timezone في context
          const time = (timeCell.match(hourRe)?.[0]) || "";

          if (home && away && time) {
            rows.push({
              home, away,
              time_baghdad: time,
              channels: Array.from(new Set(chans)).slice(0, 40) // سقف معقول
            });
          }
        });
      });
      return rows;
    }
    """

    rows = page.evaluate(js1)
    page.close()
    # تصفية أي عناصر مضروبة
    clean = []
    for r in rows:
        if not r.get("home") or not r.get("away"): 
            continue
        # فلترة "online", "geo", إلخ تبقى بالنص كما هي — القرار لك لاحقاً
        chans = [c for c in r.get("channels", []) if len(c) >= 2]
        if not chans:
            continue
        clean.append({
            "home": r["home"],
            "away": r["away"],
            "time_baghdad": r.get("time_baghdad",""),
            "channels": chans
        })
    print(f"[LOS] rows: {len(clean)}")
    return clean

# ---------------------- Merge Logic ----------------------
def merge_channels(ys_matches: List[MatchRow], los_rows: List[Dict]) -> None:
    """
    يدمج القنوات من LiveOnSat إلى كل مباراة قادمة من Yalla1Shoot
    التطابق: أسماء الفرق (مع التطبيع) + الوقت ضمن ±15 دقيقة
    """
    # ابنِ فهارس سريعة لـ LOS
    index: Dict[Tuple[str,str], List[Dict]] = {}
    for r in los_rows:
        k = (norm_team(r["home"]), norm_team(r["away"]))
        index.setdefault(k, []).append(r)
        # أحياناً LOS يعكس الترتيب
        k2 = (norm_team(r["away"]), norm_team(r["home"]))
        index.setdefault(k2, []).append({
            "home": r["away"], "away": r["home"],
            "time_baghdad": r["time_baghdad"], "channels": r["channels"]
        })

    for m in ys_matches:
        key = m.match_key()
        m_min = hhmm_to_minutes(m.time_baghdad)
        candidates = index.get(key, [])
        channels_accum: List[str] = []

        for cand in candidates:
            c_min = hhmm_to_minutes(cand.get("time_baghdad",""))
            if minutes_close(m_min, c_min, tol=15):
                channels_accum.extend(cand.get("channels", []))

        # dedup & normalize بسيط
        seen = set()
        deduped = []
        for ch in channels_accum:
            ch_clean = SPACES.sub(" ", ch.strip())
            if ch_clean.lower() in seen: 
                continue
            seen.add(ch_clean.lower())
            deduped.append(ch_clean)

        m.channels_raw = deduped

# ---------------------- Main ----------------------
def run():
    today = dt.datetime.now(BAGHDAD_TZ).date().isoformat()
    url_override = os.environ.get("FORCE_URL") or YS_URL

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1366, "height": 864},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36",
            locale="ar",
            timezone_id="Asia/Baghdad",
        )

        # 1) سحب يلا شوت
        ys_matches = scrape_yalla1shoot(ctx)

        # 2) سحب LiveOnSat (قنوات)
        los_rows = scrape_liveonsat(ctx)

        browser.close()

    # 3) دمج
    merge_channels(ys_matches, los_rows)

    # 4) تجهيز JSON النهائي
    out = {
        "date": today,
        "source_url": url_override,
        "matches": []
    }
    for m in ys_matches:
        mid = f"{(m.home or '')[:12]}-{(m.away or '')[:12]}-{today}".replace(" ", "")
        out["matches"].append({
            "id": mid,
            "home": m.home, "away": m.away,
            "home_logo": m.home_logo, "away_logo": m.away_logo,
            "time_baghdad": m.time_baghdad,
            "status": m.status,
            "status_text": m.status_text,
            "result_text": m.result_text,
            # ⚠️ القنوات الآن حصراً من LiveOnSat
            "channels_raw": m.channels_raw or [],
            "channel": [],  # فارغة دائماً حتى ما نخلط مصادر
            "commentator": m.commentator,
            "competition": m.competition,
            "_source": "yalla1shoot+liveonsat"
        })

    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[write] {OUT_PATH} with {len(out['matches'])} matches.")

if __name__ == "__main__":
    run()

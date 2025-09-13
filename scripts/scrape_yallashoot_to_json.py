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

# ===================== قنواتك الحرفية =====================
CHANNEL_CANON = [
    "starzplay1","starzplay2",
    "abudhabi sport 1","abudhabi sport 2",
    "beIN SPORTS 1","beIN SPORTS 2","beIN SPORTS 3","beIN SPORTS 4",
    "beIN SPORTS 5","beIN SPORTS 6","beIN SPORTS 7","beIN SPORTS 8","beIN SPORTS 9",
    "DAZN 1","DAZN 2","DAZN 3","DAZN 4","DAZN 5","DAZN 6",
    "ESPN","ESPN 2","ESPN 3","ESPN 4","ESPN 5","ESPN 6","ESPN 7",
    "Varzesh TV Iran","Varzish TV Tajikistan","Football HD Tajikistan","IRIB TV 3 Iran","Persiana Sports Iran",
    "Match! Futbol 1","Match! Futbol 2","Match! Futbol 3","Match! TV Russia",
    "Sport TV 1","Sport TV 2",
    "mbc Action","MBC Drama+","MBC Drama","mbc masr","mbc masr2",
    "TNT SPORTS","TNT SPORTS 1","TNT SPORTS 2","Sky Sports Main Event HD","Sky Premier League HD",
    "SSC 1","SSC 2","Thmanyah 1","Thmanyah 2","Thmanyah 3",
]

# أنماط تحويل أسماء LiveOnSat إلى أسمائك
CHANNEL_PATTERNS = []
for i in range(1,10):
    CHANNEL_PATTERNS.append((re.compile(rf"(?i)\bbeIN\s*Sports?\s*(?:HD\s*)?{i}\b.*"), f"beIN SPORTS {i}"))
for i in range(1,7):
    CHANNEL_PATTERNS.append((re.compile(rf"(?i)\bDAZN\s*{i}\b.*"), f"DAZN {i}"))
CHANNEL_PATTERNS.append((re.compile(r"(?i)\bESPN\b(?!\s*\d)"), "ESPN"))
for i in range(2,8):
    CHANNEL_PATTERNS.append((re.compile(rf"(?i)\bESPN\s*{i}\b"), f"ESPN {i}"))
CHANNEL_PATTERNS += [
    (re.compile(r"(?i)\bVarzesh\b.*"), "Varzesh TV Iran"),
    (re.compile(r"(?i)\bVarzish\b.*"), "Varzish TV Tajikistan"),
    (re.compile(r"(?i)\bFootball\s*HD\b.*Tajikistan\b"), "Football HD Tajikistan"),
    (re.compile(r"(?i)\bIRIB\s*TV\s*3\b"), "IRIB TV 3 Iran"),
    (re.compile(r"(?i)\bPersiana\b.*Sports\b"), "Persiana Sports Iran"),
    (re.compile(r"(?i)\bMatch!?[\s\-]*Futbol\s*1\b.*"), "Match! Futbol 1"),
    (re.compile(r"(?i)\bMatch!?[\s\-]*Futbol\s*2\b.*"), "Match! Futbol 2"),
    (re.compile(r"(?i)\bMatch!?[\s\-]*Futbol\s*3\b.*"), "Match! Futbol 3"),
    (re.compile(r"(?i)\bMatch!?[\s\-]*TV\b.*"), "Match! TV Russia"),
    (re.compile(r"(?i)\bSport\s*TV\s*1\b.*"), "Sport TV 1"),
    (re.compile(r"(?i)\bSport\s*TV\s*2\b.*"), "Sport TV 2"),
    (re.compile(r"(?i)\bMBC\s*Action\b"), "mbc Action"),
    (re.compile(r"(?i)\bMBC\s*Drama\+\b"), "MBC Drama+"),
    (re.compile(r"(?i)\bMBC\s*Drama\b"), "MBC Drama"),
    (re.compile(r"(?i)\bMBC\s*Masr\s*2\b"), "mbc masr2"),
    (re.compile(r"(?i)\bMBC\s*Masr\b"), "mbc masr"),
    (re.compile(r"(?i)\bTNT\s*Sports?\b(?!\s*\d)"), "TNT SPORTS"),
    (re.compile(r"(?i)\bTNT\s*Sports?\s*1\b"), "TNT SPORTS 1"),
    (re.compile(r"(?i)\bTNT\s*Sports?\s*2\b"), "TNT SPORTS 2"),
    (re.compile(r"(?i)\bSky\s*Sports?\s*Main\s*Event\b.*"), "Sky Sports Main Event HD"),
    (re.compile(r"(?i)\bSky\s*(?:Sports?\s*)?Premier\s*League\b.*"), "Sky Premier League HD"),
    (re.compile(r"(?i)\bSSC\s*1\b.*"), "SSC 1"),
    (re.compile(r"(?i)\bSSC\s*2\b.*"), "SSC 2"),
    (re.compile(r"(?i)\bThmanyah\s*1\b.*"), "Thmanyah 1"),
    (re.compile(r"(?i)\bThmanyah\s*2\b.*"), "Thmanyah 2"),
    (re.compile(r"(?i)\bThmanyah\s*3\b.*"), "Thmanyah 3"),
    (re.compile(r"(?i)\bAbu\s*Dhabi\b.*\bSports?\s*1\b.*"), "abudhabi sport 1"),
    (re.compile(r"(?i)\bAbu\s*Dhabi\b.*\bSports?\s*2\b.*"), "abudhabi sport 2"),
    (re.compile(r"(?i)\bStarz\s*Play\b.*\b1\b.*|\bSTARZPLAY\b.*\b1\b.*"), "starzplay1"),
    (re.compile(r"(?i)\bStarz\s*Play\b.*\b2\b.*|\bSTARZPLAY\b.*\b2\b.*"), "starzplay2"),
]

def map_channel_to_canonical(los_name: str) -> str | None:
    for pat, canon in CHANNEL_PATTERNS:
        if pat.search(los_name or ""):
            return canon
    return None

# ===================== LiveOnSat utils =====================
def _session_with_retries():
    s = requests.Session()
    retry = Retry(total=5, connect=5, read=5, status=5,
                  backoff_factor=1.2,
                  status_forcelist=[429,500,502,503,504],
                  allowed_methods=frozenset(["GET","HEAD"]),
                  raise_on_status=False)
    ad = HTTPAdapter(max_retries=retry)
    s.mount("http://", ad); s.mount("https://", ad)
    s.headers.update({"User-Agent":"Mozilla/5.0"})
    return s

def fetch_liveonsat_html():
    url = os.environ.get("LOS_URL","https://liveonsat.com/2day.php")
    s = _session_with_retries()
    r = s.get(url,timeout=(10,60)); r.raise_for_status(); return r.text

def _normspace(s:str)->str: return re.sub(r"\s+"," ",(s or "").strip())
def _strip_tags(s:str)->str: return re.sub(r"<[^>]+>","",s or "")

def parse_liveonsat_basic(html:str):
    results=[]
    comp_pat=re.compile(r'<span\s+class="comp_head">(?P<comp>.*?)</span>',re.S)
    for m in comp_pat.finditer(html):
        comp=_strip_tags(m.group("comp"))
        start=m.end(); nxt=comp_pat.search(html,start)
        end=nxt.start() if nxt else len(html); block=html[start:end]
        tm=re.search(r'<div\s+class="fLeft"[^>]*?>\s*([^<]*\sv\s[^<]*)</div>',block)
        fixture=_normspace(unescape(_strip_tags(tm.group(1))) if tm else "")
        home=away=""
        if " v " in fixture:
            parts=[p.strip() for p in fixture.split(" v ",1)]
            if len(parts)==2: home,away=parts
        channels=[]
        for live_area in re.finditer(r'<div\s+class="fLeft_live"[^>]*?>(?P<html>.*?)</div>',block,re.S):
            area=live_area.group("html")
            for a in re.finditer(r'<a[^>]+class="chan_live_(?P<ctype>[^"]+)"[^>]*?>(?P<text>.*?)</a>',area,re.S):
                name=_normspace(unescape(_strip_tags(a.group("text"))))
                if name: channels.append({"name":name})
        results.append({"competition":comp,"fixture":fixture,"home":home,"away":away,"channels":channels})
    return results

def _normalize_team(s:str)->str:
    s=s or ""; s=unicodedata.normalize("NFKD",s)
    s="".join(ch for ch in s if not unicodedata.combining(ch))
    s=s.lower(); s=re.sub(r"[^a-z0-9]+"," ",s).strip()
    return re.sub(r"\s+"," ",s)

TEAM_MAP_AR2EN={"أتلتيك بلباو":"Athletic Bilbao","ألافيس":"Alaves","برشلونة":"Barcelona","ريال مدريد":"Real Madrid","ريال سوسيداد":"Real Sociedad"}

def _to_en(name:str)->str:
    if re.search(r"[\u0600-\u06FF]",name or ""): return TEAM_MAP_AR2EN.get(name,name)
    return name

def _similar(a:str,b:str)->float: return SequenceMatcher(None,a,b).ratio()

def find_best_los_match(y_home,y_away,los_matches,threshold=0.8):
    yh,ya=_normalize_team(_to_en(y_home)),_normalize_team(_to_en(y_away))
    best,best_score=None,-1.0
    for m in los_matches:
        lh,la=_normalize_team(m.get("home","")),_normalize_team(m.get("away",""))
        score=max(_similar(f"{yh} {ya}",f"{lh} {la}"),_similar(f"{yh} {ya}",_normalize_team(m.get("fixture",""))))
        if score>best_score: best,best_score=m,score
    return best if best_score>=threshold else None

# ===================== Scraper =====================
def gradual_scroll(page, step=900, pause=0.25):
    last_h=0
    while True:
        h=page.evaluate("() => document.body.scrollHeight")
        if h<=last_h: break
        for y in range(0,h,step):
            page.evaluate(f"window.scrollTo(0, {y});"); time.sleep(pause)
        last_h=h

def scrape():
    url=os.environ.get("FORCE_URL") or DEFAULT_URL
    today=dt.datetime.now(BAGHDAD_TZ).date().isoformat()

    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        ctx=browser.new_context(
            viewport={"width":1366,"height":864},
            user_agent="Mozilla/5.0",
            locale="ar",
            timezone_id="Asia/Baghdad",
        )
        page=ctx.new_page(); page.set_default_timeout(60000)
        print("[open]",url); page.goto(url,wait_until="domcontentloaded",timeout=60000)
        try: page.wait_for_load_state("networkidle",timeout=20000)
        except PWTimeout: pass
        gradual_scroll(page)
        js=r"""
        () => {
          const cards = [];
          document.querySelectorAll('.AY_Inner').forEach((inner) => {
            const root = inner.parentElement || inner;
            const qText = (sel) => { const el=root.querySelector(sel); return el?el.textContent.trim():""; };
            const qAttr = (sel,attr) => { const el=root.querySelector(sel); return el?(el.getAttribute(attr)||el.getAttribute('data-'+attr)||""):""; };
            const home=qText('.MT_Team.TM1 .TM_Name');
            const away=qText('.MT_Team.TM2 .TM_Name');
            const homeLogo=qAttr('.MT_Team.TM1 .TM_Logo img','src')||qAttr('.MT_Team.TM1 .TM_Logo img','data-src');
            const awayLogo=qAttr('.MT_Team.TM2 .TM_Logo img','src')||qAttr('.MT_Team.TM2 .TM_Logo img','data-src');
            const time=qText('.MT_Data .MT_Time');
            const result=qText('.MT_Data .MT_Result');
            const status=qText('.MT_Data .MT_Stat');
            const infoLis=Array.from(root.querySelectorAll('.MT_Info li span')).map(x=>x.textContent.trim());
            const competition=infoLis[2]||"";
            cards.push({home,away,home_logo:homeLogo,away_logo:awayLogo,time_local:time,result_text:result,status_text:status,competition});
          }); return cards;
        }
        """
        cards=page.evaluate(js); browser.close()

    def normalize_status(ar_text:str)->str:
        t=(ar_text or "").strip()
        if not t: return "NS"
        if "انتهت" in t: return "FT"
        if "مباشر" in t or "الشوط" in t: return "LIVE"
        if "لم" in t and "تبدأ" in t: return "NS"
        return "NS"

    out={"date":today,"source_url":url,"matches":[]}
    for c in cards:
        mid=f"{c['home'][:12]}-{c['away'][:12]}-{today}".replace(" ","")
        out["matches"].append({
            "id":mid,"home":c["home"],"away":c["away"],
            "home_logo":c["home_logo"],"away_logo":c["away_logo"],
            "time_baghdad":c["time_local"],
            "status":normalize_status(c["status_text"]),
            "status_text":c["status_text"],"result_text":c["result_text"],
            "channel":[], # نملأها من LiveOnSat
            "competition":c["competition"],"_source":"yalla1shoot"
        })

    # ======== إحلال القنوات من LiveOnSat ========
    try:
        los_html=fetch_liveonsat_html(); los_list=parse_liveonsat_basic(los_html)
        replaced=0
        for m in out["matches"]:
            los_m=find_best_los_match(m["home"],m["away"],los_list,threshold=0.8)
            chan_set=[]
            if los_m:
                seen=set()
                for ch in los_m.get("channels",[]):
                    canon=map_channel_to_canonical(ch.get("name",""))
                    if canon and canon in CHANNEL_CANON and canon not in seen:
                        seen.add(canon); chan_set.append(canon)
            m["channel"]=chan_set
            if chan_set: replaced+=1
        print(f"[liveonsat] replaced channels for {replaced}/{len(out['matches'])} matches")
    except Exception as e:
        print(f"[liveonsat][warn]",e)

    with OUT_PATH.open("w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2)
    print(f"[write] {OUT_PATH} with {len(out['matches'])} matches.")

if __name__=="__main__":
    scrape()

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
# قنواتك الحرفية (هي المرجع)
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

# ======================================================
# دالة تطبيع أسماء القنوات → تعيد الاسم الحرفي من لستتك
def map_channel_to_canonical(los_name: str) -> str | None:
    if not los_name:
        return None
    name = los_name.lower()

    # شيل كلمات إضافية
    junk_words = ["hd","mena","portugal","france","usa","premium",
                  "plus","deutsch","geo","malaysia","brazil","life","alb","albania"]
    for jw in junk_words:
        name = name.replace(jw,"")
    name = re.sub(r"[^a-z0-9]+"," ",name).strip()

    # beIN
    if "bein" in name:
        m = re.search(r"\b(\d{1,2})\b",name)
        if m: return f"beIN SPORTS {m.group(1)}"
        return "beIN SPORTS 1"

    # DAZN
    if "dazn" in name:
        m = re.search(r"\b(\d{1,2})\b",name)
        if m: return f"DAZN {m.group(1)}"
        return "DAZN 1"

    # ESPN
    if "espn" in name:
        m = re.search(r"\b(\d{1,2})\b",name)
        if m: return f"ESPN {m.group(1)}"
        return "ESPN"

    # Sky
    if "sky" in name and "premier" in name:
        return "Sky Premier League HD"
    if "sky" in name and "main" in name:
        return "Sky Sports Main Event HD"

    # SSC
    if "ssc" in name:
        m = re.search(r"\b(\d)\b",name)
        if m: return f"SSC {m.group(1)}"

    # Thmanyah
    if "thmanyah" in name:
        m = re.search(r"\b(\d)\b",name)
        if m: return f"Thmanyah {m.group(1)}"

    # Abu Dhabi
    if "abu" in name and "dhabi" in name:
        if "1" in name: return "abudhabi sport 1"
        if "2" in name: return "abudhabi sport 2"

    # Varzesh / Varzish / IRIB / Persiana
    if "varzesh" in name: return "Varzesh TV Iran"
    if "varzish" in name: return "Varzish TV Tajikistan"
    if "football" in name: return "Football HD Tajikistan"
    if "irib" in name and "3" in name: return "IRIB TV 3 Iran"
    if "persiana" in name: return "Persiana Sports Iran"

    # Match! الروسية
    if "match" in name and "futbol" in name:
        m = re.search(r"\b(\d)\b",name)
        if m: return f"Match! Futbol {m.group(1)}"
    if "match" in name and "tv" in name:
        return "Match! TV Russia"

    # Sport TV
    if "sport tv" in name:
        m = re.search(r"\b(\d)\b",name)
        if m: return f"Sport TV {m.group(1)}"

    # MBC
    if "mbc" in name and "action" in name: return "mbc Action"
    if "mbc" in name and "drama+" in name: return "MBC Drama+"
    if "mbc" in name and "drama" in name: return "MBC Drama"
    if "mbc" in name and "masr2" in name: return "mbc masr2"
    if "mbc" in name and "masr" in name: return "mbc masr"

    # TNT
    if "tnt" in name:
        m = re.search(r"\b(\d)\b",name)
        if m: return f"TNT SPORTS {m.group(1)}"
        return "TNT SPORTS"

    return None

# ======================================================
# LiveOnSat utils
def _session_with_retries():
    s=requests.Session()
    retry=Retry(total=5,connect=5,read=5,status=5,backoff_factor=1.2,
                status_forcelist=[429,500,502,503,504],
                allowed_methods=frozenset(["GET","HEAD"]),
                raise_on_status=False)
    ad=HTTPAdapter(max_retries=retry)
    s.mount("http://",ad); s.mount("https://",ad)
    s.headers.update({"User-Agent":"Mozilla/5.0"})
    return s

def fetch_liveonsat_html():
    url=os.environ.get("LOS_URL","https://liveonsat.com/2day.php")
    s=_session_with_retries()
    r=s.get(url,timeout=(10,60)); r.raise_for_status(); return r.text

def _normspace(s): return re.sub(r"\s+"," ",(s or "").strip())
def _strip_tags(s): return re.sub(r"<[^>]+>","",s or "")

def parse_liveonsat_basic(html):
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
            for a in re.finditer(r'<a[^>]+class="chan_live_.*?"[^>]*?>(?P<text>.*?)</a>',area,re.S):
                name=_normspace(unescape(_strip_tags(a.group("text"))))
                if name: channels.append({"name":name})
        results.append({"competition":comp,"fixture":fixture,"home":home,"away":away,"channels":channels})
    return results

def _normalize_team(s):
    s=s or ""; s=unicodedata.normalize("NFKD",s)
    s="".join(ch for ch in s if not unicodedata.combining(ch))
    s=s.lower(); s=re.sub(r"[^a-z0-9]+"," ",s).strip()
    return re.sub(r"\s+"," ",s)

TEAM_MAP_AR2EN={"أتلتيك بلباو":"Athletic Bilbao","ألافيس":"Alaves","برشلونة":"Barcelona","ريال مدريد":"Real Madrid","ريال سوسيداد":"Real Sociedad","الهلال":"Al Hilal","القادسية":"Al Qadisiyah"}

def _to_en(name): return TEAM_MAP_AR2EN.get(name.strip(),name.strip())

def _similar(a,b): return SequenceMatcher(None,a,b).ratio()

def find_best_los_match(y_home,y_away,los_matches,threshold=0.8):
    yh,ya=_normalize_team(_to_en(y_home)),_normalize_team(_to_en(y_away))
    best,best_score=None,-1.0
    for m in los_matches:
        lh,la=_normalize_team(m.get("home","")),_normalize_team(m.get("away",""))
        score=max(_similar(f"{yh} {ya}",f"{lh} {la}"),_similar(f"{yh} {ya}",_normalize_team(m.get("fixture",""))))
        if score>best_score: best,best_score=m,score
    return best if best_score>=threshold else None

# ======================================================
# Scraper (YallaShoot)
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
            "channel":[], # نعبيها من LiveOnSat
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

            # 👇 خاص: إذا المباراة من الدوري الإيطالي → أضف starzplay1 و starzplay2
            if m.get("competition") and "ايطالي" in m["competition"]:
                for sp in ["starzplay1","starzplay2"]:
                    if sp not in chan_set:
                        chan_set.append(sp)

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

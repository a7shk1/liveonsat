# scripts/scrape_all_in_one.py
# سكربت واحد:
# 1) يحاول يجلب مباريات اليوم من يلا شوت (اختياري).
# 2) يجلب قنوات كل مباراة من LiveOnSat (2day.php) ويطابقها.
# 3) إذا يلا شوت فاضي، يبني المباريات من LiveOnSat مباشرةً.
# 4) يضيف channels_raw (بالضبط مثل الموقع) + channel (تطابق ذكي مع قنواتك).
# 5) يضيف starzplay1 و starzplay2 لكل مباراة بالدوري الإيطالي.

import json, os, re, time
from pathlib import Path
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "matches"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "today.json"

YALLA_URL_DEFAULT = "https://www.yalla1shoot.com/matches-today_1/"
YALLA_URL = os.environ.get("FORCE_URL") or YALLA_URL_DEFAULT
LIVE_URL = "https://liveonsat.com/2day.php"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
HDRS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ar;q=0.8", "Referer": "https://liveonsat.com/", "Cache-Control": "no-cache"}

# ====== أدوات عامة ======
def _clean_spaces(s: str) -> str:
    s = (s or "").strip()
    return re.sub(r"\s+", " ", s)

def _norm(s: str) -> str:
    s = (s or "")
    s = re.sub(r"[^\w\s+!?.-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()

def time_to_minutes(t: str | None) -> int | None:
    if not t: return None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", t)
    if not m: return None
    return int(m.group(1)) * 60 + int(m.group(2))

def normalize_time_to_baghdad(t):
    s = (t or "").strip()
    if not s: return ""
    m = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm|AM|PM)?", s)
    if not m: return ""
    hh, mm, ap = m.group(1), m.group(2), m.group(3)
    h = int(hh)
    if ap:
        ap = ap.lower()
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
    return f"{h:02d}:{mm}"

def fetch_requests(url: str, headers=None, timeout=45):
    r = requests.get(url, headers=headers or HDRS, timeout=timeout)
    r.raise_for_status()
    return r.text

def fetch_playwright(url: str, locale="en-GB", timeout_ms=45000):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(user_agent=UA, locale=locale)
        page = ctx.new_page()
        page.set_default_timeout(timeout_ms)
        page.goto(url, wait_until="domcontentloaded")
        html = page.content()
        ctx.close()
        browser.close()
        return html

def safe_get_html(url, use_requests_first=True):
    try:
        if use_requests_first:
            return fetch_requests(url)
        else:
            return fetch_playwright(url)
    except Exception as e1:
        try:
            return fetch_playwright(url)
        except Exception as e2:
            raise RuntimeError(f"Failed to fetch {url}: {e1} / {e2}")

# ====== خرائط الأندية (عربي → إنجليزي مبسّط) ======
ALIASES = {
    # England
    "أرسنال":"Arsenal","تشيلسي":"Chelsea","مانشستر سيتي":"Manchester City","مانشستر يونايتد":"Manchester United",
    "ليفربول":"Liverpool","توتنهام":"Tottenham","نيوكاسل":"Newcastle United","وست هام يونايتد":"West Ham",
    "برينتفورد":"Brentford","برايتون":"Brighton","بورنموث":"Bournemouth","ليستر سيتي":"Leicester","إيفرتون":"Everton",
    "وولفرهامبتون":"Wolves","أستون فيلا":"Aston Villa","نوتنغهام فورست":"Nottingham Forest","كريستال بالاس":"Crystal Palace","فولهام":"Fulham",
    # Spain
    "ريال مدريد":"Real Madrid","برشلونة":"Barcelona","أتلتيكو مدريد":"Atletico Madrid","إشبيلية":"Sevilla","فالنسيا":"Valencia","فياريال":"Villarreal",
    "أتلتيك بلباو":"Athletic Bilbao","ريال سوسييداد":"Real Sociedad","ريال بيتيس":"Real Betis","ألافيس":"Alaves","بلد الوليد":"Valladolid","ألميريا":"Almeria",
    # Italy
    "يوفنتوس":"Juventus","إنتر ميلان":"Inter Milan","انتر ميلان":"Inter Milan","إنتر":"Inter","ميلان":"AC Milan","إيه سي ميلان":"AC Milan",
    "نابولي":"Napoli","روما":"Roma","لاتسيو":"Lazio","فيورنتينا":"Fiorentina","أتلانتا":"Atalanta","بولونيا":"Bologna","تورينو":"Torino","أودينيزي":"Udinese",
    "جنوى":"Genoa","كالياري":"Cagliari","إمبولي":"Empoli","مونزا":"Monza","ليتشي":"Lecce","فيرونا":"Verona","بارما":"Parma","كومو":"Como",
    # France
    "باريس سان جيرمان":"PSG","باريس سان-جيرمان":"PSG","مارسيليا":"Marseille","ليون":"Lyon","ليل":"Lille","موناكو":"Monaco","نيس":"Nice",
    # Germany
    "بايرن ميونخ":"Bayern Munich","بوروسيا دورتموند":"Borussia Dortmund","لايبزيج":"RB Leipzig","لايبزيغ":"RB Leipzig","باير ليفركوزن":"Bayer Leverkusen",
    "شتوتجارت":"Stuttgart","فولفسبورج":"Wolfsburg","هوفنهايم":"Hoffenheim","فرايبورج":"Freiburg","مونشنغلادباخ":"Monchengladbach","يونيون برلين":"Union Berlin",
    "آينتراخت فرانكفورت":"Eintracht Frankfurt","هامبورج":"Hamburg",
    # Saudi
    "الهلال":"Al Hilal","النصر":"Al Nassr","الاتحاد":"Al Ittihad","الأهلي":"Al Ahli","القادسية":"Al Qadsiah",
}

ITALY_TEAMS = {
    "Juventus","Inter","Inter Milan","AC Milan","Milan","Napoli","Roma","Lazio","Fiorentina","Atalanta","Bologna","Torino","Udinese",
    "Genoa","Cagliari","Empoli","Monza","Lecce","Verona","Parma","Como"
}

# ====== قنواتك + التطابق الذكي ======
MY_CHANNELS = [
    "starzplay1","starzplay2",
    "abudhabi sport 1","abudhabi sport 2",
    "beIN SPORTS 1","beIN SPORTS 2","beIN SPORTS 3","beIN SPORTS 4","beIN SPORTS 5","beIN SPORTS 6","beIN SPORTS 7","beIN SPORTS 8","beIN SPORTS 9",
    "DAZN 1","DAZN 2","DAZN 3","DAZN 4","DAZN 5","DAZN 6",
    "ESPN","ESPN 2","ESPN 3","ESPN 4","ESPN 5","ESPN 6","ESPN 7",
    "Varzesh TV Iran","Varzish TV Tajikistan","Football HD Tajikistan","IRIB TV 3 Iran","Persiana Sports Iran",
    "Match! Futbol 1","Match! Futbol 2","Match! Futbol 3","Match! TV Russia",
    "Sport TV 1","Sport TV 2",
    "mbc Action","MBC Drama+","MBC Drama","mbc masr","mbc masr2",
    "TNT SPORTS","TNT SPORTS 1","TNT SPORTS 2",
    "Sky Sports Main Event HD","Sky Premier League HD",
    "SSC 1","SSC 2",
    "Thmanyah 1","Thmanyah 2","Thmanyah 3",
]
MY_SET = {_norm(x) for x in MY_CHANNELS}

def map_liveonsat_to_mine(name: str) -> str | None:
    n = _norm(name or "")
    # beIN
    m = re.search(r"\bbein\s+sports?\b.*?(\d{1,2})\b", n)
    if m:
        cand = f"beIN SPORTS {m.group(1)}"
        return cand if _norm(cand) in MY_SET else None
    # DAZN
    m = re.search(r"\bdazn\b\s*(\d)\b", n)
    if m:
        cand = f"DAZN {m.group(1)}"
        return cand if _norm(cand) in MY_SET else None
    # ESPN
    m = re.search(r"\bespn\b(?:\s*(\d))?", n)
    if m:
        num = m.group(1)
        cand = f"ESPN {num}" if num else "ESPN"
        return cand if _norm(cand) in MY_SET else None
    # طاجيك/إيران
    if "varzish" in n:
        cand = "Varzish TV Tajikistan"
        return cand if _norm(cand) in MY_SET else None
    if "varzesh" in n or "irib varzesh" in n:
        cand = "Varzesh TV Iran"
        return cand if _norm(cand) in MY_SET else None
    if "irib" in n and ("tv 3" in n or "tv3" in n or "channel 3" in n):
        cand = "IRIB TV 3 Iran"
        return cand if _norm(cand) in MY_SET else None
    if "football hd" in n and ("tjk" in n or "tajik" in n):
        cand = "Football HD Tajikistan"
        return cand if _norm(cand) in MY_SET else None
    if "persiana" in n:
        cand = "Persiana Sports Iran"
        return cand if _norm(cand) in MY_SET else None
    # Match الروسية
    if "match" in n and "futbol" in n:
        m = re.search(r"futbol\s*(\d)", n)
        if m:
            cand = f"Match! Futbol {m.group(1)}"
            return cand if _norm(cand) in MY_SET else None
    if n.startswith("match") and "tv" in n:
        cand = "Match! TV Russia"
        return cand if _norm(cand) in MY_SET else None
    # Sport TV PT
    m = re.search(r"\bsport\s*tv\s*(\d)\b", n)
    if m:
        cand = f"Sport TV {m.group(1)}"
        return cand if _norm(cand) in MY_SET else None
    # Sky
    if "sky sports main event" in n:
        cand = "Sky Sports Main Event HD"
        return cand if _norm(cand) in MY_SET else None
    if "sky sports premier league" in n or "sky sport premier league" in n:
        cand = "Sky Premier League HD"
        return cand if _norm(cand) in MY_SET else None
    # TNT
    if n.startswith("tnt sports"):
        m = re.search(r"\btnt\s*sports\s*(\d)\b", n)
        cand = f"TNT SPORTS {m.group(1)}" if m else "TNT SPORTS"
        return cand if _norm(cand) in MY_SET else None
    # SSC
    if n.startswith("ssc"):
        m = re.search(r"\bssc\s*(\d)\b", n)
        if m:
            cand = f"SSC {m.group(1)}"
            return cand if _norm(cand) in MY_SET else None
    # MBC
    if "mbc action" in n: return "mbc Action"
    if "mbc drama+" in n or "mbc drama plus" in n: return "MBC Drama+"
    if re.search(r"\bmbc\s+drama\b", n): return "MBC Drama"
    if "mbc masr 2" in n or "masr 2" in n: return "mbc masr2"
    if "mbc masr" in n: return "mbc masr"
    # Thmanyah
    if n.startswith("thmanyah"):
        m = re.search(r"\bthmanyah\s*(\d)\b", n)
        if m:
            cand = f"Thmanyah {m.group(1)}"
            return cand if _norm(cand) in MY_SET else None
    # AbuDhabi
    if "abudhabi sport 1" in n or "abu dhabi sport 1" in n: return "abudhabi sport 1"
    if "abudhabi sport 2" in n or "abu dhabi sport 2" in n: return "abudhabi sport 2"
    return None

# ====== Parser: YallaShoot (اختياري) ======
def parse_yalla(html: str):
    # نحاول التقاط كروت تحتوي فريقين ووقت
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    blocks = soup.select(".match-card, .match, .single-match, .game, .item, .live-match") or soup.select("article, li, div.card, div.box, div.row")
    for el in blocks:
        txt = _clean_spaces(el.get_text(" "))
        if not (":" in txt and re.search(r"[\u0600-\u06FF]", txt)):
            continue
        # فرق
        names = []
        for node in el.select("a, span, div, h3, h2"):
            t = _clean_spaces(node.get_text())
            if t and len(t) <= 40 and re.search(r"[\u0600-\u06FF]", t):
                names.append(t)
        names = list(dict.fromkeys(names))
        home = names[0] if len(names) >= 1 else ""
        away = names[1] if len(names) >= 2 else ""
        if not home or not away: 
            m = re.search(r"([\u0600-\u06FF][\u0600-\u06FF\s]+)\s*[-–]\s*([\u0600-\u06FF][\u0600-\u06FF\s]+)", txt)
            if m:
                home, away = m.group(1).strip(), m.group(2).strip()
        if not home or not away:
            continue
        # وقت
        mtime = re.search(r"(\d{1,2}:\d{2}\s*(AM|PM|am|pm)?)", txt)
        time_bgd = normalize_time_to_baghdad(mtime.group(1)) if mtime else ""
        # بطولة
        comp = ""
        comp_node = el.select_one("small, .comp, .league, .tournament, .competition")
        if comp_node: comp = _clean_spaces(comp_node.get_text())
        if not comp:
            mcomp = re.search(r"(الدوري|كأس|السوبر|تصفيات|ودية)[\u0600-\u06FF\s,]+", txt)
            if mcomp: comp = _clean_spaces(mcomp.group(0))
        # شعارات (اختياري)
        imgs = [img.get("src","") for img in el.select("img")]
        home_logo = imgs[0] if len(imgs) > 0 else ""
        away_logo = imgs[1] if len(imgs) > 1 else ""
        # حالة
        status_text = ""
        for kw in ["جارية الان","انتهت","لم تبدأ","NS","FT","HT","LIVE"]:
            if kw in txt:
                status_text = kw; break
        status = "NS"
        if "انتهت" in status_text or status_text == "FT": status = "FT"
        elif "جارية" in status_text or status_text.upper() == "LIVE": status = "LIVE"
        candidates.append({
            "home": home, "away": away, "time_baghdad": time_bgd,
            "competition": comp, "home_logo": home_logo, "away_logo": away_logo,
            "status": status, "status_text": status_text, "result_text": ""
        })
    return candidates

# ====== Parser: LiveOnSat ======
def parse_liveonsat(html: str):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for live_block in soup.select("div.fLeft_live"):
        # الوقت
        time_div = live_block.find_previous_sibling("div", class_="fLeft_time_live")
        st_txt = _clean_spaces(time_div.get_text()) if time_div else ""
        m = re.search(r"(\d{1,2}:\d{2})", st_txt)
        kickoff = m.group(1) if m else ""
        # العنوان (حاول التقاط "Team A v Team B")
        title = ""
        cur_parent = live_block.parent
        search_txt = _clean_spaces(cur_parent.get_text(" ")) if cur_parent else ""
        # التقط أقرب سطر يحوي v / vs
        for line in re.split(r"\s{2,}", search_txt):
            if " v " in line or " vs " in line:
                title = _clean_spaces(line)
                break
        # القنوات
        channels = []
        for a in live_block.select("a"):
            label = _clean_spaces(a.get_text())
            if label and len(label) >= 2:
                channels.append(label)
        channels = list(dict.fromkeys(channels))
        if not channels:
            continue
        if not title:
            title = f"ST: {kickoff} " + " ".join(channels[:3])
        items.append({"title": title, "kickoff_baghdad": kickoff, "channels_raw": channels})
    return items

# ====== مطابقة مباراة يلا شوت مع بلوك LiveOnSat ======
def find_live_block(live_items, home_ar, away_ar, yalla_time):
    home_en = ALIASES.get(home_ar, "").lower()
    away_en = ALIASES.get(away_ar, "").lower()
    if not home_en or not away_en: return None
    target = time_to_minutes(yalla_time)
    candidates = []
    for it in live_items:
        title = (it.get("title") or "").lower()
        if not title: continue
        if home_en.split()[0] in title and away_en.split()[0] in title:
            st = it.get("kickoff_baghdad")
            st_min = time_to_minutes(st)
            diff = abs(st_min - target) if (st_min is not None and target is not None) else 9999
            candidates.append((diff, it))
    if not candidates: return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]

def looks_italian_match_en(title_en: str) -> bool:
    t = (title_en or "").lower()
    # مفتاحية بدائية
    if "serie a" in t: return True
    # أو عبر أسماء فرق إيطالية
    parts = re.split(r"\bv(s|\.)\b| v ", t)
    # أسهل: لو أي فريق ضمن لستة إيطاليا
    for name in ITALY_TEAMS:
        if name.lower() in t:
            return True
    return False

# ====== Main ======
def main():
    # 1) LiveOnSat (أساسي)
    live_html = safe_get_html(LIVE_URL)
    live_items = parse_liveonsat(live_html)

    # 2) YallaShoot (اختياري)
    try:
        yalla_html = safe_get_html(YALLA_URL, use_requests_first=False)  # صفحاتهم غالبًا تتطلب متصفح
        yalla_matches = parse_yalla(yalla_html)
    except Exception:
        yalla_matches = []

    out_matches = []

    if yalla_matches:
        # دمج على أساس يلا شوت
        for m in yalla_matches:
            home = m["home"]; away = m["away"]; time_bgd = m["time_baghdad"]
            block = find_live_block(live_items, home, away, time_bgd)
            channels_raw = block.get("channels_raw") if block else []
            channels_raw = list(dict.fromkeys(channels_raw))
            # تطابق لقنواتي
            channels_my = []
            for ch in channels_raw:
                mapped = map_liveonsat_to_mine(ch)
                if mapped and mapped not in channels_my:
                    channels_my.append(mapped)
            # إضافة ستارزبلاي لمباريات الدوري الإيطالي
            comp = m.get("competition") or ""
            title_guess = f"{ALIASES.get(home, home)} v {ALIASES.get(away, away)}"
            if ("الدوري الإيطالي" in comp) or looks_italian_match_en(title_guess):
                for extra in ("starzplay1","starzplay2"):
                    if extra not in channels_my:
                        channels_my.append(extra)

            date_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
            _id = f"{home.replace(' ','')}-{away.replace(' ','')}-{date_str}"

            out_matches.append({
                "id": _id,
                "home": home,
                "away": away,
                "home_logo": m.get("home_logo",""),
                "away_logo": m.get("away_logo",""),
                "time_baghdad": time_bgd,
                "status": m.get("status","NS"),
                "status_text": m.get("status_text",""),
                "result_text": m.get("result_text",""),
                "channels_raw": channels_raw,
                "channel": channels_my,
                "competition": comp,
                "_source": "yalla1shoot+liveonsat"
            })
    else:
        # يلا شوت فاضي → بنية كاملة من LiveOnSat
        for it in live_items:
            title = it["title"]
            kickoff = it.get("kickoff_baghdad","")
            channels_raw = list(dict.fromkeys(it.get("channels_raw",[])))

            # حاول نفصل الفرق من العنوان
            home_en = away_en = ""
            m = re.search(r"(.+?)\s+v(?:s\.?)?\s+(.+?)\s*(?:ST:|$)", title, re.IGNORECASE)
            if m:
                home_en = _clean_spaces(m.group(1))
                away_en = _clean_spaces(m.group(2))
            # fallback بسيط
            if not (home_en and away_en):
                parts = re.split(r"\bv(s|\.)\b| v ", title)
                if len(parts) >= 2:
                    home_en = _clean_spaces(parts[0])
                    away_en = _clean_spaces(parts[1])

            # خليه بالعربي إذا نعرف المعادل (عكس ALIASES)
            inv_alias = {v: k for k, v in ALIASES.items()}
            home_ar = inv_alias.get(home_en, home_en)
            away_ar = inv_alias.get(away_en, away_en)

            # قنواتي
            channels_my = []
            for ch in channels_raw:
                mapped = map_liveonsat_to_mine(ch)
                if mapped and mapped not in channels_my:
                    channels_my.append(mapped)

            # إيطاليا → starzplay
            if looks_italian_match_en(title):
                for extra in ("starzplay1","starzplay2"):
                    if extra not in channels_my:
                        channels_my.append(extra)
                comp = "إيطاليا, الدوري الإيطالي"
            else:
                # نحاول استنتاج خفيف من كلمات العنوان
                t = title.lower()
                if "premier league" in t: comp = "إنجلترا, الدوري الإنجليزي"
                elif "laliga" in t or "la liga" in t: comp = "إسبانيا, الدوري الإسباني"
                elif "bundesliga" in t: comp = "ألمانيا, الدوري الألماني"
                elif "ligue 1" in t: comp = "فرنسا, الدوري الفرنسي"
                elif "serie a" in t: comp = "إيطاليا, الدوري الإيطالي"
                else: comp = ""

            date_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
            _id = f"{str(home_ar).replace(' ','')}-{str(away_ar).replace(' ','')}-{date_str}"

            out_matches.append({
                "id": _id,
                "home": home_ar,
                "away": away_ar,
                "home_logo": "",
                "away_logo": "",
                "time_baghdad": kickoff,
                "status": "NS",
                "status_text": "",
                "result_text": "",
                "channels_raw": channels_raw,
                "channel": channels_my,
                "competition": comp,
                "_source": "liveonsat"
            })

    out_obj = {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "source_url": YALLA_URL,
        "matches": out_matches
    }
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out_obj, f, ensure_ascii=False, indent=2)
    print(f"[ALL-IN-ONE] wrote {OUT_PATH} with {len(out_matches)} matches.")

if __name__ == "__main__":
    main()

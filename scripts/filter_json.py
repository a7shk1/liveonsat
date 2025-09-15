# scripts/filter_json.py
# -*- coding: utf-8 -*-
import json
import re
import unicodedata
from pathlib import Path
import requests

# ==== المسارات/الإعدادات (نفسها) ====
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
INPUT_PATH = MATCHES_DIR / "liveonsat_raw.json"        # المصدر الأساسي
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"
YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"

# ==== أدوات مساعدة ====
AR_LETTERS_RE = re.compile(r'[\u0600-\u06FF]')
EMOJI_MISC_RE = re.compile(r'[\u2600-\u27BF\U0001F300-\U0001FAFF]+')
BEIN_RE = re.compile(r'bein\s*sports?', re.I)

def strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = str(text)
    text = EMOJI_MISC_RE.sub('', text)
    text = re.sub(r'\(.*?\)', '', text)
    text = strip_accents(text)
    text = text.lower()
    text = text.replace("&", "and")
    text = re.sub(r'\b(fc|sc|cf|u\d+)\b', '', text)
    # بدائل عربية شائعة
    text = (text
            .replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
            .replace("ى", "ي").replace("ة", "ه").replace("ال", "")
            .replace("ـ", ""))
    text = text.replace(" ", "").replace("-", "").replace("_", "")
    text = re.sub(r'[^a-z0-9\u0600-\u06FF]', '', text)
    return text.strip()

def unique_preserving(seq):
    seen, out = set(), []
    for x in seq:
        k = str(x).lower().strip()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out

def to_list_channels(val):
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        s = val.strip()
        if not s: return []
        parts = re.split(r"\s*(?:,|،|/|\||&| و | and )\s*", s, flags=re.I)
        return [p for p in parts if p]
    return []

def clean_channel_display(name: str) -> str:
    if not name: return ""
    s = str(name)
    s = EMOJI_MISC_RE.sub("", s)
    s = re.sub(r"\s*\((?:\$?\/?geo\/?R|geo\/?R|\$\/?geo)\)\s*", "", s, flags=re.I)
    s = re.sub(r"📺|\[online\]|\[app\]", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def is_bein_channel(name: str) -> bool:
    return bool(BEIN_RE.search(name or ""))

# ==== القنوات المسموحة فقط ====
SUPPORTED_CHANNELS = [
    "MATCH! Futbol 1", "MATCH! Futbol 2", "MATCH! Futbol 3",
    "Football HD",
    "Sport TV1 Portugal HD", "Sport TV2 Portugal HD",
    "ESPN 1 Brazil", "ESPN 2 Brazil", "ESPN 3 Brazil", "ESPN 4 Brazil", "ESPN 5 Brazil", "ESPN 6 Brazil", "ESPN 7 Brazil",
    "DAZN 1 Portugal HD", "DAZN 2 Portugal HD", "DAZN 3 Portugal HD", "DAZN 4 Portugal HD", "DAZN 5 Portugal HD", "DAZN 6 Portugal HD",
    "MATCH! Premier HD", "Sky Sports Main Event HD", "Sky Sport Premier League HD", "IRIB Varzesh HD",
    "Persiana Sport HD", "MBC Action HD", "TNT Sports 1 HD", "TNT Sports 2 HD", "TNT Sports HD",
    "MBC masrHD", "MBC masr2HD", "ssc1 hd", "ssc2 hd", "Shahid MBC",
]
_supported_tokens = set()
for c in SUPPORTED_CHANNELS:
    cl = c.lower()
    _supported_tokens.add(cl)
    _supported_tokens.add(cl.replace(" hd", ""))
SUPPORTED_TOKENS = list(_supported_tokens)

def is_supported_channel(name: str) -> bool:
    if not name: return False
    n = name.lower()
    return any(tok in n for tok in SUPPORTED_TOKENS)

# ==== قاموس EN→AR موسّع (أندية عربية، آسيوية، أفريقية، أوروبية، منتخبات) ====
# (تقدر توسّعه لاحقًا بسهولة — المطابقة لا تستخدم أي ترجمة آلية)
EN2AR = {
    # منتخبات عربية
    "Iraq":"العراق","Saudi Arabia":"السعودية","Qatar":"قطر","United Arab Emirates":"الإمارات","UAE":"الإمارات",
    "Kuwait":"الكويت","Bahrain":"البحرين","Oman":"عمان","Jordan":"الأردن","Syria":"سوريا","Lebanon":"لبنان",
    "Palestine":"فلسطين","Yemen":"اليمن","Egypt":"مصر","Libya":"ليبيا","Tunisia":"تونس","Algeria":"الجزائر","Morocco":"المغرب",

    # منتخبات عالمية مختصرة
    "Brazil":"البرازيل","Argentina":"الأرجنتين","Germany":"ألمانيا","France":"فرنسا","Spain":"إسبانيا","Italy":"إيطاليا",
    "England":"إنجلترا","Portugal":"البرتغال","Netherlands":"هولندا","Belgium":"بلجيكا","Croatia":"كرواتيا","Uruguay":"أوروجواي",
    "United States":"الولايات المتحدة","USA":"الولايات المتحدة","Mexico":"المكسيك","Japan":"اليابان","South Korea":"كوريا الجنوبية","Australia":"أستراليا",

    # أندية سعودية
    "Al Hilal":"الهلال","Al-Hilal":"الهلال","Al Nassr":"النصر","Al-Nassr":"النصر","Al Ittihad":"الاتحاد","Al-Ittihad":"الاتحاد",
    "Al Ahli":"الأهلي السعودي","Al-Ahli":"الأهلي السعودي","Al Shabab":"الشباب","Al-Shabab":"الشباب","Al Ettifaq":"الاتفاق","Al-Ettifaq":"الاتفاق",
    "Al Fayha":"الفيحاء","Al-Fayha":"الفيحاء","Al Raed":"الرائد","Al-Raed":"الرائد","Al Taawoun":"التعاون","Al-Taawoun":"التعاون",
    "Abha":"أبها","Damac":"ضمك","Al Fateh":"الفتح","Al-Fateh":"الفتح","Al Okhdood":"الأخدود","Al-Okhdood":"الأخدود",
    "Al Riyadh":"الرياض","Al-Riyadh":"الرياض","Al Wehda":"الوحدة","Al-Wehda":"الوحدة","Al Qadsiah":"القادسية","Al-Qadsiah":"القادسية",

    # أندية قطر/الإمارات/العراق/المغرب
    "Al Sadd":"السد","Al-Sadd":"السد","Al Duhail":"الدحيل","Al-Duhail":"الدحيل","Al Gharafa":"الغرافة","Al-Gharafa":"الغرافة",
    "Al Rayyan":"الريان","Al-Rayyan":"الريان","Qatar SC":"قطر","Al Arabi":"العربي","Al-Arabi":"العربي","Al Wakrah":"الوكرة","Al-Wakrah":"الوكرة",
    "Al Ain":"العين","Al-Ain":"العين","Al Jazira":"الجزيرة","Al-Jazira":"الجزيرة","Shabab Al Ahli":"شباب الأهلي",
    "Al Nasr Dubai":"النصر الإماراتي","Sharjah":"الشارقة","Khor Fakkan":"خورفكان","Bani Yas":"بني ياس",
    "Al Shorta":"الشرطة","Al-Shorta":"الشرطة","Al Zawraa":"الزوراء","Al-Zawraa":"الزوراء",
    "Al Quwa Al Jawiya":"القوة الجوية","Al-Quwa Al-Jawiya":"القوة الجوية","Naft Al Wasat":"نفط الوسط","Al Najaf":"النجف",
    "Erbil":"أربيل","Duhok":"دهوك","Al Minaa":"الميناء","Al-Minaa":"الميناء",
    "Wydad":"الوداد","Raja":"الرجاء","FUS Rabat":"الفتح الرباطي","RS Berkane":"نهضة بركان",
    "Hassania Agadir":"حسنية أكادير","Ittihad Tanger":"اتحاد طنجة","OC Safi":"أولمبيك آسفي","Olympic Safi":"أولمبيك آسفي",

    # إسبانيا/إيطاليا/إنجلترا/فرنسا/ألمانيا (أشهر)
    "Real Madrid":"ريال مدريد","Barcelona":"برشلونة","Atletico Madrid":"أتلتيكو مدريد","Sevilla":"إشبيلية","Valencia":"فالنسيا",
    "Villarreal":"فياريال","Real Sociedad":"ريال سوسيداد","Espanyol":"إسبانيول","Real Mallorca":"ريال مايوركا","Mallorca":"ريال مايوركا",

    "Inter":"إنتر ميلان","Inter Milan":"إنتر ميلان","AC Milan":"ميلان","Milan":"ميلان","Juventus":"يوفنتوس",
    "Napoli":"نابولي","Roma":"روما","Lazio":"لاتسيو","Fiorentina":"فيورنتينا","Atalanta":"أتالانتا","Torino":"تورينو",
    "Udinese":"أودينيزي","Sassuolo":"ساسولو","Monza":"مونزا","Como":"كومو","Genoa":"جنوى","Hellas Verona":"هيلاس فيرونا","Cremonese":"كريمونيزي",

    "Manchester City":"مانشستر سيتي","Manchester United":"مانشستر يونايتد","Arsenal":"أرسنال","Liverpool":"ليفربول","Chelsea":"تشيلسي",
    "Tottenham Hotspur":"توتنهام","Tottenham":"توتنهام","Newcastle United":"نيوكاسل يونايتد","Aston Villa":"أستون فيلا",
    "West Ham United":"وست هام يونايتد","Everton":"إيفرتون","Wolverhampton":"ولفرهامبتون","Wolves":"ولفرهامبتون",

    "Paris Saint-Germain":"باريس سان جيرمان","PSG":"باريس سان جيرمان","Marseille":"مارسيليا","Lyon":"ليون","Monaco":"موناكو",
    "Lille":"ليل","Nice":"نيس","Rennes":"رين","Brest":"بريست","Strasbourg":"ستراسبورغ","Montpellier":"مونبلييه","Guingamp":"جانجون",

    "Bayern Munich":"بايرن ميونخ","Borussia Dortmund":"بوروسيا دورتموند","RB Leipzig":"لايبزيغ","Bayer Leverkusen":"باير ليفركوزن",

    # هولندا/البرتغال
    "Ajax":"أياكس","PSV Eindhoven":"آيندهوفن","Feyenoord":"فاينورد",
    "Benfica":"بنفيكا","Porto":"بورتو","Sporting CP":"سبورتينغ لشبونة","Sporting":"سبورتينغ لشبونة",
}
AR2EN = {v: k for k, v in EN2AR.items()}

def en_to_ar(name: str) -> str:
    return EN2AR.get(name, name or "")

def ar_to_en(name: str) -> str:
    return AR2EN.get(name, name or "")

# ==== parsing liveonsat ====
def parse_title_to_teams_generic(title: str) -> tuple[str|None, str|None]:
    if not title: return None, None
    t = title.strip()
    DELIMS = [
        r"\s+v(?:s)?\.?\s+",  # v / vs
        r"\s+-\s+", r"\s+–\s+", r"\s+—\s+",
        r"\s*:\s*", r"\s*\|\s*", r"\s*·\s*", r"\s*;\s*",
    ]
    for d in DELIMS:
        parts = re.split(d, t, maxsplit=1)
        if len(parts) == 2:
            l, r = parts[0].strip(), parts[1].strip()
            if l and r:
                return l, r
    return None, None

def extract_live_match(m: dict) -> tuple[str|None, str|None]:
    home = (m.get("home") or m.get("home_team"))
    away = (m.get("away") or m.get("away_team"))
    if home and away:
        return str(home).strip(), str(away).strip()
    title = (m.get("title") or "").strip()
    return parse_title_to_teams_generic(title)

# ==== بناء فهرس liveonsat بالقنوات المسموحة ====
def build_live_entries(live_data: dict):
    out = []
    matches = (live_data or {}).get("matches", []) or []
    for m in matches:
        h_en, a_en = extract_live_match(m)
        if not h_en or not a_en:
            continue

        # قنوات من عدة حقول
        raw_channels = []
        for ck in ("channels_raw","channels","tv_channels","broadcasters","broadcaster"):
            if ck in m and m[ck]:
                raw = m[ck]
                if isinstance(raw, list):
                    raw_channels.extend([str(x) for x in raw])
                elif isinstance(raw, str):
                    raw_channels.extend(to_list_channels(raw))

        # فلترة القنوات
        filtered = []
        for ch in raw_channels:
            ch = clean_channel_display(ch)
            if not ch: continue
            if is_bein_channel(ch):  # beIN من يلا فقط
                continue
            if is_supported_channel(ch):
                filtered.append(ch)
        filtered = unique_preserving(filtered)
        if not filtered:
            continue

        entry = {
            "competition": m.get("competition") or "",
            "kickoff_baghdad": m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff") or "",
            "home_en": h_en.strip(),
            "away_en": a_en.strip(),
            "home_ar_guess": en_to_ar(h_en.strip()),
            "away_ar_guess": en_to_ar(a_en.strip()),
            "channels": filtered,
        }
        out.append(entry)
    return out

# ==== يلا شوت ====
def collect_yalla_channels(y: dict) -> list:
    keys_try = ["channels_raw","channels","tv_channels","channel","channel_ar","channel_en","broadcasters","broadcaster"]
    out = []
    for k in keys_try:
        if k in y:
            out.extend(to_list_channels(y.get(k)))
    return unique_preserving(out)

def pick_primary_yalla_channel(chs: list[str]) -> str|None:
    if not chs: return None
    for c in chs:
        if is_bein_channel(c):
            return c.strip()
    return chs[0].strip()

def build_yalla_index(yalla_data: dict):
    """
    فهرس بمفاتيح:
      - AR pair: norm(home_ar)-norm(away_ar)
      - EN pair: norm(ar_to_en(home_ar))-norm(ar_to_en(away_ar))
    ونخزن كلا الاتجاهين (home-away) و(away-home).
    """
    idx = {}
    matches = (yalla_data or {}).get("matches", []) or []
    for m in matches:
        home_ar = (m.get("home") or m.get("home_team") or "").strip()
        away_ar = (m.get("away") or m.get("away_team") or "").strip()
        if not home_ar or not away_ar:
            continue

        # مفاتيح عربية مباشرة
        k1 = f"{normalize_text(home_ar)}-{normalize_text(away_ar)}"
        k2 = f"{normalize_text(away_ar)}-{normalize_text(home_ar)}"

        # مفاتيح إنجليزية من تحويل القيم العربية (من القاموس)
        home_en = ar_to_en(home_ar)
        away_en = ar_to_en(away_ar)
        k3 = f"{normalize_text(home_en)}-{normalize_text(away_en)}"
        k4 = f"{normalize_text(away_en)}-{normalize_text(home_en)}"

        for k in (k1, k2, k3, k4):
            # نخزن أفضل قناة من يلا
            y_chs = collect_yalla_channels(m)
            primary = pick_primary_yalla_channel(y_chs)
            idx[k] = {
                "match": m,
                "primary_yalla_channel": primary
            }
    return idx

# ==== المطابقة الصارمة (بعد التحويل) ====
def match_live_to_yalla(live_entry: dict, y_idx: dict) -> dict|None:
    # 1) جرّب مقارنة عربي لعربي (EN_live→AR) بالاتجاهين
    h_ar = live_entry["home_ar_guess"]
    a_ar = live_entry["away_ar_guess"]
    if h_ar and a_ar:
        k1 = f"{normalize_text(h_ar)}-{normalize_text(a_ar)}"
        k2 = f"{normalize_text(a_ar)}-{normalize_text(h_ar)}"
        if k1 in y_idx: return y_idx[k1]
        if k2 in y_idx: return y_idx[k2]

    # 2) جرّب مقارنة إنجليزي لإنجليزي (AR_yalla→EN) بالاتجاهين — يتم من خلال فهرس y_idx
    h_en = live_entry["home_en"]; a_en = live_entry["away_en"]
    k3 = f"{normalize_text(h_en)}-{normalize_text(a_en)}"
    k4 = f"{normalize_text(a_en)}-{normalize_text(h_en)}"
    if k3 in y_idx: return y_idx[k3]
    if k4 in y_idx: return y_idx[k4]

    return None

# ==== الرئيسي ====
def filter_matches():
    # 0) اقرأ liveonsat (مصدر أساسي)
    try:
        with INPUT_PATH.open("r", encoding="utf-8") as f:
            live_data = json.load(f)
    except Exception as e:
        print(f"[x] ERROR reading liveonsat: {e}")
        return

    live_entries = build_live_entries(live_data)
    if not live_entries:
        print("[!] liveonsat has 0 usable matches (after channel filtering).")
        with OUTPUT_PATH.open("w", encoding="utf-8") as f:
            json.dump({"date": live_data.get("date"), "source_url": live_data.get("source_url"), "matches": []}, f, ensure_ascii=False, indent=2)
        return

    # 1) حمّل يلا شوت (للمطابقة + beIN)
    try:
        yresp = requests.get(YALLASHOOT_URL, timeout=25)
        yresp.raise_for_status()
        yalla = yresp.json()
    except Exception as e:
        print(f"[x] ERROR fetching yallashoot: {e}")
        yalla = {"matches": []}

    y_idx = build_yalla_index(yalla)

    # 2) تقاطع + دمج
    out_matches = []
    matched_cnt = 0
    for le in live_entries:
        m_y = match_live_to_yalla(le, y_idx)
        if not m_y:
            continue
        matched_cnt += 1

        y_match = m_y["match"]
        primary_yalla = m_y.get("primary_yalla_channel")

        # قنوات: beIN من يلا (إن وجِدت) + قنوات liveonsat المسموحة
        channels = []
        if primary_yalla:
            channels.append(primary_yalla)
        channels.extend(le["channels"])
        channels = unique_preserving(channels)

        # الحقول
        out = {
            "competition": y_match.get("competition") or le["competition"],
            "kickoff_baghdad": y_match.get("kickoff_baghdad") or le["kickoff_baghdad"],
            "home_team": en_to_ar(le["home_en"]) if en_to_ar(le["home_en"]) else le["home_en"],
            "away_team": en_to_ar(le["away_en"]) if en_to_ar(le["away_en"]) else le["away_en"],
            "channels_raw": channels,
            "home_logo": y_match.get("home_logo"),
            "away_logo": y_match.get("away_logo"),
            "status_text": y_match.get("status_text"),
            "result_text": y_match.get("result_text"),
        }
        out_matches.append(out)

    # 3) كتابة المخرجات
    output = {
        "date": live_data.get("date") or yalla.get("date"),
        "source_url": live_data.get("source_url") or "liveonsat + yallashoot",
        "matches": out_matches
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[✓] Done. live entries: {len(live_entries)} | matched with yalla: {matched_cnt} | written: {len(out_matches)}")

if __name__ == "__main__":
    filter_matches()

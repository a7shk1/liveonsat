# scripts/filter_json.py
# -*- coding: utf-8 -*-
import json
import re
import unicodedata
from pathlib import Path
import requests
from difflib import SequenceMatcher

# ========= إعدادات =========
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"
LIVEONSAT_PATH = MATCHES_DIR / "liveonsat_raw.json"

YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"

# نافذة التطابق بالوقت (دقائق) — الأساسية
TIME_TOL_MIN = 25

# offsets محتملة (إذا liveonsat وقتها مو بغداد)
TIME_OFFSETS = [0, 60, 120, 180, -60, -120, -180]

# ========= أدوات مساعدة =========
EMOJI_MISC_RE = re.compile(r'[\u2600-\u27BF\U0001F300-\U0001FAFF]+')
BEIN_EN_RE = re.compile(r'bein\s*sports?', re.I)
BEIN_AR_RE = re.compile(r'(?:بي|بى)\s*[^A-Za-z0-9]{0,2}\s*ا?ن\s*[^A-Za-z0-9]{0,4}\s*سبورت', re.I)

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
TIME_RE_12 = re.compile(r'^\s*(\d{1,2}):(\d{2})\s*([AP]M)\s*$', re.I)
TIME_RE_24 = re.compile(r'^\s*(\d{1,2}):(\d{2})\s*$')

TITLE_SPLIT_RE = re.compile(r"\s+(?:v|vs)\s+", re.I)

def to_western_digits(s: str) -> str:
    return (s or "").translate(ARABIC_DIGITS)

def kickoff_to_minutes(hhmm: str):
    if not hhmm:
        return None
    s = to_western_digits(hhmm).strip()
    m = TIME_RE_12.match(s)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
        if ap == "PM" and h != 12:
            h += 12
        if ap == "AM" and h == 12:
            h = 0
        return h*60 + mi
    m = TIME_RE_24.match(s)
    if m:
        return int(m.group(1))*60 + int(m.group(2))
    return None

def wrap_minutes(x: int) -> int:
    return x % 1440

def best_time_diff_with_offsets(y_tmin: int, live_tmin: int) -> tuple[int, int]:
    """
    يرجّع (أفضل فرق بالدقائق, offset المستخدم)
    """
    best = (10**9, 0)
    for off in TIME_OFFSETS:
        d = abs(wrap_minutes(y_tmin) - wrap_minutes(live_tmin + off))
        # خذ الأقصر عبر منتصف الليل
        d = min(d, 1440 - d)
        if d < best[0]:
            best = (d, off)
    return best

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
    text = (text
            .replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
            .replace("ى", "ي").replace("ة", "ه").replace("ال", "")
            .replace("ـ", ""))
    text = text.replace(" ", "").replace("-", "").replace("_", "")
    text = re.sub(r'[^a-z0-9\u0600-\u06FF]', '', text)
    return text.strip()

def similarity(a: str, b: str) -> float:
    a, b = normalize_text(a), normalize_text(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # تشابه تقريبي
    return SequenceMatcher(None, a, b).ratio()

def clean_channel_display(name: str) -> str:
    if not name:
        return ""
    s = str(name)
    s = EMOJI_MISC_RE.sub("", s)
    s = re.sub(r"\s*\((?:\$?\/?geo\/?R|geo\/?R|\$\/?geo|tjk)\)\s*", "", s, flags=re.I)
    s = re.sub(r"📺|\[online\]|\[app\]", "", s, flags=re.I)
    s = re.sub(r"\s*hd\s*$", " HD", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def to_list_channels(val):
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return []
        parts = re.split(r"\s*(?:,|،|/|\||&| و | and )\s*", s, flags=re.I)
        return [p for p in parts if p]
    return []

def unique_preserving(seq):
    seen, out = set(), []
    for x in seq:
        k = str(x).lower().strip()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out

def is_bein(name: str) -> bool:
    s = name or ""
    return bool(BEIN_EN_RE.search(s) or BEIN_AR_RE.search(s))

def extract_bein_signal(ch_name: str):
    disp = clean_channel_display(ch_name)
    s = to_western_digits(disp)
    ok = is_bein(s)
    mena = None
    if re.search(r'\bmena\b|\bmiddle\s*east\b', s, re.I):
        mena = True
    if "الشرقالاوسط" in normalize_text(s):
        mena = True
    mnum = re.search(r'\b(\d{1,2})\b', s)
    num = int(mnum.group(1)) if mnum else None
    return {"is_bein": bool(ok), "mena": mena, "num": num}

# ========= فلتر القنوات من liveonsat =========
DENY_PATTERNS = [
    re.compile(r'\balkass\b', re.I),
    re.compile(r'\bal\s*kass\b', re.I),
    re.compile(r'الكاس|الكأس', re.I),
]

SKY_ALLOWED_RE = re.compile(
    r'\bsky\s*sport[s]?\s*(?:main\s*event|premier\s*league(?:\s*uk)?)\b', re.I
)

TNT_BASE_RE = re.compile(r'\btnt\s*sports?\b(?:\s*(\d+))?', re.I)

IRIB_TV3_RE = re.compile(r'\birib\s*tv\s*3\b', re.I)
IRIB_VARZESH_RE = re.compile(r'\birib\s*varzesh\b', re.I)

VARZISH_RE = re.compile(r'\bvarzish\b', re.I)

DAZN_PT_RE = re.compile(r'\bdazn\b\s*(?:\d+\s*)?portugal\b', re.I)
SPORTTV_PT_RE = re.compile(r'\bsport\s*tv\b\s*(?:\d+\s*)?portugal\b', re.I)

GENERAL_ALLOWED_SUBSTRINGS = {
    "football hd",
    "dazn portugal",
    "sport tv portugal",
    "espn 1 brazil", "espn 2 brazil", "espn 3 brazil", "espn 4 brazil", "espn 5 brazil", "espn 6 brazil", "espn 7 brazil",
    "persiana sport", "mbc action", "ssc ", " ssc", "shahid", "thmanyah", "starzplay", "abu dhabi sport",
    "irib varzesh", "irib tv3", "varzish",
}

def is_denied_channel(name: str) -> bool:
    if not name:
        return True
    n = name.lower()
    for pat in DENY_PATTERNS:
        if pat.search(n):
            return True
    return False

def sky_allowed(name: str) -> bool:
    return bool(SKY_ALLOWED_RE.search(name or ""))

def tnt_allowed(name: str) -> bool:
    m = TNT_BASE_RE.search(name or "")
    if not m:
        return False
    num = m.group(1)
    if num is None:
        return True
    return num in {"1", "2"}

def is_supported_channel(name: str) -> bool:
    if not name:
        return False
    disp = clean_channel_display(name)
    n = disp.lower()

    if is_denied_channel(n):
        return False

    # beIN من live ممنوع إضافته
    if is_bein(disp):
        return False

    if "sky" in n:
        return sky_allowed(disp)

    if "tnt" in n:
        return tnt_allowed(disp)

    if DAZN_PT_RE.search(disp):
        return True

    if SPORTTV_PT_RE.search(disp):
        return True

    if IRIB_TV3_RE.search(disp) or IRIB_VARZESH_RE.search(disp):
        return True

    if VARZISH_RE.search(disp):
        return True

    for sub in GENERAL_ALLOWED_SUBSTRINGS:
        if sub in n:
            return True

    return False

# ========= توحيد أسماء القنوات =========
CHANNEL_CANON_RULES = [
    (re.compile(r"thmanyah\s*(\d+)", re.I),            lambda m: (f"thmanyah-{m.group(1)}", f"Thmanyah {m.group(1)}")),
    (re.compile(r"starzplay\s*(\d+)", re.I),           lambda m: (f"starzplay-{m.group(1)}", f"Starzplay {m.group(1)}")),
    (re.compile(r"starzplay\b", re.I),                 lambda m: ("starzplay-1", "Starzplay 1")),
    (re.compile(r"abu\s*dhabi\s*sport\s*(\d+)", re.I), lambda m: (f"abudhabi-{m.group(1)}", f"Abu Dhabi Sport {m.group(1)}")),
    (re.compile(r"ssc\s*extra", re.I),                 lambda m: ("ssc-extra", "SSC Extra HD")),
    (re.compile(r"ssc\s*(\d+)", re.I),                 lambda m: (f"ssc-{m.group(1)}", f"SSC {m.group(1)} HD")),
    (re.compile(r"shahid\s*(vip)?", re.I),             lambda m: ("shahid", "Shahid MBC")),
    (re.compile(r"football\s*hd", re.I),               lambda m: ("football-hd", "Football HD")),
    (re.compile(r"persiana\s*sport", re.I),            lambda m: ("persiana-sport", "Persiana Sport HD")),
    (re.compile(r"sky\s*sport[s]?\s*main\s*event", re.I),
                                                     lambda m: ("sky-main-event", "Sky Sports Main Event HD")),
    (re.compile(r"sky\s*sport[s]?\s*premier\s*league(?:\s*uk)?", re.I),
                                                     lambda m: ("sky-premier-league", "Sky Sports Premier League UK" if "uk" in m.group(0).lower() else "Sky Sport Premier League HD")),
    (re.compile(r"dazn\s*1\s*portugal", re.I),         lambda m: ("dazn-pt-1", "DAZN 1 Portugal HD")),
    (re.compile(r"dazn\s*2\s*portugal", re.I),         lambda m: ("dazn-pt-2", "DAZN 2 Portugal HD")),
    (re.compile(r"dazn\s*3\s*portugal", re.I),         lambda m: ("dazn-pt-3", "DAZN 3 Portugal HD")),
    (re.compile(r"dazn\s*4\s*portugal", re.I),         lambda m: ("dazn-pt-4", "DAZN 4 Portugal HD")),
    (re.compile(r"dazn\s*5\s*portugal", re.I),         lambda m: ("dazn-pt-5", "DAZN 5 Portugal HD")),
    (re.compile(r"dazn\s*6\s*portugal", re.I),         lambda m: ("dazn-pt-6", "DAZN 6 Portugal HD")),
    (re.compile(r"dazn\s*portugal", re.I),             lambda m: ("dazn-pt", "DAZN Portugal HD")),
    (re.compile(r"sport\s*tv\s*1\s*portugal", re.I),   lambda m: ("sporttv-pt-1", "Sport TV1 Portugal HD")),
    (re.compile(r"sport\s*tv\s*2\s*portugal", re.I),   lambda m: ("sporttv-pt-2", "Sport TV2 Portugal HD")),
    (re.compile(r"sport\s*tv\s*portugal", re.I),       lambda m: ("sporttv-pt", "Sport TV Portugal HD")),
    (re.compile(r"tnt\s*sports?\s*1\b", re.I),         lambda m: ("tnt-1", "TNT Sports 1 HD")),
    (re.compile(r"tnt\s*sports?\s*2\b", re.I),         lambda m: ("tnt-2", "TNT Sports 2 HD")),
    (re.compile(r"tnt\s*sports?(?!\s*\d)", re.I),      lambda m: ("tnt", "TNT Sports HD")),
    (re.compile(r"irib\s*tv\s*3", re.I),               lambda m: ("irib-tv3", "IRIB TV3 HD")),
    (re.compile(r"irib\s*varzesh", re.I),              lambda m: ("irib-varzesh", "IRIB Varzesh HD")),
    (re.compile(r"varzish", re.I),                     lambda m: ("varzish", "Varzish TV Sport HD")),
]

def channel_key_and_display(raw_name: str):
    disp = clean_channel_display(raw_name)
    low = disp.lower()
    if is_bein(disp):
        has_mena = bool(re.search(r'\bmena\b|\bmiddle\s*east\b', low)) or ("الشرقالاوسط" in normalize_text(disp))
        mnum = re.search(r'\b(\d{1,2})\b', to_western_digits(disp))
        if has_mena and mnum:
            return (f"bein-mena-{mnum.group(1)}", f"beIN Sports MENA {mnum.group(1)} HD")
        if has_mena:
            return ("bein-mena", "beIN Sports MENA HD")
        if mnum:
            return (f"bein-{mnum.group(1)}", f"beIN Sports {mnum.group(1)} HD")
        return ("bein", "beIN Sports HD")
    for pat, conv in CHANNEL_CANON_RULES:
        m = pat.search(disp)
        if m:
            key, fixed = conv(m)
            return (key.lower(), fixed)
    return (low, disp)

def dedupe_channels_preserve_order(ch_list):
    seen_keys, out_disp = set(), []
    for ch in ch_list:
        if not ch:
            continue
        key, disp = channel_key_and_display(ch)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out_disp.append(disp)
    return out_disp

# ========= buckets (نوع البطولة) =========
def comp_bucket(name: str) -> str:
    n = normalize_text(name)
    if "uefa" in n or "championsleague" in n or "دوريابطالاوروبا" in n:
        return "UEFA-CL"
    if "afc" in n or "دوريابطالاسيا" in n or "اسيا" in n:
        return "AFC-CL"
    if "carabao" in n or "efl" in n or ("كاس" in n and "الانجليزي" in n):
        return "ENG-EFL"
    if "المغربي" in n or "botola" in n:
        return "MAR-BOT"
    return "OTHER"

def split_title_teams(title: str):
    """
    من liveonsat: "A v B" أو "A vs B" -> (home, away)
    """
    if not title:
        return ("", "")
    parts = TITLE_SPLIT_RE.split(title.strip(), maxsplit=1)
    if len(parts) == 2:
        return (parts[0].strip(), parts[1].strip())
    return ("", "")

# ========= قراءة liveonsat إلى فهرس =========
def build_live_index(live_data: dict):
    idx = []
    matches = (live_data or {}).get("matches", []) or []
    for m in matches:
        # time
        t = (m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff") or "").strip()
        tmin = kickoff_to_minutes(t)
        if tmin is None:
            continue

        # comp + bucket
        comp = (m.get("competition") or "").strip()
        bucket = comp_bucket(comp)

        # teams from title
        title = (m.get("title") or m.get("match") or m.get("name") or "").strip()
        lh, la = split_title_teams(title)

        # channels
        raw_channels = []
        for ck in ("channels_raw", "channels", "tv_channels", "broadcasters", "broadcaster"):
            if ck in m and m[ck]:
                raw = m[ck]
                if isinstance(raw, list):
                    raw_channels.extend([str(x) for x in raw])
                elif isinstance(raw, str):
                    raw_channels.extend(to_list_channels(raw))

        bein_nums = set()
        allowed = []
        for ch in raw_channels:
            disp = clean_channel_display(ch)
            if not disp:
                continue

            sig = extract_bein_signal(disp)
            if sig["is_bein"]:
                if sig["num"]:
                    bein_nums.add(sig["num"])
                continue

            if is_supported_channel(disp):
                allowed.append(disp)

        allowed = dedupe_channels_preserve_order(allowed)

        idx.append({
            "tmin": tmin,
            "bucket": bucket,
            "bein_nums": bein_nums,
            "allowed": allowed,
            "home": lh,
            "away": la,
            "home_n": normalize_text(lh),
            "away_n": normalize_text(la),
        })
    return idx

# ========= قنوات يلا =========
def collect_yalla_channels(y: dict):
    keys = ["channels_raw","channels","tv_channels","channel","channel_ar","channel_en","broadcasters","broadcaster"]
    out = []
    for k in keys:
        if k in y and y[k]:
            out.extend(to_list_channels(y[k]))
    return unique_preserving(out)

def yalla_primary_channel(y: dict):
    chs = [clean_channel_display(c) for c in collect_yalla_channels(y)]
    return chs[0] if chs else None

def yalla_bein_num(y: dict):
    for c in collect_yalla_channels(y):
        disp = clean_channel_display(c)
        sig = extract_bein_signal(disp)
        if sig["is_bein"] and sig["num"]:
            return sig["num"]
    return None

def score_live_candidate(li: dict, y_home: str, y_away: str, y_tmin: int, y_bein: int | None, y_bucket: str):
    """
    سكورنغ: فرق + وقت + bein + bucket + غنى القنوات
    """
    score = 0
    # teams similarity
    sh = similarity(li.get("home", ""), y_home)
    sa = similarity(li.get("away", ""), y_away)

    # اسماء الفرق بالعكس (أحياناً ترتيب)
    sh_rev = similarity(li.get("home", ""), y_away)
    sa_rev = similarity(li.get("away", ""), y_home)

    best_team = max((sh + sa) / 2, (sh_rev + sa_rev) / 2)
    score += int(best_team * 60)  # up to 60

    # time diff with offsets
    dmin, used_off = best_time_diff_with_offsets(y_tmin, li["tmin"])
    if dmin <= TIME_TOL_MIN:
        score += 35
    elif dmin <= 60:
        score += 25
    elif dmin <= 180:
        score += 12

    # bein hint
    if y_bein is not None and y_bein in li.get("bein_nums", set()):
        score += 40

    # bucket
    if y_bucket != "OTHER" and li.get("bucket") == y_bucket:
        score += 10

    # allowed channels richness
    score += min(len(li.get("allowed", [])), 6)

    return score, dmin, used_off, best_team

def pick_best_live(li_list: list[dict], y_home: str, y_away: str, y_tmin: int, y_bein: int | None, y_bucket: str):
    best = None
    best_meta = None
    for li in li_list:
        sc, dmin, off, team_sim = score_live_candidate(li, y_home, y_away, y_tmin, y_bein, y_bucket)
        if best is None or sc > best_meta["score"]:
            best = li
            best_meta = {"score": sc, "dmin": dmin, "offset": off, "team_sim": team_sim}
    return best, best_meta

# ========= الرئيسي =========
def filter_matches():
    # 1) يلا شوت
    try:
        yresp = requests.get(YALLASHOOT_URL, timeout=25)
        yresp.raise_for_status()
        yalla = yresp.json()
    except Exception as e:
        print(f"[x] ERROR fetching yallashoot: {e}")
        return

    y_matches = (yalla or {}).get("matches", []) or []
    print(f"[i] Yalla matches: {len(y_matches)}")

    # 2) liveonsat (محلي)
    try:
        with LIVEONSAT_PATH.open("r", encoding="utf-8") as f:
            live_data = json.load(f)
    except Exception as e:
        print(f"[!] WARN reading liveonsat: {e}")
        live_data = {"matches": []}

    live_matches = (live_data or {}).get("matches", []) or []
    print(f"[i] Live matches in file: {len(live_matches)}")

    live_idx = build_live_index(live_data)
    print(f"[i] Live index usable (with time): {len(live_idx)}")

    out_matches = []
    matched_from_live = 0

    for m in y_matches:
        y_time = (m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff") or "").strip()
        y_tmin = kickoff_to_minutes(y_time)
        y_bucket = comp_bucket(m.get("competition") or "")
        y_bein = yalla_bein_num(m)

        y_home = (m.get("home") or m.get("home_team") or "").strip()
        y_away = (m.get("away") or m.get("away_team") or "").strip()

        merged = []
        primary = yalla_primary_channel(m)
        if primary:
            merged.append(primary)

        best = None
        meta = None

        if y_tmin is not None and live_idx:
            # بدل فلترة 25 دقيقة فقط: خذ كل المرشحين ضمن 3 ساعات (لأن offsets ممكن)
            broad = []
            for li in live_idx:
                dmin, _ = best_time_diff_with_offsets(y_tmin, li["tmin"])
                if dmin <= 180:
                    broad.append(li)

            best, meta = pick_best_live(broad, y_home, y_away, y_tmin, y_bein, y_bucket)

        if best and best.get("allowed"):
            merged.extend(best["allowed"])
            matched_from_live += 1

        merged = dedupe_channels_preserve_order(merged)

        out_matches.append({
            "competition": m.get("competition") or "",
            "kickoff_baghdad": y_time,
            "home_team": y_home,
            "away_team": y_away,
            "channels_raw": merged,
            "home_logo": m.get("home_logo"),
            "away_logo": m.get("away_logo"),
            "status_text": m.get("status_text"),
            "result_text": m.get("result_text"),
            # معلومات Debug اختيارية (تقدر تشيلها إذا ما تريدها)
            "merge_debug": meta if meta else None
        })

    output = {
        "date": (yalla or {}).get("date"),
        "source_url": "yallashoot (primary) + liveonsat (best-by-score: time+offset+teams+bein+bucket; custom channel filter)",
        "matches": out_matches
    }

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[✓] Done. yalla: {len(y_matches)} | matched_from_live: {matched_from_live} | written: {len(out_matches)}")


if __name__ == "__main__":
    filter_matches()

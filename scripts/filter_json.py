# scripts/filter_json.py
# -*- coding: utf-8 -*-
import json
import re
import unicodedata
from pathlib import Path
import requests

# ============ Paths / Sources ============
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_DIR = REPO_ROOT / "matches"
OUTPUT_PATH = MATCHES_DIR / "filtered_matches.json"

YALLASHOOT_URL = "https://raw.githubusercontent.com/a7shk1/yallashoot/refs/heads/main/matches/today.json"
LIVEONSAT_PATH = MATCHES_DIR / "liveonsat_raw.json"   # محلي EN

# ============ Regex / Helpers ============
EMOJI_MISC_RE = re.compile(r'[\u2600-\u27BF\U0001F300-\U0001FAFF]+')
BEIN_EN_RE = re.compile(r'bein\s*sports?', re.I)
# العربية: بي/بى + (أن|ان) + سبورت (مع مسافات/علامات مرنة)
BEIN_AR_RE = re.compile(r'(?:بي|بى)\s*[^A-Za-z0-9]{0,2}\s*ا?ن\s*[^A-Za-z0-9]{0,4}\s*سبورت', re.I)

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

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
def to_western_digits(s: str) -> str:
    return (s or "").translate(ARABIC_DIGITS)

TIME_RE_12 = re.compile(r'^\s*(\d{1,2}):(\d{2})\s*([AP]M)\s*$', re.I)
TIME_RE_24 = re.compile(r'^\s*(\d{1,2}):(\d{2})\s*$')

def kickoff_to_minutes(hhmm: str) -> int | None:
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
        return int(m.group(1)) * 60 + int(m.group(2))
    return None

def minutes_close(m1: int | None, m2: int | None, tol: int = 30) -> bool:
    if m1 is None or m2 is None:
        return True
    return abs(m1 - m2) <= tol

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

def is_bein(ch_name: str) -> bool:
    s = ch_name or ""
    return bool(BEIN_EN_RE.search(s) or BEIN_AR_RE.search(s))

def extract_bein_signal(ch_name: str):
    """
    يرجّع dict مثل: {"is_bein": True, "mena": True/False/None, "num": int|None}
    """
    disp = clean_channel_display(ch_name)
    s = to_western_digits(disp)
    is_b = is_bein(s)
    mena = None
    # EN
    if re.search(r'\bmena\b|\bmiddle\s*east\b', s, re.I):
        mena = True
    # AR (اختياري: "الشرق الأوسط")
    if re.search(r'الشرقالاوسط|الشرقالاوسط', normalize_text(s)):
        mena = True
    # رقم القناة
    mnum = re.search(r'\b(\d{1,2})\b', s)
    num = int(mnum.group(1)) if mnum else None
    return {"is_bein": bool(is_b), "mena": mena, "num": num}

def unique_preserving(seq):
    seen, out = set(), []
    for x in seq:
        k = str(x).lower().strip()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out

# ============ Whitelist (كما ذكرتها) ============
SUPPORTED_CHANNELS = [
    "MATCH! Futbol 1", "MATCH! Futbol 2", "MATCH! Futbol 3",
    "Football HD",
    "Sport TV1 Portugal HD", "Sport TV2 Portugal HD",
    "ESPN 1 Brazil", "ESPN 2 Brazil", "ESPN 3 Brazil", "ESPN 4 Brazil", "ESPN 5 Brazil", "ESPN 6 Brazil", "ESPN 7 Brazil",
    "DAZN 1 Portugal HD", "DAZN 2 Portugal HD", "DAZN 3 Portugal HD", "DAZN 4 Portugal HD", "DAZN 5 Portugal HD", "DAZN 6 Portugal HD",
    "MATCH! Premier HD", "Sky Sports Main Event HD", "Sky Sport Premier League HD",
    "IRIB Varzesh HD", "Persiana Sport HD",
    "MBC Action HD",
    "TNT Sports 1 HD", "TNT Sports 2 HD", "TNT Sports HD",
    "MBC masrHD", "MBC masr2HD", "ssc1 hd", "ssc2 hd", "Shahid MBC",
    "Thmanyah 1", "Thmanyah 2", "Thmanyah 3",
    "Starzplay 1", "Starzplay 2",
    "Abu Dhabi Sport 1", "Abu Dhabi Sport 2",
]
ALLOWED_SUBSTRINGS = {
    "ssc ", " ssc", "ssc1", "ssc2", "ssc3", "ssc4", "ssc5", "ssc6", "ssc7", "ssc extra", "ssc sport",
    "alkass", "al kass", "al-kass", "الكاس", "الكأس",
    "shahid", "shahid vip", "shahid mbc",
    "mbc action", "persiana sport", "irib varzesh", "football hd",
    "thmanyah", "starzplay", "abu dhabi sport"
}
_allowed_tokens = set()
for c in SUPPORTED_CHANNELS:
    cl = c.lower()
    _allowed_tokens.add(cl)
    _allowed_tokens.add(cl.replace(" hd", ""))

def is_supported_channel(name: str) -> bool:
    if not name:
        return False
    n = name.lower()
    if any(tok in n for tok in _allowed_tokens):
        return True
    if any(sub in n for sub in ALLOWED_SUBSTRINGS):
        return True
    return False

# ============ Canonicalization ============
CHANNEL_CANON_RULES = [
    (re.compile(r"thmanyah\s*(\d+)", re.I), lambda m: (f"thmanyah-{m.group(1)}", f"Thmanyah {m.group(1)}")),
    (re.compile(r"starzplay\s*(\d+)", re.I), lambda m: (f"starzplay-{m.group(1)}", f"Starzplay {m.group(1)}")),
    (re.compile(r"starzplay\b", re.I), lambda m: ("starzplay-1", "Starzplay 1")),
    (re.compile(r"abu\s*dhabi\s*sport\s*(\d+)", re.I), lambda m: (f"abudhabi-{m.group(1)}", f"Abu Dhabi Sport {m.group(1)}")),
    (re.compile(r"(al[\s-]?kass|الكاس|الكأس)\s*(?:channel\s*)?(\d+)", re.I),
     lambda m: (f"alkass-{m.group(2)}", f"Alkass {m.group(2)} HD")),
    (re.compile(r"^(?:الكاس|الكأس)\s*(\d+)", re.I), lambda m: (f"alkass-{m.group(1)}", f"Alkass {m.group(1)} HD")),
    (re.compile(r"^al\s*kass\s*(\d+)", re.I), lambda m: (f"alkass-{m.group(1)}", f"Alkass {m.group(1)} HD")),
    (re.compile(r"^alkass\s*(\d+)", re.I), lambda m: (f"alkass-{m.group(1)}", f"Alkass {m.group(1)} HD")),
    (re.compile(r"ssc\s*extra", re.I), lambda m: ("ssc-extra", "SSC Extra HD")),
    (re.compile(r"ssc\s*(\d+)", re.I), lambda m: (f"ssc-{m.group(1)}", f"SSC {m.group(1)} HD")),
    (re.compile(r"shahid\s*(vip)?", re.I), lambda m: ("shahid", "Shahid MBC")),
    (re.compile(r"football\s*hd", re.I), lambda m: ("football-hd", "Football HD")),
    (re.compile(r"sky\s*sport[s]?\s*premier\s*league", re.I),
     lambda m: ("sky-premier-league", "Sky Sport Premier League HD")),
    (re.compile(r"sky\s*sport[s]?\s*main\s*event", re.I),
     lambda m: ("sky-main-event", "Sky Sports Main Event HD")),
    (re.compile(r"dazn\s*1\s*portugal", re.I), lambda m: ("dazn-pt-1", "DAZN 1 Portugal HD")),
    (re.compile(r"dazn\s*2\s*portugal", re.I), lambda m: ("dazn-pt-2", "DAZN 2 Portugal HD")),
    (re.compile(r"dazn\s*3\s*portugal", re.I), lambda m: ("dazn-pt-3", "DAZN 3 Portugal HD")),
    (re.compile(r"mbc\s*action", re.I), lambda m: ("mbc-action", "MBC Action HD")),
    (re.compile(r"persiana\s*sport", re.I), lambda m: ("persiana-sport", "Persiana Sport HD")),
    (re.compile(r"irib\s*varzesh", re.I), lambda m: ("irib-varzesh", "IRIB Varzesh HD")),
    (re.compile(r"tnt\s*sports?\s*1", re.I), lambda m: ("tnt-1", "TNT Sports 1 HD")),
    (re.compile(r"tnt\s*sports?\s*2", re.I), lambda m: ("tnt-2", "TNT Sports 2 HD")),
]

def channel_key_and_display(raw_name: str) -> tuple[str, str]:
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

def dedupe_channels_preserve_order(ch_list: list[str]) -> list[str]:
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

# ============ Competition buckets ============
def comp_bucket(name: str) -> str:
    n = normalize_text(name)
    # UEFA CL
    if "uefachampions" in n or "دوريابطالاوروبا" in n or "championsleague" in n:
        return "UEFA-CL"
    # AFC Champions League Elite
    if "afcchampions" in n or "اسيا" in n or "دوريابطالاسيا" in n:
        # لو تحب تخصص "النخبة" ممكن تضيف كلمة النخبة هنا
        return "AFC-CL"
    # EFL / Carabao
    if "carabao" in n or "efl" in n or "leaguecup" in n or "الانجليزي" in n and "كاس" in n:
        return "ENG-EFL"
    # Morocco Botola
    if "botola" in n or "الدوريمغربي" in n or "المغربي" in n:
        return "MAR-BOT"
    return "OTHER"

# ============ Live index (EN) ============
def parse_title_to_teams(title: str):
    if not title: return None, None
    t = title.strip()
    for d in [r"\s+v(?:s)?\.?\s+", r"\s+-\s+", r"\s+–\s+", r"\s+—\s+", r"\s*:\s*", r"\s*\|\s*", r"\s*·\s*", r"\s*;\s*"]:
        parts = re.split(d, t, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return parts[0].strip(), parts[1].strip()
    return None, None

def extract_live_match(m: dict):
    home = (m.get("home") or m.get("home_team"))
    away = (m.get("away") or m.get("away_team"))
    if not (home and away):
        tl, tr = parse_title_to_teams(m.get("title") or "")
        home, away = tl, tr
    return (str(home).strip() if home else None,
            str(away).strip() if away else None)

def build_live_index(live_data: dict):
    idx = []
    for m in (live_data or {}).get("matches", []) or []:
        h, a = extract_live_match(m)
        if not (h and a):
            continue
        comp = m.get("competition") or ""
        bucket = comp_bucket(comp)
        t = m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff") or ""
        tmin = kickoff_to_minutes(t)

        # channels
        raw_channels = []
        for ck in ("channels_raw", "channels", "tv_channels", "broadcasters", "broadcaster"):
            if ck in m and m[ck]:
                raw = m[ck]
                if isinstance(raw, list):
                    raw_channels.extend([str(x) for x in raw])
                elif isinstance(raw, str):
                    raw_channels.extend(to_list_channels(raw))

        # beIN signal from live (للربط فقط)
        live_bein = None
        allowed = []
        for ch in raw_channels:
            disp = clean_channel_display(ch)
            if not disp:
                continue
            sig = extract_bein_signal(disp)
            if sig["is_bein"] and sig["num"]:
                # نحتفظ بإشارة beIN الأقوى (MENA أولاً)
                if (not live_bein) or (sig["mena"] and not live_bein.get("mena")):
                    live_bein = {"num": sig["num"], "mena": bool(sig["mena"])}
                # لا نضيف beIN لقائمة allowed
                continue
            if is_supported_channel(disp):
                allowed.append(disp)

        idx.append({
            "home_en": h,
            "away_en": a,
            "home_norm": normalize_text(h),
            "away_norm": normalize_text(a),
            "title": (m.get("title") or "").strip(),
            "title_norm": normalize_text(m.get("title") or ""),
            "competition": comp,
            "bucket": bucket,
            "tmin": tmin,
            "bein": live_bein,            # {"num": N, "mena": True/False} أو None
            "allowed_channels": dedupe_channels_preserve_order(allowed),
        })
    return idx

# ============ Yalla extraction ============
def collect_yalla_channels(y: dict) -> list[str]:
    keys = ["channels_raw","channels","tv_channels","channel","channel_ar","channel_en","broadcasters","broadcaster"]
    out = []
    for k in keys:
        if k in y and y[k]:
            out.extend(to_list_channels(y[k]))
    return unique_preserving(out)

def yalla_primary_channel(y: dict) -> str | None:
    chs = [clean_channel_display(c) for c in collect_yalla_channels(y)]
    return chs[0] if chs else None  # نرجّع قناة يلا كما هي (بدون أولوية خاصة)

def yalla_bein_signal(y: dict):
    for c in collect_yalla_channels(y):
        disp = clean_channel_display(c)
        sig = extract_bein_signal(disp)
        if sig["is_bein"] and sig["num"]:
            return {"num": sig["num"], "mena": sig["mena"] if sig["mena"] is not None else None}
    return None

def yalla_item(m: dict):
    comp = m.get("competition") or ""
    return {
        "home_ar": (m.get("home") or m.get("home_team") or "").strip(),
        "away_ar": (m.get("away") or m.get("away_team") or "").strip(),
        "title": (m.get("title_en") or m.get("title") or m.get("title_ar") or "").strip(),
        "title_norm": normalize_text(m.get("title_en") or m.get("title") or m.get("title_ar") or ""),
        "competition": comp,
        "bucket": comp_bucket(comp),
        "tmin": kickoff_to_minutes(m.get("kickoff_baghdad") or m.get("time_baghdad") or m.get("kickoff") or ""),
        "primary": yalla_primary_channel(m),
        "bein": yalla_bein_signal(m),
        "raw": m,
    }

# ============ Matching ============
def same_match_by_bein_and_time(y_it: dict, li: dict) -> bool:
    ys, ls = y_it.get("bein"), li.get("bein")
    if not ys or not ls:
        return False
    if ys["num"] != ls["num"]:
        return False
    if not minutes_close(y_it.get("tmin"), li.get("tmin"), tol=30):
        return False
    # لو عندنا MENA flags اثنينهم ومختلفات، نخليها تمشي لأن live يذكر MENA غالباً ويلا لا
    return True

def candidate_by_bucket_and_time(y_it: dict, live_idx: list[dict]) -> list[dict]:
    cand = []
    for li in live_idx:
        if y_it["bucket"] != "OTHER" and li["bucket"] != "OTHER":
            if y_it["bucket"] != li["bucket"]:
                continue
        if minutes_close(y_it.get("tmin"), li.get("tmin"), tol=30):
            cand.append(li)
    return cand

def parse_title_teams(title: str):
    if not title: return None, None
    return parse_title_to_teams(title)

def title_match_score(y_title: str, li: dict) -> float:
    # إذا العنوان إنجليزي على يلا، نقارنه مع فرق live
    l, r = parse_title_teams(y_title)
    if not (l and r):
        return 0.0
    nl, nr = normalize_text(l), normalize_text(r)
    Lh, La = li["home_norm"], li["away_norm"]
    # تطابق جزئي بالترتيبين
    score = 0.0
    if (nl and nr):
        cond1 = (nl in Lh or Lh in nl) and (nr in La or La in nr)
        cond2 = (nl in La or La in nl) and (nr in Lh or Lh in nr)
        score = 1.0 if (cond1 or cond2) else 0.0
    return score

def pick_best_live_for_yalla(y_it: dict, live_idx: list[dict]) -> dict | None:
    # 1) beIN + time
    for li in live_idx:
        if same_match_by_bein_and_time(y_it, li):
            return li

    # 2) bucket + time window
    cands = candidate_by_bucket_and_time(y_it, live_idx)
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        # 3) title_en/title: حاول نقيّمه
        best, best_s = None, -1.0
        for li in cands:
            s = title_match_score(y_it.get("title"), li)
            if s > best_s:
                best, best_s = li, s
        if best_s >= 1.0:
            return best
        # إذا ماكو عنوان واضح، رجّع ولا واحد (أفضل من مطابقة خاطئة)
    return None

# ============ Main ============
def filter_matches():
    # يلا شوت
    try:
        yresp = requests.get(YALLASHOOT_URL, timeout=25)
        yresp.raise_for_status()
        yalla = yresp.json()
    except Exception as e:
        print(f"[x] ERROR fetching yallashoot: {e}")
        return
    ylist = [yalla_item(m) for m in (yalla or {}).get("matches", []) or []]
    print(f"[i] Yalla matches: {len(ylist)}")

    # liveonsat
    try:
        with LIVEONSAT_PATH.open("r", encoding="utf-8") as f:
            live_data = json.load(f)
    except Exception as e:
        print(f"[!] WARN reading liveonsat: {e}")
        live_data = {"matches": []}
    live_idx = build_live_index(live_data)
    print(f"[i] Live index built: {len(live_idx)}")

    out_matches = []
    matched_extra = 0

    for y in ylist:
        primary = clean_channel_display(y.get("primary") or "")
        merged = [primary] if primary else []

        li = pick_best_live_for_yalla(y, live_idx)
        if li and li["allowed_channels"]:
            merged.extend(li["allowed_channels"])
            matched_extra += 1

        merged = dedupe_channels_preserve_order(merged)

        mraw = y["raw"]
        out_matches.append({
            "competition": mraw.get("competition") or "",
            "kickoff_baghdad": mraw.get("kickoff_baghdad") or mraw.get("time_baghdad") or mraw.get("kickoff") or "",
            "home_team": (mraw.get("home") or mraw.get("home_team") or "").strip(),
            "away_team": (mraw.get("away") or mraw.get("away_team") or "").strip(),
            "channels_raw": merged,
            "home_logo": mraw.get("home_logo"),
            "away_logo": mraw.get("away_logo"),
            "status_text": mraw.get("status_text"),
            "result_text": mraw.get("result_text"),
        })

    output = {
        "date": (yalla or {}).get("date"),
        "source_url": "yallashoot (primary) + liveonsat (extra whitelisted channels)",
        "matches": out_matches
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[✓] Done. yalla: {len(ylist)} | matched-with-live: {matched_extra} | written: {len(out_matches)}")

if __name__ == "__main__":
    filter_matches()

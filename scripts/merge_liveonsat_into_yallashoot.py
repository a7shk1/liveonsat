# scripts/merge_liveonsat_into_yallashoot.py
# يطابق مباريات يلا شوت مع بلوكات LiveOnSat ويضيف القنوات (raw + قنواتك) إلى matches/today.json

import json, re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
YALLA_PATH = REPO_ROOT / "matches" / "today.json"
LIVEO_PATH = REPO_ROOT / "matches" / "liveonsat_raw.json"

ALIASES = {
    # England
    "أرسنال": "Arsenal", "تشيلسي": "Chelsea", "مانشستر سيتي": "Manchester City",
    "مانشستر يونايتد": "Manchester United", "ليفربول": "Liverpool",
    "توتنهام": "Tottenham", "نيوكاسل": "Newcastle United", "وست هام يونايتد": "West Ham",
    "برينتفورد": "Brentford", "برايتون": "Brighton", "بورنموث": "Bournemouth",
    "ليستر سيتي": "Leicester", "إيفرتون": "Everton", "وولفرهامبتون": "Wolves",
    "أستون فيلا": "Aston Villa", "نوتنغهام فورست": "Nottingham Forest",
    "كريستال بالاس": "Crystal Palace", "فولهام": "Fulham",
    # Spain
    "ريال مدريد": "Real Madrid", "برشلونة": "Barcelona", "أتلتيكو مدريد": "Atletico Madrid",
    "إشبيلية": "Sevilla", "فالنسيا": "Valencia", "فياريال": "Villarreal",
    "أتلتيك بلباو": "Athletic Bilbao", "ريال سوسييداد": "Real Sociedad",
    "ريال بيتيس": "Real Betis", "ألافيس": "Alaves", "بلد الوليد": "Valladolid",
    "ألميريا": "Almeria",
    # Italy
    "يوفنتوس": "Juventus", "إنتر ميلان": "Inter Milan", "انتر ميلان": "Inter Milan",
    "إنتر": "Inter", "ميلان": "AC Milan", "إيه سي ميلان": "AC Milan",
    "نابولي": "Napoli", "روما": "Roma", "لاتسيو": "Lazio", "فيورنتينا": "Fiorentina",
    "أتلانتا": "Atalanta", "بولونيا": "Bologna", "تورينو": "Torino", "أودينيزي": "Udinese",
    "جنوى": "Genoa", "كالياري": "Cagliari", "إمبولي": "Empoli", "مونزا": "Monza",
    "ليتشي": "Lecce", "فيرونا": "Verona", "بارما": "Parma", "كومو": "Como",
    # France
    "باريس سان جيرمان": "PSG", "باريس سان-جيرمان": "PSG",
    "مارسيليا": "Marseille", "ليون": "Lyon", "ليل": "Lille", "موناكو": "Monaco", "نيس": "Nice",
    # Germany
    "بايرن ميونخ": "Bayern Munich", "بوروسيا دورتموند": "Borussia Dortmund",
    "لايبزيج": "RB Leipzig", "لايبزيغ": "RB Leipzig", "باير ليفركوزن": "Bayer Leverkusen",
    "شتوتجارت": "Stuttgart", "فولفسبورج": "Wolfsburg", "هوفنهايم": "Hoffenheim",
    "فرايبورج": "Freiburg", "مونشنغلادباخ": "Monchengladbach", "يونيون برلين": "Union Berlin",
    "آينتراخت فرانكفورت": "Eintracht Frankfurt", "هامبورج": "Hamburg",
    # Saudi
    "الهلال": "Al Hilal", "النصر": "Al Nassr", "الاتحاد": "Al Ittihad", "الأهلي": "Al Ahli",
    "القادسية": "Al Qadsiah",
}

MY_CHANNELS = [
    "starzplay1", "starzplay2",
    "abudhabi sport 1", "abudhabi sport 2",
    "beIN SPORTS 1", "beIN SPORTS 2", "beIN SPORTS 3", "beIN SPORTS 4",
    "beIN SPORTS 5", "beIN SPORTS 6", "beIN SPORTS 7", "beIN SPORTS 8", "beIN SPORTS 9",
    "DAZN 1", "DAZN 2", "DAZN 3", "DAZN 4", "DAZN 5", "DAZN 6",
    "ESPN", "ESPN 2", "ESPN 3", "ESPN 4", "ESPN 5", "ESPN 6", "ESPN 7",
    "Varzesh TV Iran", "Varzish TV Tajikistan", "Football HD Tajikistan", "IRIB TV 3 Iran", "Persiana Sports Iran",
    "Match! Futbol 1", "Match! Futbol 2", "Match! Futbol 3", "Match! TV Russia",
    "Sport TV 1", "Sport TV 2",
    "mbc Action", "MBC Drama+", "MBC Drama", "mbc masr", "mbc masr2",
    "TNT SPORTS", "TNT SPORTS 1", "TNT SPORTS 2",
    "Sky Sports Main Event HD", "Sky Premier League HD",
    "SSC 1", "SSC 2",
    "Thmanyah 1", "Thmanyah 2", "Thmanyah 3",
]

def _norm(s: str) -> str:
    import re
    s = (s or "").strip()
    s = re.sub(r"[^\w\s+!?.-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()

MY_SET = {_norm(x) for x in MY_CHANNELS}

def map_liveonsat_to_mine(name: str) -> str | None:
    import re
    raw = name or ""
    n = _norm(raw)

    m = re.search(r"\bbein\s+sports?\b.*?(\d{1,2})\b", n)
    if m:
        cand = f"beIN SPORTS {m.group(1)}"
        return cand if _norm(cand) in MY_SET else None

    m = re.search(r"\bdazn\b\s*(\d)\b", n)
    if m:
        cand = f"DAZN {m.group(1)}"
        return cand if _norm(cand) in MY_SET else None

    m = re.search(r"\bespn\b(?:\s*(\d))?", n)
    if m:
        num = m.group(1)
        cand = f"ESPN {num}" if num else "ESPN"
        return cand if _norm(cand) in MY_SET else None

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

    if "match" in n and "futbol" in n:
        m = re.search(r"futbol\s*(\d)", n)
        if m:
            cand = f"Match! Futbol {m.group(1)}"
            return cand if _norm(cand) in MY_SET else None
    if n.startswith("match") and "tv" in n:
        cand = "Match! TV Russia"
        return cand if _norm(cand) in MY_SET else None

    m = re.search(r"\bsport\s*tv\s*(\d)\b", n)
    if m:
        cand = f"Sport TV {m.group(1)}"
        return cand if _norm(cand) in MY_SET else None

    if "sky sports main event" in n:
        cand = "Sky Sports Main Event HD"
        return cand if _norm(cand) in MY_SET else None
    if "sky sports premier league" in n or "sky sport premier league" in n:
        cand = "Sky Premier League HD"
        return cand if _norm(cand) in MY_SET else None

    if n.startswith("tnt sports"):
        m = re.search(r"\btnt\s*sports\s*(\d)\b", n)
        cand = f"TNT SPORTS {m.group(1)}" if m else "TNT SPORTS"
        return cand if _norm(cand) in MY_SET else None

    if n.startswith("ssc"):
        m = re.search(r"\bssc\s*(\d)\b", n)
        if m:
            cand = f"SSC {m.group(1)}"
            return cand if _norm(cand) in MY_SET else None

    if "mbc action" in n:
        return "mbc Action"
    if "mbc drama+" in n or "mbc drama plus" in n:
        return "MBC Drama+"
    if re.search(r"\bmbc\s+drama\b", n):
        return "MBC Drama"
    if "mbc masr 2" in n or "masr 2" in n:
        return "mbc masr2"
    if "mbc masr" in n:
        return "mbc masr"

    if n.startswith("thmanyah"):
        m = re.search(r"\bthmanyah\s*(\d)\b", n)
        if m:
            cand = f"Thmanyah {m.group(1)}"
            return cand if _norm(cand) in MY_SET else None

    if "abudhabi sport 1" in n or "abu dhabi sport 1" in n:
        return "abudhabi sport 1"
    if "abudhabi sport 2" in n or "abu dhabi sport 2" in n:
        return "abudhabi sport 2"

    return None

def time_to_minutes(t: str | None) -> int | None:
    if not t: return None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", t)
    if not m: return None
    return int(m.group(1)) * 60 + int(m.group(2))

def find_match_block(live_items, home_ar, away_ar, yalla_time):
    home_en = ALIASES.get(home_ar, "").lower()
    away_en = ALIASES.get(away_ar, "").lower()
    if not home_en or not away_en:
        return None

    candidates = []
    target_minutes = time_to_minutes(yalla_time)

    for it in live_items:
        title = (it.get("title") or "").lower()
        if not title:
            continue
        if home_en.split()[0] in title and away_en.split()[0] in title:
            st = it.get("kickoff_baghdad")
            st_min = time_to_minutes(st)
            diff = abs((st_min - target_minutes)) if (st_min is not None and target_minutes is not None) else 9999
            candidates.append((diff, it))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]

def main():
    if not YALLA_PATH.exists() or not LIVEO_PATH.exists():
        raise SystemExit("today.json أو liveonsat_raw.json غير موجودين.")

    with YALLA_PATH.open("r", encoding="utf-8") as f:
        yalla = json.load(f)
    with LIVEO_PATH.open("r", encoding="utf-8") as f:
        liveo = json.load(f)

    live_items = liveo.get("matches", [])
    out_matches = []
    for m in yalla.get("matches", []):
        home = m.get("home") or ""
        away = m.get("away") or ""
        comp = m.get("competition") or ""
        time_bgd = m.get("time_baghdad")

        block = find_match_block(live_items, home, away, time_bgd)
        channels_raw = block.get("channels_raw") if block else []
        channels_raw = list(dict.fromkeys(channels_raw))

        channels_my = []
        for ch in channels_raw:
            mapped = map_liveonsat_to_mine(ch)
            if mapped and mapped not in channels_my:
                channels_my.append(mapped)

        if "الدوري الإيطالي" in comp:
            for extra in ("starzplay1", "starzplay2"):
                if extra not in channels_my:
                    channels_my.append(extra)

        nm = dict(m)
        nm["channels_raw"] = channels_raw
        nm["channel"] = channels_my
        out_matches.append(nm)

    out = dict(yalla)
    out["matches"] = out_matches

    with YALLA_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[merge] updated {YALLA_PATH} with liveonsat channels.")

if __name__ == "__main__":
    main()

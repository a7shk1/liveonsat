# scripts/filter_liveonsat_whitelist.py
import json, re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IN_PATH  = REPO_ROOT / "matches" / "liveonsat_raw.json"
OUT_PATH = REPO_ROOT / "matches" / "liveonsat_filtered.json"

LEAGUES = [
    r"\bPremier League\b",
    r"\bLa Liga\b|\bPrimera Division\b",
    r"\bSerie A\b",
    r"\bBundesliga\b",
    r"\bLigue 1\b",
]

DOMESTIC_CUPS = [
    r"\bCopa del Rey\b",
    r"\bSupercopa de España\b|\bSpanish Super Cup\b",
    r"\bCoppa Italia\b",
    r"\bSupercoppa Italiana\b|\bItalian Super Cup\b",
    r"\bCoupe de France\b|\bFrench Cup\b",
    r"\bTroph[ée]e des Champions\b|\bFrench Super Cup\b",
    r"\bDFB[- ]Pokal\b|\bGerman Cup\b",
    r"\bDFL[- ]Supercup\b|\bGerman Super Cup\b",
    r"\bFA Cup\b",
    r"\bEFL Cup\b|\bCarabao Cup\b|\bEnglish Football League Cup\b",
]

CLUB_INTL = [
    r"\bUEFA Champions League\b",
    r"\bUEFA Europa League\b",
    r"\bUEFA Europa Conference League\b",
    r"\bFIFA Club World Cup\b",
]

NATIONAL_TEAMS = [
    r"\bFIFA World Cup\b",
    r"\bWorld Cup Qualif(ier|ying|iers)\b|\bWC Qualifiers\b",
    r"\bWorld Cup Play[- ]offs?\b|\bIntercontinental Play[- ]offs?\b|\bPlay[- ]off\b",
    r"\bUEFA Nations League\b",
    r"\bUEFA European Championship\b|\bUEFA EURO\b|\bEURO(?:\s20\d{2})?\b",
    r"\bCopa Am[eé]rica\b",
    r"\bAfrica Cup of Nations\b|\bAFCON\b",
    r"\bAFC Asian Cup\b",
    r"\bArab Cup\b",
]

WHITELIST_PATTERNS = [*LEAGUES, *DOMESTIC_CUPS, *CLUB_INTL, *NATIONAL_TEAMS]
WHITELIST_REGEX = re.compile("|".join(f"(?:{p})" for p in WHITELIST_PATTERNS), re.IGNORECASE)

SPACES = re.compile(r"\s+")
def clean_text(s: str) -> str:
    if not s: return ""
    return SPACES.sub(" ", s).strip()

def match_competition(title: str):
    if not title:
        return None
    for pat in WHITELIST_PATTERNS:
        if re.search(pat, title, flags=re.IGNORECASE):
            return pat
    return None

def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Input JSON not found: {IN_PATH}")

    with IN_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("matches", [])
    filtered = []
    for it in items:
        title = clean_text(it.get("title") or "")
        tag = match_competition(title)
        if tag:
            new_item = dict(it)
            new_item["title"] = title
            new_item["matched_tag"] = tag
            filtered.append(new_item)

    out = dict(data)
    out["matches"] = filtered
    out["_filter_note"] = "Applied whitelist on title text only."

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[filter] kept {len(filtered)} / {len(items)}. Wrote {OUT_PATH}")

if __name__ == "__main__":
    main()

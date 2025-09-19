# scripts/send_notifications.py
# -*- coding: utf-8 -*-
import json
import os
import re
from pathlib import Path
from datetime import datetime, date, timezone

import firebase_admin
from firebase_admin import credentials, messaging

# ===== إعداد المنطقة الزمنية لبغداد =====
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    TZ_BAGHDAD = ZoneInfo("Asia/Baghdad")
except Exception:
    TZ_BAGHDAD = timezone.utc  # fallback بسيط

# ===== إعدادات الملفات =====
REPO_ROOT = Path(__file__).resolve().parents[1]
NOTIFIED_JSON = REPO_ROOT / "matches" / "notified.json"
SERVICE_KEY_PATH = REPO_ROOT / "serviceAccountKey.json"  # fallback لو موجود داخل الريبو

# ===== إعدادات Football API (بدون JSON وسيط) =====
API_BASE = "https://api.football-data.org/v4"
API_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN") or "d520ab265b61437697348dedc08a552a"  # fallback منّك
API_TIMEOUT = 20  # ثواني

# ===== تهيئة Firebase Admin =====
def init_firebase():
    """
    يهيئ Firebase باستخدام واحد من التالي (بالترتيب):
    1) متغيّر البيئة FCM_SERVICE_ACCOUNT: النص الكامل لمفتاح الخدمة JSON.
    2) GOOGLE_APPLICATION_CREDENTIALS: مسار ملف JSON على الدسك.
    3) ملف fallback داخل الريبو: serviceAccountKey.json
    """
    if firebase_admin._apps:
        return

    # 1) من متغيّر البيئة (JSON مباشرةً)
    env_json = os.environ.get("FCM_SERVICE_ACCOUNT")
    if env_json:
        try:
            payload = json.loads(env_json)
            cred = credentials.Certificate(payload)
            firebase_admin.initialize_app(cred)
            print("🔥 Firebase initialized from FCM_SERVICE_ACCOUNT env.")
            return
        except Exception as e:
            print(f"⚠️ فشل تهيئة Firebase من FCM_SERVICE_ACCOUNT: {e}")

    # 2) من مسار ملف (GOOGLE_APPLICATION_CREDENTIALS)
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac and Path(gac).exists() and Path(gac).stat().st_size > 0:
        print(f"✅ Using GOOGLE_APPLICATION_CREDENTIALS -> {gac}")
        cred = credentials.Certificate(gac)
        firebase_admin.initialize_app(cred)
        print("🔥 Firebase initialized.")
        return

    # 3) من ملف داخل الريبو
    if SERVICE_KEY_PATH.exists() and SERVICE_KEY_PATH.stat().st_size > 0:
        print(f"✅ Using repo key -> {SERVICE_KEY_PATH}")
        cred = credentials.Certificate(str(SERVICE_KEY_PATH))
        firebase_admin.initialize_app(cred)
        print("🔥 Firebase initialized.")
        return

    raise RuntimeError("❌ No Firebase service account found")

# ===== أدوات مساعدة =====
# يلتقط: مباشر / لايف / جاري(ة) الان/الآن / الشوط الأول/الثاني / دقائق مثل 12' أو 45'+2
LIVE_RE = re.compile(
    r"(?:\bLIVE\b|\bمباشر\b|لايف|جاري(?:ة)?\s*ال(?:آن|ان)|\bال(?:آن|ان)\b|"
    r"الشوط\s*(?:الأول|الاول|الثاني)|"
    r"\d{1,2}'(?:\+\d{1,2})?"
    r")",
    re.IGNORECASE
)

def is_live(status: str) -> bool:
    return bool(LIVE_RE.search((status or "").strip()))

def norm(s: str) -> str:
    return (s or "").strip().lower()

def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️  ملف JSON غير صالح ({path}): {e}")
        return default

def save_json(path: Path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        print(f"⚠️  فشل حفظ {path}: {e}")

def match_key(date_str: str, home: str, away: str, comp: str, kickoff: str) -> str:
    """مفتاح فريد لعدم تكرار الإرسال لنفس المباراة في نفس اليوم/الحدث."""
    return "|".join([date_str, norm(home), norm(away), norm(comp), norm(kickoff)])

# ===== جلب المباريات مباشرة من الـ API =====
def http_get(url: str) -> dict:
    import urllib.request, urllib.error
    if not API_TOKEN:
        raise RuntimeError("❌ FOOTBALL_DATA_TOKEN غير موجود")
    req = urllib.request.Request(url, headers={"X-Auth-Token": API_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"HTTPError {e.code}: {body}") from None

def to_hm_pairs(utc_iso: str) -> tuple[str, str]:
    """يرجع ('HH:MM UTC', 'HH:MM' بتوقيت بغداد)."""
    if not utc_iso:
        return "", ""
    dt_utc = datetime.fromisoformat(utc_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    try:
        dt_bg = dt_utc.astimezone(TZ_BAGHDAD)
    except Exception:
        dt_bg = dt_utc
    return dt_utc.strftime("%H:%M UTC"), dt_bg.strftime("%H:%M")

def map_status_for_regex(s: str) -> str:
    """تحويل حالات مزود البيانات إلى نص يلتقطه regex الحالي."""
    s = (s or "").upper()
    if s in ("IN_PLAY", "PAUSED", "LIVE"):
        return "LIVE"
    if s in ("FINISHED", "AWARDED", "POSTPONED", "SUSPENDED", "CANCELLED"):
        return s.title()
    return "Scheduled"

def fetch_matches_live():
    """
    يرجّع نفس الـ schema اللي السكربت القديم يتوقعه:
      { "date": "YYYY-MM-DD", "matches": [ {home_team, away_team, competition, status_text, kickoff, kickoff_baghdad} ] }
    لكن مباشرة من API بدون JSON وسيط.
    """
    today = date.today().isoformat()
    url = f"{API_BASE}/matches?dateFrom={today}&dateTo={today}"
    payload = http_get(url)
    out_matches = []
    for m in (payload.get("matches") or []):
        home = (m.get("homeTeam") or {}).get("name") or ""
        away = (m.get("awayTeam") or {}).get("name") or ""
        comp = (m.get("competition") or {}).get("name") or ""
        status_text = map_status_for_regex(m.get("status"))
        utc_iso = m.get("utcDate")
        kickoff_utc, kickoff_bg = to_hm_pairs(utc_iso) if utc_iso else ("", "")
        out_matches.append({
            "home_team": home,
            "away_team": away,
            "competition": comp,
            "status_text": status_text,
            "kickoff": kickoff_utc,
            "kickoff_baghdad": kickoff_bg
        })
    return {"date": today, "matches": out_matches}

# ===== إرسال إشعار =====
def send_topic_notification(title: str, body: str, topic: str = "matches", dry: bool = False):
    if dry:
        print(f"🧪 DRY_RUN — كان راح يُرسل ({topic}): {title} — {body}")
        return
    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        topic=topic,
    )
    resp = messaging.send(msg)
    print(f"✅ sent to topic: {resp} | {title} — {body}")

def send_token_notification(title: str, body: str, token: str, dry: bool = False):
    if dry:
        print(f"🧪 DRY_RUN — كان راح يُرسل (token): {title} — {body}")
        return
    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        token=token,
    )
    resp = messaging.send(msg)
    print(f"✅ sent to token: {resp} | {title} — {body}")

def subscribe_token_to_topic(token: str, topic: str = "matches"):
    """يسجّل التوكن في Topic عبر Firebase Admin (مفيد لفحص الاشتراك)."""
    resp = messaging.subscribe_to_topic([token], topic)
    print(f"✅ subscribe_to_topic('{topic}'): success={resp.success_count} failure={resp.failure_count}")
    if resp.failure_count:
        for e in resp.errors:
            print(f"  - idx {e.index} error: {e.reason}")

# ===== الرئيسي =====
def main():
    dry_run = os.environ.get("DRY_RUN") in ("1", "true", "True")

    # 1) تهيئة Firebase
    init_firebase()

    # 2) (اختياري للاختبار) إرسال مباشر للتوكن وتمكين اشتراكه بالـ topic
    test_token = os.environ.get("TEST_DEVICE_TOKEN")
    if test_token:
        try:
            subscribe_token_to_topic(test_token, "matches")
            send_token_notification("🔔 Test", "Hello from CI", test_token, dry=dry_run)
            # إرسال عبر الـ topic أيضًا للتأكد من المسار
            send_topic_notification("📢 Topic Test", "Hello matches!", topic="matches", dry=dry_run)
        except Exception as e:
            print(f"⚠️ فشل إرسال/اشتراك التوكن: {e}")

    # 3) جلب المباريات لايف مباشرة من الـ API (بدون JSON وسيط)
    try:
        data = fetch_matches_live()
    except Exception as e:
        print(f"❌ فشل جلب المباريات من الـ API: {e}")
        print("ℹ️ لن يتم إرسال إشعارات في هذه الدورة.")
        return

    date_str = data.get("date") or datetime.utcnow().date().isoformat()
    matches = data.get("matches") or []

    # 4) قراءة سجل الإشعارات السابقة
    notified = load_json(NOTIFIED_JSON, {})  # dict: key -> True
    changed = False
    sent_count = 0

    for m in matches:
        home = m.get("home_team") or "فريق A"
        away = m.get("away_team") or "فريق B"
        status = m.get("status_text") or ""
        comp = m.get("competition") or ""
        kickoff = m.get("kickoff_baghdad") or m.get("kickoff") or ""

        key = match_key(date_str, home, away, comp, kickoff)

        if is_live(status) and not notified.get(key):
            title = "📺 شاهد الآن"
            body_parts = [f"{home} × {away}"]
            if comp:
                body_parts.append(f"— {comp}")
            if kickoff:
                body_parts.append(f"({kickoff})")
            body = " ".join(body_parts)

            try:
                send_topic_notification(title, body, topic="matches", dry=dry_run)
                notified[key] = True
                changed = True
                sent_count += 1
            except Exception as e:
                print(e)
        else:
            print(f"skip: {home} vs {away} | status='{status}' | already_notified={bool(notified.get(key))}")

    # 5) حفظ السجل
    if changed and not dry_run:
        save_json(NOTIFIED_JSON, notified)
        print(f"📝 updated notified.json ({len(notified)} entries)")

    if sent_count == 0:
        print("ℹ️ لا توجد مباريات Live جديدة الآن.")
    else:
        print(f"✅ تم إرسال {sent_count} إشعار/إشعارات.")

if __name__ == "__main__":
    main()

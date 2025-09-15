# scripts/send_notifications.py
# -*- coding: utf-8 -*-
import json
import os
import re
import time
from pathlib import Path
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, messaging

# ===== إعدادات الملفات =====
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_JSON = REPO_ROOT / "matches" / "filtered_matches.json"
NOTIFIED_JSON = REPO_ROOT / "matches" / "notified.json"
# fallback فقط إن وُجد ملف داخل الريبو (غير مُستحسن)
SERVICE_KEY_PATH = REPO_ROOT / "serviceAccountKey.json"

# ===== تهيئة Firebase Admin =====
def init_firebase():
    """يهيئ Firebase باستخدام GOOGLE_APPLICATION_CREDENTIALS أو ملف fallback."""
    if firebase_admin._apps:
        return

    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac and Path(gac).exists() and Path(gac).stat().st_size > 0:
        print(f"✅ Using GOOGLE_APPLICATION_CREDENTIALS -> {gac}")
        cred = credentials.Certificate(gac)
    elif SERVICE_KEY_PATH.exists() and SERVICE_KEY_PATH.stat().st_size > 0:
        print(f"✅ Using repo key -> {SERVICE_KEY_PATH}")
        cred = credentials.Certificate(str(SERVICE_KEY_PATH))
    else:
        raise RuntimeError(
            "❌ No Firebase service account found.\n"
            "Set GOOGLE_APPLICATION_CREDENTIALS to a valid JSON path, "
            f"or add a valid file at {SERVICE_KEY_PATH}"
        )

    firebase_admin.initialize_app(cred)
    print("🔥 Firebase initialized.")

# ===== أدوات مساعدة =====
# يشمل: جاري الآن / جارية الآن / الآن / مباشر / LIVE
LIVE_RE = re.compile(r"(?:\bمباشر\b|جاري(?:ة)?\s*ال?آن|\bال?آن\b|\bLIVE\b)", re.IGNORECASE)

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
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"⚠️  فشل حفظ {path}: {e}")

def match_key(date_str: str, home: str, away: str, comp: str, kickoff: str) -> str:
    """مفتاح فريد لعدم تكرار الإرسال لنفس المباراة في نفس اليوم/الحدث."""
    return "|".join([date_str, norm(home), norm(away), norm(comp), norm(kickoff)])

# ===== إرسال إشعار =====
def send_topic_notification(title: str, body: str, topic: str = "matches", dry: bool = False):
    if dry:
        print(f"🧪 DRY_RUN — كان راح يُرسل ({topic}): {title} — {body}")
        return

    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        topic=topic,
    )

    # محاولة واحدة + إعادة محاولة بسيطة إذا صار خطأ مؤقت
    last_err = None
    for attempt in range(2):
        try:
            resp = messaging.send(msg)
            print(f"✅ sent: {resp} | {title} — {body}")
            return
        except Exception as e:
            last_err = e
            print(f"⚠️  إرسال فشل (محاولة {attempt+1}): {e}")
            time.sleep(1.0)

    # لو فشل بعد المحاولات
    raise RuntimeError(f"❌ فشل إرسال الإشعار نهائيًا: {last_err}")

# ===== الرئيسي =====
def main():
    dry_run = os.environ.get("DRY_RUN") in ("1", "true", "True")

    # 1) تهيئة Firebase
    init_firebase()

    # 2) قراءة المباريات
    data = load_json(MATCHES_JSON, {"date": "", "matches": []})
    date_str = data.get("date") or datetime.utcnow().date().isoformat()
    matches = data.get("matches") or []

    # 3) قراءة سجل الإشعارات السابقة
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
            # أضِف الوقت إن وُجد
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
                # لا نمنع باقي الإشعارات، فقط نطبع الخطأ
                print(e)

    # 4) حفظ السجل
    if changed and not dry_run:
        save_json(NOTIFIED_JSON, notified)
        print(f"📝 updated notified.json ({len(notified)} entries)")

    if sent_count == 0:
        print("ℹ️ لا توجد مباريات Live جديدة الآن.")
    else:
        print(f"✅ تم إرسال {sent_count} إشعار/إشعارات.")

if __name__ == "__main__":
    main()

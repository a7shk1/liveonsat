# scripts/send_notifications.py
# -*- coding: utf-8 -*-
import json
import os
import re
from pathlib import Path
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, messaging

# ------ إعدادات المسارات ------
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_JSON = REPO_ROOT / "matches" / "filtered_matches.json"
NOTIFIED_JSON = REPO_ROOT / "matches" / "notified.json"
# fallback: يُنشأ بالوركفلو من Secrets أو موجود داخل الريبو
SERVICE_KEY_PATH = REPO_ROOT / "serviceAccountKey.json"

# ------ تهيئة Firebase Admin ------
def _cred_from_env_or_file():
    """
    يحاول بهالترتيب:
    1) GOOGLE_APPLICATION_CREDENTIALS -> ملف
    2) FIREBASE_SERVICE_ACCOUNT_JSON   -> JSON نصّي
    3) FIREBASE_SERVICE_ACCOUNT_B64    -> JSON Base64
    4) SERVICE_KEY_PATH                -> ملف في الريبو
    """
    # 1) GAC path
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac:
        p = Path(gac)
        if p.exists() and p.stat().st_size > 0:
            return credentials.Certificate(str(p))
        else:
            print(f"⚠️  GOOGLE_APPLICATION_CREDENTIALS يشير لملف غير موجود/فارغ: {p}")

    # 2) JSON نصّي
    raw_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if raw_json:
        try:
            data = json.loads(raw_json)
            return credentials.Certificate(data)
        except Exception as e:
            print(f"⚠️  محتوى FIREBASE_SERVICE_ACCOUNT_JSON غير صالح JSON: {e}")

    # 3) JSON Base64
    b64 = os.environ.get("FIREBASE_SERVICE_ACCOUNT_B64")
    if b64:
        try:
            import base64
            decoded = base64.b64decode(b64).decode("utf-8")
            data = json.loads(decoded)
            return credentials.Certificate(data)
        except Exception as e:
            print(f"⚠️  محتوى FIREBASE_SERVICE_ACCOUNT_B64 غير صالح Base64/JSON: {e}")

    # 4) ملف داخل الريبو
    if SERVICE_KEY_PATH.exists() and SERVICE_KEY_PATH.stat().st_size > 0:
        return credentials.Certificate(str(SERVICE_KEY_PATH))

    raise RuntimeError(
        "لم يتم العثور على بيانات حساب Firebase. "
        "وفّر أحد الخيارات: GOOGLE_APPLICATION_CREDENTIALS (مسار ملف) "
        "أو FIREBASE_SERVICE_ACCOUNT_JSON (نص JSON) "
        "أو FIREBASE_SERVICE_ACCOUNT_B64 (Base64) "
        f"أو ضع ملفًا صالحًا في: {SERVICE_KEY_PATH}"
    )

def init_firebase():
    if firebase_admin._apps:
        return
    cred = _cred_from_env_or_file()
    firebase_admin.initialize_app(cred)
    print("✅ Firebase initialized.")

# ------ أدوات مساعدة ------
LIVE_RE = re.compile(r"(?:جاري(?:ة)?\s*الا?ن|LIVE)", re.IGNORECASE)

def is_live(status: str) -> bool:
    return bool(LIVE_RE.search(status or ""))

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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ------ إرسال إشعار إلى Topic عام (matches) ------
def send_topic_notification(title: str, body: str, dry: bool = False):
    if dry:
        print(f"🧪 DRY_RUN — كان راح يُرسل: {title} — {body}")
        return
    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        topic="matches",
    )
    resp = messaging.send(msg)
    print(f"✅ sent: {resp} | {title} — {body}")

# ------ الرئيسي ------
def main():
    # 0) وضع تجربة؟
    dry_run = os.environ.get("DRY_RUN") in ("1", "true", "True")

    # 1) جهّز Firebase
    init_firebase()

    # 2) اقرا ملف المباريات
    data = load_json(MATCHES_JSON, {"date": "", "matches": []})
    date_str = data.get("date") or datetime.utcnow().date().isoformat()
    matches = data.get("matches", [])

    # 3) اقرا سجل الإشعارات السابقة
    notified = load_json(NOTIFIED_JSON, {})  # dict: key -> True
    changed = False

    for m in matches:
        home = m.get("home_team") or "فريق A"
        away = m.get("away_team") or "فريق B"
        status = m.get("status_text") or ""
        comp = m.get("competition") or ""

        # مفتاح فريد لكل مباراة بنفس اليوم
        key = f"{date_str}|{norm(home)}|{norm(away)}"

        if is_live(status) and not notified.get(key):
            title = "📺 شاهد الآن"
            body = f"{home} × {away} — {comp}"
            send_topic_notification(title, body, dry=dry_run)
            notified[key] = True
            changed = True

    # 4) احفظ السجل إذا صار إرسال
    if changed and not dry_run:
        save_json(NOTIFIED_JSON, notified)
        print(f"📝 updated notified.json ({len(notified)} entries)")
    else:
        print("ℹ️ لا توجد مباريات Live جديدة الآن." if not changed else "🧪 DRY_RUN — لم يُحدّث notified.json")

if __name__ == "__main__":
    main()

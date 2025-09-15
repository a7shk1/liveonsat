# scripts/send_notifications.py
# -*- coding: utf-8 -*-
import json
import re
from pathlib import Path
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, messaging

# ------ إعدادات المسارات ------
REPO_ROOT = Path(__file__).resolve().parents[1]
MATCHES_JSON = REPO_ROOT / "matches" / "filtered_matches.json"
NOTIFIED_JSON = REPO_ROOT / "matches" / "notified.json"
SERVICE_KEY_PATH = REPO_ROOT / "serviceAccountKey.json"  # يُنشأ بالوركفلو من Secrets

# ------ تهيئة Firebase Admin ------
def init_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(SERVICE_KEY_PATH))
        firebase_admin.initialize_app(cred)

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
    except Exception:
        return default

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ------ إرسال إشعار إلى Topic عام (matches) ------
def send_topic_notification(title: str, body: str):
    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        topic="matches",  # كل الأجهزة المشترِكة بهذا التوبيك تستلم
    )
    resp = messaging.send(msg)
    print(f"✅ sent: {resp} | {title} — {body}")

# ------ الرئيسي ------
def main():
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
        kickoff = m.get("kickoff_baghdad") or ""
        comp = m.get("competition") or ""

        # مفتاح فريد لكل مباراة بنفس اليوم
        key = f"{date_str}|{norm(home)}|{norm(away)}"

        if is_live(status) and not notified.get(key):
            title = "📺 شاهد الآن"
            body = f"{home} × {away} — {comp}"
            send_topic_notification(title, body)
            notified[key] = True
            changed = True

    # 4) احفظ السجل إذا صار إرسال
    if changed:
        save_json(NOTIFIED_JSON, notified)
        print(f"📝 updated notified.json ({len(notified)} entries)")
    else:
        print("ℹ️ لا توجد مباريات Live جديدة الآن.")

if __name__ == "__main__":
    main()

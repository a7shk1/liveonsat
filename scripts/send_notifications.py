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
# fallback فقط إن وُجد ملف داخل الريبو (غير مُستحسن)
SERVICE_KEY_PATH = REPO_ROOT / "serviceAccountKey.json"

# ------ تهيئة Firebase Admin ------
def init_firebase():
    if firebase_admin._apps:
        return

    from pathlib import Path
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

        key = f"{date_str}|{norm(home)}|{norm(away)}"

        if is_live(status) and not notified.get(key):
            title = "📺 شاهد الآن"
            body = f"{home} × {away} — {comp}"
            send_topic_notification(title, body, dry=dry_run)
            notified[key] = True
            changed = True

    if changed and not dry_run:
        save_json(NOTIFIED_JSON, notified)
        print(f"📝 updated notified.json ({len(notified)} entries)")
    else:
        print("ℹ️ لا توجد مباريات Live جديدة الآن." if not changed else "🧪 DRY_RUN — لم يُحدّث notified.json")

if __name__ == "__main__":
    main()

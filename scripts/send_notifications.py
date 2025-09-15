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
SERVICE_KEY_PATH = REPO_ROOT / "serviceAccountKey.json"  # fallback

# ===== تهيئة Firebase Admin =====
def init_firebase():
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
        raise RuntimeError("❌ No Firebase service account found")

    firebase_admin.initialize_app(cred)
    print("🔥 Firebase initialized.")

# ===== أدوات مساعدة =====
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

# ===== الرئيسي =====
def main():
    dry_run = os.environ.get("DRY_RUN") in ("1", "true", "True")

    init_firebase()

    # --- إرسال مباشر إذا تم تمرير TEST_DEVICE_TOKEN ---
    test_token = os.environ.get("TEST_DEVICE_TOKEN")
    if test_token:
        try:
            send_token_notification("🔔 Test", "Hello from CI", test_token, dry=dry_run)
        except Exception as e:
            print(f"⚠️ فشل إرسال للتوكن: {e}")

    # --- منطق المباريات (topic matches) ---
    data = load_json(MATCHES_JSON, {"date": "", "matches": []})
    date_str = data.get("date") or datetime.utcnow().date().isoformat()
    matches = data.get("matches") or []

    notified = load_json(NOTIFIED_JSON, {})
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

    if changed and not dry_run:
        save_json(NOTIFIED_JSON, notified)
        print(f"📝 updated notified.json ({len(notified)} entries)")

    if sent_count == 0:
        print("ℹ️ لا توجد مباريات Live جديدة الآن.")
    else:
        print(f"✅ تم إرسال {sent_count} إشعار/إشعارات.")

if __name__ == "__main__":
    main()

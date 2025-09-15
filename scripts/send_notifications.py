def init_firebase():
    if firebase_admin._apps:
        return

    import os
    from pathlib import Path
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if gac and Path(gac).exists() and Path(gac).stat().st_size > 0:
        print(f"✅ Using GOOGLE_APPLICATION_CREDENTIALS -> {gac}")
        cred = credentials.Certificate(gac)
    else:
        # fallback: الملف داخل الريبو لو موجود
        if SERVICE_KEY_PATH.exists() and SERVICE_KEY_PATH.stat().st_size > 0:
            print(f"✅ Using repo key -> {SERVICE_KEY_PATH}")
            cred = credentials.Certificate(str(SERVICE_KEY_PATH))
        else:
            raise RuntimeError(
                "❌ No Firebase service account found.\n"
                "Set GOOGLE_APPLICATION_CREDENTIALS to a valid JSON path, "
                f"or add a valid file at {SERVICE_KEY_PATH}"
            )

    firebase_admin.initialize_app(cred)

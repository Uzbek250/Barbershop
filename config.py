"""Sozlamalar.

Tokenlarni ikki yo'l bilan berish mumkin:
  1) shu fayldagi "BU_YERGA..." joylarni o'zgartirib (faqat PRIVATE repoda!),
  2) yoki Render > Environment bo'limida BOT_TOKEN va ADMIN_IDS yozib (tavsiya).
"""
import hashlib
import os
import re
from datetime import timedelta, timezone

try:  # lokalda .env faylni o'qiydi (ixtiyoriy)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ===================== SHU YERNI TO'LDIRING =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "BU_YERGA_BOT_TOKENNI_YOZING")  # @BotFather bergan token
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "BU_YERGA_ADMIN_ID_NI_YOZING")  # Telegram ID: 123456789 yoki 111,222
SHOP_NAME = os.getenv("SHOP_NAME", "Sartaroshxona")  # mijozlarga ko'rinadigan nom
# ================================================================

ADMIN_IDS = {int(x) for x in re.split(r"[,\s;]+", ADMIN_IDS_RAW) if x.isdigit()}
AVG_SERVICE_MINUTES = int(os.getenv("AVG_SERVICE_MINUTES", "20"))  # bitta mijozga ketadigan taxminiy vaqt
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./navbat.db")  # bo'sh bo'lsa SQLite
BASE_URL = (os.getenv("BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
WEBHOOK_SECRET = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()
TZ = timezone(timedelta(hours=5))  # O'zbekiston vaqti (UTC+5)


def check() -> None:
    if ":" not in BOT_TOKEN or BOT_TOKEN.startswith("BU_YERGA"):
        raise SystemExit("BOT_TOKEN kiritilmagan: config.py yoki muhit o'zgaruvchisiga @BotFather tokenini yozing.")
    if not ADMIN_IDS:
        print("DIQQAT: ADMIN_IDS kiritilmagan - admin menyusi hech kimga ochilmaydi.")

# 💈 Navbat boti (Telegram)

Mijoz botga kirib navbatga yoziladi va navbatini jonli ko'radi. Sartarosh (admin) shu botning o'zida
**✅ Yakunlash** tugmasini bosadi, bot esa keyingi 2 mijozga o'zi xabar yuboradi. Navbat har kuni 1 dan boshlanadi.

## 1. Tayyorlash
1. Telegram'da **@BotFather** → `/newbot` → **token** oling.
2. **@userinfobot** ga `/start` yozing → sartarosh (va o'zingizning) **ID** raqamini oling.
3. Ikkalasini `config.py` dagi "SHU YERNI TO'LDIRING" joyiga yozing,
   **yoki** (tavsiya) Render'da `BOT_TOKEN` va `ADMIN_IDS` muhit o'zgaruvchisi sifatida bering.
   > Token yozilgan `config.py` ni faqat **private** GitHub repoga yuklang. Aks holda tokenni env orqali bering.

## 2. Kompyuterda sinash
```bash
pip install -r requirements.txt
python main.py        # BASE_URL yo'q -> polling rejimi, SQLite baza
```
Python 3.10+ kerak. Admin menyusini ko'rish uchun `ADMIN_IDS` ga o'z ID'ingizni ham qo'shing.
Mijoz sifatida sinash: admin menyusidagi **👤 Mijoz menyusi** (yoki ikkinchi akkauntdan kiring).

## 3. Render'ga chiqarish
1. Kodni GitHub'ga yuklang.
2. Render → **New → Blueprint** → repo'ni tanlang (`render.yaml` hammasini o'zi sozlaydi).
   So'ralganda `BOT_TOKEN` va `ADMIN_IDS` ni kiriting.
3. Deploy tugagach bot o'zi webhook o'rnatadi (qo'shimcha sozlash kerak emas). Botga `/start` yozing.

Blueprintsiz qo'lda: **New → Web Service**
- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Environment: `PYTHON_VERSION=3.12.8`, `BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL` (PostgreSQL)

## Eslatmalar
- Render bepul web xizmati 15 daqiqa so'rovsiz qolsa uxlaydi; birinchi xabar 30-60 soniya kechikishi mumkin.
  Ish rejimida pullik reja oling yoki `https://SIZNING-APP.onrender.com/health` ni UptimeRobot bilan 5 daqiqada bir pinglang.
- Render'ning bepul PostgreSQL bazasi cheklangan muddatga beriladi. Doimiy bepul baza uchun Neon.tech'da baza ochib,
  `DATABASE_URL` ga uning manzilini yozing (`render.yaml` dagi `databases` qismini olib tashlang).
- Xabar matnlari: `services.py` boshidagi `TXT_CALLED` va `TXT_NEAR`.
- Taxminiy kutish vaqti: `AVG_SERVICE_MINUTES` (bitta mijozga ketadigan daqiqa).

## 8. Texnik: bazani tozalash

Navbat tarixini (bugungi navbat, mijozlar) tozalash uchun maxfiy kalit bilan:

```bash
curl -X POST https://navbat-bot-vvfe.onrender.com/admin/clear \
  -H "X-Clear-Secret: <sha256(BOT_TOKEN)>"
```

Kalit = `BOT_TOKEN` ning SHA-256 hash'i. `queue_entries` jadvali tozalanadi va
`settings` (navbat ochiq/yopiq) qayta boshlang'ich holatga qaytadi.

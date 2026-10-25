"""Kirish nuqtasi: FastAPI + Telegram webhook (Render uchun). BASE_URL bo'lmasa - polling (lokal sinov)."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from sqlalchemy import text

import config

config.check()  # token kiritilmagan bo'lsa, tushunarli xato bilan to'xtaydi

from db import SessionLocal, init_db  # noqa: E402
from handlers import admin, client, common  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("navbat")

bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(common)
dp.include_router(admin)
dp.include_router(client)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    polling = None
    if config.BASE_URL:
        await bot.set_webhook(
            url=f"{config.BASE_URL}/webhook",
            secret_token=config.WEBHOOK_SECRET,
            allowed_updates=dp.resolve_used_update_types(),
        )
        log.info("Webhook o'rnatildi: %s/webhook", config.BASE_URL)
    else:
        await bot.delete_webhook()
        polling = asyncio.create_task(dp.start_polling(bot, handle_signals=False, close_bot_session=False))
        log.info("BASE_URL yo'q - polling rejimida ishlayapti (lokal sinov)")
    yield
    if polling:
        polling.cancel()
    await bot.session.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


@app.api_route("/", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok"}


@app.post("/admin/clear")
async def admin_clear(request: Request):
    """Vaqtinchalik: navbat bazasini tozalash (maxfiy kalit bilan)."""
    if request.headers.get("X-Clear-Secret") != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=403)
    async with SessionLocal() as s:
        await s.execute(text("TRUNCATE TABLE queue_entries RESTART IDENTITY"))
        await s.execute(text("DELETE FROM settings"))
        await s.commit()
    return {"ok": True}


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=403)
    update = Update.model_validate(await request.json(), context={"bot": bot})
    background.add_task(dp.feed_update, bot, update)  # Telegram'ga darhol javob, ishlov keyin
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

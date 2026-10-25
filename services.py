"""Navbat mantig'i: yozilish, yakunlash, bekor qilish, xabarlar va jonli chiptalar."""
import asyncio
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from sqlalchemy import func, select

import config
import keyboards as kb
from db import ACTIVE, CANCELLED, DONE, SERVING, SKIPPED, WAITING, QueueEntry, SessionLocal, Setting, now, today

log = logging.getLogger("navbat")
queue_lock = asyncio.Lock()  # navbatni o'zgartiradigan amallar bir vaqtda bitta bo'lsin

# Mijozlarga boradigan avtomatik xabarlar (matnni shu yerda o'zgartirish mumkin)
TXT_CALLED = "🔔 <b>Navbatingiz keldi!</b>\nTezroq keling, sartarosh sizni kutmoqda. ✂️"
TXT_NEAR = "⏳ <b>Navbatingiz yaqinlashdi!</b>\nSizdan oldin 1 kishi qoldi. Tayyorlanib, tezroq keling."


# ------------------------------------------------------------------ yordamchilar
def esc(text) -> str:
    return html.escape(text or "")


def who(e: QueueEntry) -> str:
    return f"№{e.number} {esc(e.name)}"


def who_full(e: QueueEntry) -> str:
    return who(e) + (f" ({esc(e.phone)})" if e.phone else "")


def stamp() -> str:
    return datetime.now(config.TZ).strftime("%H:%M:%S")


_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 9:
        digits = "998" + digits
    return "+" + digits if 10 <= len(digits) <= 15 else None


def parse_name_phone(text: str) -> tuple[str, str | None]:
    """'Ali 901234567' -> ('Ali', '+998901234567')."""
    found = _PHONE_RE.search(text)
    phone = normalize_phone(found.group()) if found else None
    name = _PHONE_RE.sub(" ", text) if found else text
    return " ".join(name.split())[:40] or "Mijoz", phone


# ------------------------------------------------------------------ Telegram
async def _try(call):
    try:
        return await call()
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after)
        try:
            return await call()
        except TelegramAPIError as exc2:
            log.warning("Telegram xatosi (qayta urinishda): %s", exc2)
    except TelegramAPIError as exc:
        log.info("Telegram xatosi: %s", exc)
    return None


async def safe_send(bot: Bot, chat_id: int, text: str, **kw):
    return await _try(lambda: bot.send_message(chat_id, text, **kw))


async def safe_edit(bot: Bot, chat_id: int, message_id: int, text: str, markup=None):
    return await _try(
        lambda: bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
    )


async def safe_delete(bot: Bot, chat_id: int, message_id: int):
    return await _try(lambda: bot.delete_message(chat_id, message_id))


async def tell_admins(bot: Bot, text: str, skip_id: int | None = None) -> None:
    for admin_id in config.ADMIN_IDS:
        if admin_id != skip_id:
            await safe_send(bot, admin_id, text)


# ------------------------------------------------------------------ o'qish
async def is_queue_open(s) -> bool:
    row = await s.get(Setting, "queue_open")
    return row is None or row.value == "1"


async def set_queue_open(value: bool) -> None:
    async with SessionLocal() as s:
        row = await s.get(Setting, "queue_open")
        if row:
            row.value = "1" if value else "0"
        else:
            s.add(Setting(key="queue_open", value="1" if value else "0"))
        await s.commit()


async def load_queue(s) -> tuple[QueueEntry | None, list[QueueEntry]]:
    """Bugungi (xizmatdagi mijoz, kutayotganlar ro'yxati)."""
    rows = (
        await s.scalars(
            select(QueueEntry)
            .where(QueueEntry.queue_date == today(), QueueEntry.status.in_(ACTIVE))
            .order_by(QueueEntry.number)
        )
    ).all()
    serving = next((r for r in rows if r.status == SERVING), None)
    return serving, [r for r in rows if r.status == WAITING]


async def get_active_entry(s, tg_id: int) -> QueueEntry | None:
    return await s.scalar(
        select(QueueEntry)
        .where(QueueEntry.queue_date == today(), QueueEntry.tg_id == tg_id, QueueEntry.status.in_(ACTIVE))
        .limit(1)
    )


async def day_stats(s) -> dict[str, int]:
    rows = await s.execute(
        select(QueueEntry.status, func.count()).where(QueueEntry.queue_date == today()).group_by(QueueEntry.status)
    )
    return {status: count for status, count in rows.all()}


# ------------------------------------------------------------------ o'zgartirish
async def join_queue(name: str, phone: str | None, tg_id: int | None) -> tuple[str, QueueEntry | None]:
    """('ok' | 'exists' | 'closed', entry). tg_id=None - admin qo'lda qo'shmoqda."""
    async with queue_lock, SessionLocal() as s:
        if tg_id is not None:
            existing = await get_active_entry(s, tg_id)
            if existing:
                return "exists", existing
            if not await is_queue_open(s):
                return "closed", None
        last = await s.scalar(select(func.max(QueueEntry.number)).where(QueueEntry.queue_date == today()))
        entry = QueueEntry(queue_date=today(), number=(last or 0) + 1, tg_id=tg_id, name=name, phone=phone)
        s.add(entry)
        await s.commit()
        return "ok", entry


@dataclass
class Advance:
    finished: QueueEntry | None  # hozirgina yakunlangan (yoki kelmagan) mijoz
    called: QueueEntry | None  # endi chaqirilgan mijoz
    upcoming: QueueEntry | None  # undan keyingi mijoz


async def advance(skip: bool = False) -> Advance:
    """Xizmatdagi mijozni yakunlaydi (skip=True bo'lsa 'kelmadi') va keyingisini chaqiradi."""
    async with queue_lock, SessionLocal() as s:
        serving, waiting = await load_queue(s)
        finished = None
        if serving:
            serving.status = SKIPPED if skip else DONE
            serving.finished_at = now()
            finished = serving
        called = waiting[0] if waiting else None
        if called:
            called.status = SERVING
            called.called_at = now()
        await s.commit()
        return Advance(finished, called, waiting[1] if len(waiting) > 1 else None)


async def cancel_entry(entry_id: int) -> QueueEntry | None:
    """Kutayotgan mijozni navbatdan o'chiradi."""
    async with queue_lock, SessionLocal() as s:
        entry = await s.get(QueueEntry, entry_id)
        if not entry or entry.status != WAITING or entry.queue_date != today():
            return None
        entry.status = CANCELLED
        entry.finished_at = now()
        await s.commit()
        return entry


# ------------------------------------------------------------------ matnlar
def ticket_text(e: QueueEntry, serving: QueueEntry | None, waiting: list[QueueEntry]) -> str:
    head = f"🎫 <b>Sizning navbatingiz: №{e.number}</b>\n👤 {esc(e.name)}\n\n"
    if e.status == SERVING:
        return head + TXT_CALLED + f"\n\n🔄 {stamp()}"
    if e.status == DONE:
        return head + "✅ Xizmat yakunlandi. Rahmat, yana keling! 💈"
    if e.status == CANCELLED:
        return head + "❌ Navbat bekor qilindi."
    if e.status == SKIPPED:
        return head + "🚫 Siz kelmadingiz, navbat o'tkazib yuborildi.\nXohlasangiz, qayta yoziling."
    ahead = sum(1 for w in waiting if w.number < e.number) + (1 if serving else 0)
    if ahead == 0:
        body = "🥇 Siz birinchisiz - sartarosh tez orada chaqiradi."
    else:
        body = f"👥 Oldingizda: <b>{ahead}</b> kishi\n⏱ Taxminan kutish: ~{ahead * config.AVG_SERVICE_MINUTES} daqiqa"
    current = f"№{serving.number}" if serving else "hali boshlanmadi"
    return head + body + f"\n✂️ Hozir xizmatda: {current}\n\n🔄 {stamp()}"


def overview_text(serving: QueueEntry | None, waiting: list[QueueEntry], is_open: bool) -> str:
    current = f"№{serving.number}" if serving else "hech kim"
    order = ", ".join(f"№{w.number}" for w in waiting) or "-"
    state = "🟢 Navbat ochiq" if is_open else "🔴 Navbat yopiq"
    return (
        f"👀 <b>Jonli navbat</b>\n\n✂️ Hozir xizmatda: {current}\n"
        f"⏳ Kutayotganlar: <b>{len(waiting)}</b> kishi\n🔢 Tartib: {order}\n{state}\n\n🔄 {stamp()}"
    )


def admin_queue_text(serving, waiting, stats, is_open) -> str:
    lines = [
        f"📋 <b>Bugungi navbat</b> - {today().strftime('%d.%m.%Y')}",
        "🟢 Navbat ochiq" if is_open else "🔴 Navbat yopiq",
        "",
        f"✂️ Xizmatda: {who_full(serving)}" if serving else "✂️ Xizmatda: hech kim",
        "",
    ]
    if waiting:
        lines.append(f"⏳ Kutayotganlar ({len(waiting)}):")
        lines += [who_full(w) for w in waiting[:40]]
        if len(waiting) > 40:
            lines.append(f"... va yana {len(waiting) - 40} ta")
    else:
        lines.append("⏳ Kutayotganlar yo'q")
    lines.append(
        f"\n✅ Tugagan: {stats.get(DONE, 0)} · 🚫 Kelmadi: {stats.get(SKIPPED, 0)} · ❌ Bekor: {stats.get(CANCELLED, 0)}"
    )
    lines.append(f"🔄 {stamp()}")
    return "\n".join(lines)


# ------------------------------------------------------------------ jonli chipta va xabarlar
async def send_ticket(bot: Bot, entry_id: int) -> None:
    """Mijozga jonli yangilanib turadigan navbat xabarini yuboradi (eskisini o'chiradi)."""
    async with SessionLocal() as s:
        entry = await s.get(QueueEntry, entry_id)
        serving, waiting = await load_queue(s)
    if not entry or not entry.tg_id:
        return
    msg = await safe_send(bot, entry.tg_id, ticket_text(entry, serving, waiting), reply_markup=kb.refresh_kb())
    if msg:
        async with SessionLocal() as s:
            row = await s.get(QueueEntry, entry_id)
            old, row.ticket_message_id = row.ticket_message_id, msg.message_id
            await s.commit()
        if old:
            await safe_delete(bot, entry.tg_id, old)


async def refresh_tickets(bot: Bot) -> None:
    """Navbatdagi hamma mijozning chiptasini yangilaydi (xabar o'zi o'zgaradi)."""
    async with SessionLocal() as s:
        serving, waiting = await load_queue(s)
    for e in ([serving] if serving else []) + waiting:
        if e.tg_id and e.ticket_message_id:
            await safe_edit(bot, e.tg_id, e.ticket_message_id, ticket_text(e, serving, waiting), kb.refresh_kb())
            await asyncio.sleep(0.05)  # Telegram limitiga tushmaslik uchun


async def finalize_ticket(bot: Bot, e: QueueEntry) -> None:
    """Tugagan/bekor qilingan mijozning chiptasini oxirgi holatga keltiradi."""
    if e.tg_id and e.ticket_message_id:
        await safe_edit(bot, e.tg_id, e.ticket_message_id, ticket_text(e, None, []))


async def process_notifications(bot: Bot) -> None:
    """Chaqirilgan mijozga 'keldi', undan keyingisiga 'yaqinlashdi' xabarini BIR MARTA yuboradi."""
    to_send: list[tuple[int, str]] = []
    async with queue_lock, SessionLocal() as s:
        serving, waiting = await load_queue(s)
        if serving and not serving.notified_called:
            serving.notified_called = True
            if serving.tg_id:
                to_send.append((serving.tg_id, TXT_CALLED))
        if serving and waiting and not waiting[0].notified_near:
            waiting[0].notified_near = True
            if waiting[0].tg_id:
                to_send.append((waiting[0].tg_id, TXT_NEAR))
        await s.commit()
    for chat_id, text in to_send:
        await safe_send(bot, chat_id, text)


async def after_change(bot: Bot, closed: list[QueueEntry] | None = None) -> None:
    """Navbat o'zgargach: xabarlar yuboradi va hamma chiptalarni yangilaydi."""
    for e in closed or []:
        await finalize_ticket(bot, e)
    await process_notifications(bot)
    await refresh_tickets(bot)

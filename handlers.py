"""Telegram bot handlerlari: umumiy, admin va mijoz."""
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
import keyboards as kb
from db import SERVING, WAITING, SessionLocal
from services import (
    admin_queue_text, advance, after_change, cancel_entry, day_stats, esc, get_active_entry, is_queue_open,
    join_queue, load_queue, normalize_phone, overview_text, parse_name_phone, safe_send, send_ticket,
    set_queue_open, stamp, tell_admins, ticket_text, who, who_full,
)

common = Router(name="common")
admin = Router(name="admin")
client = Router(name="client")
admin.message.filter(F.from_user.id.in_(config.ADMIN_IDS))  # faqat adminlar
admin.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))


class Join(StatesGroup):
    name = State()
    phone = State()


class AddClient(StatesGroup):
    text = State()


# ------------------------------------------------------------------ yordamchilar
async def menu_for(user_id: int):
    if user_id in config.ADMIN_IDS:
        async with SessionLocal() as s:
            return kb.admin_menu(await is_queue_open(s))
    return kb.client_menu()


async def edit_cb(c: CallbackQuery, text: str, markup=None) -> None:
    try:
        await c.message.edit_text(text, reply_markup=markup)
    except TelegramAPIError:
        pass  # "message is not modified" va shunga o'xshashlar


_last_press = 0.0


def too_fast() -> bool:
    """Tugma tasodifan ikki marta bosilib ketsa, navbat 2 ta o'tib ketmasin."""
    global _last_press
    t = time.monotonic()
    if t - _last_press < 2:
        return True
    _last_press = t
    return False


# ------------------------------------------------------------------ UMUMIY
@common.message(F.text == kb.B_CANCEL)
async def cancel_any(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Bekor qilindi.", reply_markup=await menu_for(m.from_user.id))


# ------------------------------------------------------------------ ADMIN
@admin.message(CommandStart())
async def admin_start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        f"🛠 <b>Admin paneli</b> - {esc(config.SHOP_NAME)}\n\n"
        "✅ <b>Yakunlash</b> - hozirgi mijozni tugatadi, keyingisini chaqiradi va keyingi 2 mijozga o'zi xabar yuboradi.\n"
        "🚫 <b>Kelmadi</b> - mijoz kelmasa, o'tkazib yuboradi.\n"
        "📋 <b>Navbat</b> - ro'yxat; kerak bo'lsa mijozni o'chirish.\n"
        "➕ <b>Mijoz qo'shish</b> - botdan foydalanmaydigan mijoz uchun.\n"
        "🔒 <b>Navbatni yopish</b> - yangi mijoz yozila olmaydi.",
        reply_markup=await menu_for(m.from_user.id),
    )


@admin.message(F.text == kb.A_TO_CLIENT)
async def admin_to_client(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("👤 Mijoz menyusi (sinab ko'rish uchun).", reply_markup=kb.client_menu(admin=True))


@admin.message(F.text == kb.A_TO_ADMIN)
async def admin_to_admin(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🛠 Admin menyusi.", reply_markup=await menu_for(m.from_user.id))


async def run_advance(m: Message, bot: Bot, skip: bool) -> None:
    async with SessionLocal() as s:
        serving, waiting = await load_queue(s)
    if skip and not serving:
        return await m.answer("Hozir xizmatdagi mijoz yo'q.")
    if not serving and not waiting:
        return await m.answer("📭 Navbat bo'sh - hozircha hech kim yo'q.")
    if too_fast():
        return await m.answer("⏳ Juda tez bosildi, bir soniya kuting.")

    res = await advance(skip)
    lines = []
    if res.finished:
        lines.append(f"{'🚫 Kelmadi' if skip else '✅ Yakunlandi'}: {who(res.finished)}")
    if res.called:
        lines.append(f"🔔 Chaqirildi: {who_full(res.called)}")
        if not res.called.tg_id:
            lines.append("📣 Bu mijoz botda yo'q - o'zingiz chaqiring.")
        if res.upcoming:
            lines.append(f"⏳ Keyingisi: {who(res.upcoming)} (ogohlantirildi)")
    else:
        lines.append("📭 Kutayotgan mijoz qolmadi.")
    await m.answer("\n".join(lines))
    await after_change(bot, [res.finished] if res.finished else [])


@admin.message(F.text == kb.A_DONE)
async def adm_done(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await run_advance(m, bot, skip=False)


@admin.message(F.text == kb.A_NOSHOW)
async def adm_noshow(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await run_advance(m, bot, skip=True)


async def render_admin_list():
    async with SessionLocal() as s:
        serving, waiting = await load_queue(s)
        stats = await day_stats(s)
        is_open = await is_queue_open(s)
    return admin_queue_text(serving, waiting, stats, is_open), kb.admin_list_kb(waiting)


@admin.message(F.text == kb.A_LIST)
async def adm_list(m: Message, state: FSMContext):
    await state.clear()
    text, markup = await render_admin_list()
    await m.answer(text, reply_markup=markup)


@admin.callback_query(F.data == "adm:refresh")
async def adm_refresh(c: CallbackQuery):
    text, markup = await render_admin_list()
    await edit_cb(c, text, markup)
    await c.answer("Yangilandi")


@admin.callback_query(F.data.startswith("adm:cancel:"))
async def adm_cancel(c: CallbackQuery, bot: Bot):
    entry = await cancel_entry(int(c.data.split(":")[2]))
    if not entry:
        return await c.answer("Bu mijoz allaqachon navbatda emas.", show_alert=True)
    text, markup = await render_admin_list()
    await edit_cb(c, text, markup)
    await c.answer(f"№{entry.number} o'chirildi")
    if entry.tg_id:
        await safe_send(bot, entry.tg_id, "❌ Sartarosh navbatingizni bekor qildi. Qayta yozilish uchun menyudan foydalaning.")
    await after_change(bot, [entry])


@admin.message(F.text.in_({kb.A_CLOSE, kb.A_OPEN}))
async def adm_toggle(m: Message, state: FSMContext):
    await state.clear()
    open_ = m.text == kb.A_OPEN
    await set_queue_open(open_)
    await m.answer(
        "🔓 Navbat ochildi - mijozlar yozila oladi."
        if open_
        else "🔒 Navbat yopildi - yangi mijoz yozila olmaydi (hozirgilar saqlanadi).",
        reply_markup=kb.admin_menu(open_),
    )


@admin.message(F.text == kb.A_ADD)
async def adm_add(m: Message, state: FSMContext):
    await state.set_state(AddClient.text)
    await m.answer(
        "Mijoz ismini yozing. Telefon ham bo'lsa, birga yozing:\n<code>Ali 901234567</code>",
        reply_markup=kb.cancel_kb(),
    )


@admin.message(AddClient.text, F.text)
async def adm_add_text(m: Message, state: FSMContext):
    name, phone = parse_name_phone(m.text)
    await state.clear()
    _, entry = await join_queue(name, phone, None)
    await m.answer(f"✅ {who(entry)} navbatga qo'shildi.", reply_markup=await menu_for(m.from_user.id))


# ------------------------------------------------------------------ MIJOZ
@client.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        f"Assalomu alaykum, <b>{esc(m.from_user.first_name)}</b>! 💈\n"
        f"<b>{esc(config.SHOP_NAME)}</b> navbat botiga xush kelibsiz.\n\n"
        "Navbatga yozilish uchun pastdagi tugmani bosing. Navbatingiz yaqinlashganda bot o'zi xabar beradi.",
        reply_markup=kb.client_menu(),
    )


@client.message(F.text == kb.B_JOIN)
async def join_start(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    async with SessionLocal() as s:
        is_open = await is_queue_open(s)
        existing = await get_active_entry(s, m.from_user.id)
    if existing:
        await m.answer("Siz allaqachon navbatdasiz 👇")
        return await send_ticket(bot, existing.id)
    if not is_open:
        return await m.answer("🔒 Hozir navbat yopiq. Keyinroq urinib ko'ring.")
    await state.set_state(Join.name)
    await m.answer(
        "Ismingizni yozing (yoki pastdagi tugmani bosing):", reply_markup=kb.name_kb(m.from_user.first_name)
    )


@client.message(F.text == kb.B_LIVE)
async def live(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    async with SessionLocal() as s:
        entry = await get_active_entry(s, m.from_user.id)
        serving, waiting = await load_queue(s)
        is_open = await is_queue_open(s)
    if entry:
        await send_ticket(bot, entry.id)
    else:
        await m.answer(overview_text(serving, waiting, is_open), reply_markup=kb.overview_kb())


@client.message(F.text == kb.B_LEAVE)
async def leave(m: Message, state: FSMContext):
    await state.clear()
    async with SessionLocal() as s:
        entry = await get_active_entry(s, m.from_user.id)
    if not entry:
        await m.answer("Siz hozir navbatda emassiz.")
    elif entry.status == SERVING:
        await m.answer("Navbatingiz allaqachon keldi. Sartarosh bilan gaplashing.")
    else:
        await m.answer(f"№{entry.number} navbatdan chiqmoqchimisiz?", reply_markup=kb.leave_kb())


async def finish_join(m: Message, state: FSMContext, bot: Bot, phone: str | None) -> None:
    data = await state.get_data()
    await state.clear()
    name = data.get("name") or m.from_user.first_name
    status, entry = await join_queue(name, phone, m.from_user.id)
    menu = await menu_for(m.from_user.id)
    if status == "closed":
        return await m.answer("🔒 Kechirasiz, navbat hozirgina yopildi.", reply_markup=menu)
    await m.answer("✅ Navbatga yozildingiz!" if status == "ok" else "Siz allaqachon navbatdasiz 👇", reply_markup=menu)
    await send_ticket(bot, entry.id)
    if status == "ok":
        async with SessionLocal() as s:
            _, waiting = await load_queue(s)
        await tell_admins(bot, f"🆕 Yangi mijoz: {who_full(entry)}\n⏳ Kutayotganlar: {len(waiting)}", skip_id=m.from_user.id)


@client.message(Join.name, F.text)
async def join_name(m: Message, state: FSMContext):
    name = m.text.strip()
    if not 2 <= len(name) <= 40:
        return await m.answer("Iltimos, ismingizni 2-40 belgi oralig'ida yozing.")
    await state.update_data(name=name)
    await state.set_state(Join.phone)
    await m.answer("Telefon raqamingizni yuboring (tugma orqali yoki yozib):", reply_markup=kb.phone_kb())


@client.message(Join.phone, F.contact)
async def join_phone_contact(m: Message, state: FSMContext, bot: Bot):
    if m.contact.user_id and m.contact.user_id != m.from_user.id:
        return await m.answer("Iltimos, o'zingizning raqamingizni yuboring.")
    await finish_join(m, state, bot, normalize_phone(m.contact.phone_number))


@client.message(Join.phone, F.text == kb.B_NOPHONE)
async def join_no_phone(m: Message, state: FSMContext, bot: Bot):
    await finish_join(m, state, bot, None)


@client.message(Join.phone, F.text)
async def join_phone_text(m: Message, state: FSMContext, bot: Bot):
    phone = normalize_phone(m.text)
    if not phone:
        return await m.answer("Raqam noto'g'ri. Masalan: 90 123 45 67\nYoki «⏭ Raqamsiz davom etish» ni bosing.")
    await finish_join(m, state, bot, phone)


@client.callback_query(F.data == "refresh")
async def cb_refresh(c: CallbackQuery):
    async with SessionLocal() as s:
        entry = await get_active_entry(s, c.from_user.id)
        serving, waiting = await load_queue(s)
    if not entry:
        return await c.answer("Siz hozir navbatda emassiz.", show_alert=True)
    await edit_cb(c, ticket_text(entry, serving, waiting), kb.refresh_kb())
    await c.answer("Yangilandi ✅")


@client.callback_query(F.data == "overview")
async def cb_overview(c: CallbackQuery):
    async with SessionLocal() as s:
        serving, waiting = await load_queue(s)
        is_open = await is_queue_open(s)
    await edit_cb(c, overview_text(serving, waiting, is_open), kb.overview_kb())
    await c.answer("Yangilandi ✅")


@client.callback_query(F.data == "leave:no")
async def cb_leave_no(c: CallbackQuery):
    await edit_cb(c, "Yaxshi, navbatingiz saqlanib qoldi ✅")
    await c.answer()


@client.callback_query(F.data == "leave:yes")
async def cb_leave_yes(c: CallbackQuery, bot: Bot):
    async with SessionLocal() as s:
        entry = await get_active_entry(s, c.from_user.id)
    cancelled = await cancel_entry(entry.id) if entry and entry.status == WAITING else None
    if not cancelled:
        await edit_cb(c, "Navbat topilmadi yoki allaqachon keldi.")
        return await c.answer()
    await edit_cb(c, "❌ Siz navbatdan chiqdingiz. Qayta yozilish uchun «📝 Navbatga yozilish» ni bosing.")
    await c.answer()
    await tell_admins(bot, f"❌ Navbatdan chiqdi: {who_full(cancelled)}", skip_id=c.from_user.id)
    await after_change(bot, [cancelled])


@client.message()
async def fallback(m: Message):
    await m.answer("Menyudan tanlang 👇", reply_markup=await menu_for(m.from_user.id))

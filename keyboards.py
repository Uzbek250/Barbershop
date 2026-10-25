"""Tugmalar va ularning matnlari."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

# --- mijoz tugmalari
B_JOIN = "📝 Navbatga yozilish"
B_LIVE = "👀 Jonli navbat"
B_LEAVE = "❌ Navbatdan chiqish"
B_CANCEL = "↩️ Bekor qilish"
B_SHARE = "📱 Raqamni yuborish"
B_NOPHONE = "⏭ Raqamsiz davom etish"

# --- admin tugmalari
A_DONE = "✅ Yakunlash"
A_NOSHOW = "🚫 Kelmadi"
A_LIST = "📋 Navbat"
A_ADD = "➕ Mijoz qo'shish"
A_CLOSE = "🔒 Navbatni yopish"
A_OPEN = "🔓 Navbatni ochish"
A_TO_CLIENT = "👤 Mijoz menyusi"
A_TO_ADMIN = "🛠 Admin menyusi"


def _reply(rows, placeholder=None):
    keyboard = [[b if isinstance(b, KeyboardButton) else KeyboardButton(text=b) for b in row] for row in rows]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, input_field_placeholder=placeholder)


def _inline(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows]
    )


def client_menu(admin: bool = False):
    rows = [[B_JOIN], [B_LIVE, B_LEAVE]]
    if admin:
        rows.append([A_TO_ADMIN])
    return _reply(rows)


def admin_menu(is_open: bool):
    return _reply([[A_DONE], [A_NOSHOW, A_LIST], [A_ADD, A_CLOSE if is_open else A_OPEN], [A_TO_CLIENT]])


def name_kb(first_name: str):
    return _reply([[first_name[:40]], [B_CANCEL]], "Ismingiz")


def phone_kb():
    return _reply([[KeyboardButton(text=B_SHARE, request_contact=True)], [B_NOPHONE], [B_CANCEL]])


def cancel_kb():
    return _reply([[B_CANCEL]])


def refresh_kb():
    return _inline([[("🔄 Yangilash", "refresh")]])


def overview_kb():
    return _inline([[("🔄 Yangilash", "overview")]])


def leave_kb():
    return _inline([[("✅ Ha, chiqaman", "leave:yes"), ("↩️ Yo'q", "leave:no")]])


def admin_list_kb(waiting):
    rows, row = [], []
    for w in waiting[:20]:
        row.append((f"❌ №{w.number} {w.name[:12]}", f"adm:cancel:{w.id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("🔄 Yangilash", "adm:refresh")])
    return _inline(rows)

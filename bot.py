import asyncio
import html
import logging
import os
import sqlite3
from contextlib import closing

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
CARD_NUMBER = os.getenv("CARD_NUMBER", "0000 0000 0000 0000")
CARD_OWNER = os.getenv("CARD_OWNER", "Ism Familiya")
DB = "shop.db"


# ---------------------------------------------------------------- DB
def fetch(sql, args=()):
    with closing(sqlite3.connect(DB)) as c:
        c.row_factory = sqlite3.Row
        return c.execute(sql, args).fetchall()


def execute(sql, args=()):
    with closing(sqlite3.connect(DB)) as c:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def init_db():
    execute(
        """CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, description TEXT, price INTEGER,
            file_id TEXT, active INTEGER DEFAULT 1)"""
    )
    execute(
        """CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, product_id INTEGER,
            status TEXT DEFAULT 'pending',
            receipt_id TEXT, receipt_type TEXT,
            created TEXT DEFAULT CURRENT_TIMESTAMP)"""
    )


def money(n):
    return f"{int(n):,}".replace(",", " ") + " so'm"


def esc(s):
    return html.escape(str(s or ""))


# ---------------------------------------------------------------- Keyboards
CANCEL = "❌ Bekor qilish"
admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Dastur qo'shish"), KeyboardButton(text="📦 Dasturlarni boshqarish")],
        [KeyboardButton(text="🧾 Kutilayotgan to'lovlar"), KeyboardButton(text="🛍 Do'kon (mijoz ko'rinishi)")],
    ],
    resize_keyboard=True,
)
client_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🛍 Dasturlar"), KeyboardButton(text="📥 Xaridlarim")]],
    resize_keyboard=True,
)
cancel_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=CANCEL)]], resize_keyboard=True)


def menu_for(uid):
    return admin_kb if uid in ADMIN_IDS else client_kb


# ---------------------------------------------------------------- States
class AddProduct(StatesGroup):
    name = State()
    description = State()
    price = State()
    file = State()


class EditPrice(StatesGroup):
    price = State()


class Buy(StatesGroup):
    receipt = State()


common = Router()
admin = Router()
client = Router()
admin.message.filter(F.from_user.id.in_(ADMIN_IDS))
admin.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


# ---------------------------------------------------------------- Common
@common.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    if m.from_user.id in ADMIN_IDS:
        text = "👋 Salom, admin! Admin paneliga xush kelibsiz."
    else:
        text = "👋 Xush kelibsiz! Bu yerda dasturlarni sotib olishingiz mumkin."
    await m.answer(text, reply_markup=menu_for(m.from_user.id))


@common.message(Command("cancel"))
@common.message(F.text == CANCEL)
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Bekor qilindi.", reply_markup=menu_for(m.from_user.id))


# ---------------------------------------------------------------- Admin: add product
@admin.message(F.text == "➕ Dastur qo'shish")
async def add_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddProduct.name)
    await m.answer("Dastur nomini yuboring:", reply_markup=cancel_kb)


@admin.message(AddProduct.name, F.text)
async def add_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await state.set_state(AddProduct.description)
    await m.answer("Dastur haqida qisqa tavsif yuboring:")


@admin.message(AddProduct.description, F.text)
async def add_desc(m: Message, state: FSMContext):
    await state.update_data(description=m.text.strip())
    await state.set_state(AddProduct.price)
    await m.answer("Narxini so'mda yuboring (faqat raqam, masalan: 50000):")


@admin.message(AddProduct.price, F.text)
async def add_price(m: Message, state: FSMContext):
    raw = m.text.replace(" ", "")
    if not raw.isdigit() or int(raw) <= 0:
        return await m.answer("❗ Faqat musbat raqam yuboring, masalan: 50000")
    await state.update_data(price=int(raw))
    await state.set_state(AddProduct.file)
    await m.answer("Endi dastur faylini yuboring (Document/fayl sifatida, zip/exe/apk va h.k.):")


@admin.message(AddProduct.file, F.document)
async def add_file(m: Message, state: FSMContext):
    d = await state.get_data()
    pid = execute(
        "INSERT INTO products(name, description, price, file_id) VALUES(?,?,?,?)",
        (d["name"], d["description"], d["price"], m.document.file_id),
    )
    await state.clear()
    await m.answer(
        f"✅ Qo'shildi (#{pid})\n<b>{esc(d['name'])}</b> — {money(d['price'])}",
        reply_markup=admin_kb,
    )


@admin.message(AddProduct.file)
async def add_file_wrong(m: Message):
    await m.answer("❗ Iltimos, faylni <b>fayl (document)</b> ko'rinishida yuboring.")


# ---------------------------------------------------------------- Admin: manage products
@admin.message(F.text == "📦 Dasturlarni boshqarish")
async def manage(m: Message, state: FSMContext):
    await state.clear()
    rows = fetch("SELECT * FROM products WHERE active=1 ORDER BY id DESC")
    if not rows:
        return await m.answer("Hozircha dastur yo'q.")
    for p in rows:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="💰 Narxni o'zgartirish", callback_data=f"ep:{p['id']}"),
                    InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del:{p['id']}"),
                ]
            ]
        )
        await m.answer(
            f"#{p['id']} <b>{esc(p['name'])}</b>\n{esc(p['description'])}\n💵 {money(p['price'])}",
            reply_markup=kb,
        )


@admin.callback_query(F.data.startswith("ep:"))
async def edit_price_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(EditPrice.price)
    await state.update_data(pid=int(c.data.split(":")[1]))
    await c.message.answer("Yangi narxni yuboring (faqat raqam):", reply_markup=cancel_kb)
    await c.answer()


@admin.message(EditPrice.price, F.text)
async def edit_price_done(m: Message, state: FSMContext):
    raw = m.text.replace(" ", "")
    if not raw.isdigit() or int(raw) <= 0:
        return await m.answer("❗ Faqat musbat raqam yuboring.")
    pid = (await state.get_data())["pid"]
    execute("UPDATE products SET price=? WHERE id=?", (int(raw), pid))
    await state.clear()
    await m.answer(f"✅ Narx yangilandi: {money(int(raw))}", reply_markup=admin_kb)


@admin.callback_query(F.data.startswith("del:"))
async def delete_product(c: CallbackQuery):
    execute("UPDATE products SET active=0 WHERE id=?", (int(c.data.split(":")[1]),))
    await c.message.edit_text("🗑 Dastur o'chirildi.")
    await c.answer()


# ---------------------------------------------------------------- Admin: payments
def order_caption(o, extra=""):
    p = fetch("SELECT * FROM products WHERE id=?", (o["product_id"],))[0]
    return (
        f"🧾 <b>To'lov #{o['id']}</b>\n"
        f"👤 Mijoz ID: <code>{o['user_id']}</code>\n"
        f"📦 {esc(p['name'])} — {money(p['price'])}{extra}"
    )


def order_kb(oid):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"ok:{oid}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"no:{oid}"),
            ]
        ]
    )


async def send_receipt(bot: Bot, chat_id, o):
    cap, kb = order_caption(o), order_kb(o["id"])
    if o["receipt_type"] == "photo":
        await bot.send_photo(chat_id, o["receipt_id"], caption=cap, reply_markup=kb)
    else:
        await bot.send_document(chat_id, o["receipt_id"], caption=cap, reply_markup=kb)


@admin.message(F.text == "🧾 Kutilayotgan to'lovlar")
async def pending(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    rows = fetch("SELECT * FROM orders WHERE status='pending' ORDER BY id")
    if not rows:
        return await m.answer("Kutilayotgan to'lov yo'q ✅")
    for o in rows:
        await send_receipt(bot, m.chat.id, o)


@admin.callback_query(F.data.startswith(("ok:", "no:")))
async def decide(c: CallbackQuery, bot: Bot):
    action, oid = c.data.split(":")
    rows = fetch("SELECT * FROM orders WHERE id=?", (int(oid),))
    if not rows:
        return await c.answer("Buyurtma topilmadi", show_alert=True)
    o = rows[0]
    if o["status"] != "pending":
        return await c.answer("Bu to'lov allaqachon ko'rib chiqilgan.", show_alert=True)
    p = fetch("SELECT * FROM products WHERE id=?", (o["product_id"],))[0]

    if action == "ok":
        execute("UPDATE orders SET status='approved' WHERE id=?", (o["id"],))
        await bot.send_message(o["user_id"], f"✅ To'lovingiz tasdiqlandi! <b>{esc(p['name'])}</b> yuborilmoqda...")
        await bot.send_document(o["user_id"], p["file_id"], caption=f"📦 {esc(p['name'])}\nRahmat! 🙌")
        result = "\n\n✅ <b>Tasdiqlandi</b>"
    else:
        execute("UPDATE orders SET status='rejected' WHERE id=?", (o["id"],))
        await bot.send_message(
            o["user_id"],
            f"❌ <b>{esc(p['name'])}</b> uchun to'lovingiz rad etildi.\n"
            "Agar xatolik bo'lsa, qayta urinib ko'ring yoki admin bilan bog'laning.",
        )
        result = "\n\n❌ <b>Rad etildi</b>"

    try:
        await c.message.edit_caption(caption=order_caption(o, result), reply_markup=None)
    except Exception:
        pass
    await c.answer("Bajarildi")


# ---------------------------------------------------------------- Client
async def show_catalog(m: Message, state: FSMContext):
    await state.clear()
    rows = fetch("SELECT * FROM products WHERE active=1 ORDER BY id DESC")
    if not rows:
        return await m.answer("Hozircha dasturlar mavjud emas.")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{p['name']} — {money(p['price'])}", callback_data=f"p:{p['id']}")]
            for p in rows
        ]
    )
    await m.answer("🛍 <b>Mavjud dasturlar:</b>", reply_markup=kb)


client.message.register(show_catalog, F.text.in_({"🛍 Dasturlar", "🛍 Do'kon (mijoz ko'rinishi)"}))


@client.message(F.text == "📥 Xaridlarim")
async def my_purchases(m: Message, state: FSMContext):
    await state.clear()
    rows = fetch(
        """SELECT p.id, p.name FROM orders o JOIN products p ON p.id=o.product_id
           WHERE o.user_id=? AND o.status='approved' GROUP BY p.id ORDER BY o.id DESC""",
        (m.from_user.id,),
    )
    if not rows:
        return await m.answer("Sizda hali xaridlar yo'q.")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"📥 {r['name']}", callback_data=f"get:{r['id']}")] for r in rows]
    )
    await m.answer("Sotib olgan dasturlaringiz (qayta yuklab olish uchun bosing):", reply_markup=kb)


@client.callback_query(F.data.startswith("get:"))
async def get_again(c: CallbackQuery, bot: Bot):
    pid = int(c.data.split(":")[1])
    paid = fetch(
        "SELECT 1 FROM orders WHERE user_id=? AND product_id=? AND status='approved'",
        (c.from_user.id, pid),
    )
    if not paid:
        return await c.answer("Bu dastur sotib olinmagan.", show_alert=True)
    p = fetch("SELECT * FROM products WHERE id=?", (pid,))[0]
    await bot.send_document(c.from_user.id, p["file_id"], caption=f"📦 {esc(p['name'])}")
    await c.answer()


@client.callback_query(F.data.startswith("p:"))
async def product_card(c: CallbackQuery):
    rows = fetch("SELECT * FROM products WHERE id=? AND active=1", (int(c.data.split(":")[1]),))
    if not rows:
        return await c.answer("Dastur topilmadi.", show_alert=True)
    p = rows[0]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💳 Sotib olish", callback_data=f"buy:{p['id']}")]]
    )
    await c.message.answer(
        f"📦 <b>{esc(p['name'])}</b>\n\n{esc(p['description'])}\n\n💵 Narxi: <b>{money(p['price'])}</b>",
        reply_markup=kb,
    )
    await c.answer()


@client.callback_query(F.data.startswith("buy:"))
async def buy(c: CallbackQuery, state: FSMContext):
    pid = int(c.data.split(":")[1])
    rows = fetch("SELECT * FROM products WHERE id=? AND active=1", (pid,))
    if not rows:
        return await c.answer("Dastur topilmadi.", show_alert=True)
    p = rows[0]

    if fetch(
        "SELECT 1 FROM orders WHERE user_id=? AND product_id=? AND status='approved'",
        (c.from_user.id, pid),
    ):
        return await c.answer("Siz buni allaqachon sotib olgansiz. «📥 Xaridlarim» bo'limiga qarang.", show_alert=True)
    if fetch(
        "SELECT 1 FROM orders WHERE user_id=? AND product_id=? AND status='pending'",
        (c.from_user.id, pid),
    ):
        return await c.answer("To'lovingiz admin tomonidan tekshirilmoqda, iltimos kuting.", show_alert=True)

    await state.set_state(Buy.receipt)
    await state.update_data(pid=pid)
    await c.message.answer(
        f"💳 <b>To'lov</b>\n\n"
        f"📦 {esc(p['name'])}\n💵 Summa: <b>{money(p['price'])}</b>\n\n"
        f"Karta: <code>{esc(CARD_NUMBER)}</code>\n👤 {esc(CARD_OWNER)}\n\n"
        "To'lovni amalga oshirgach, <b>chek rasmini (skrinshot)</b> shu yerga yuboring.",
        reply_markup=cancel_kb,
    )
    await c.answer()


@client.message(Buy.receipt, F.photo | F.document)
async def receive_receipt(m: Message, state: FSMContext, bot: Bot):
    pid = (await state.get_data())["pid"]
    if m.photo:
        rid, rtype = m.photo[-1].file_id, "photo"
    else:
        rid, rtype = m.document.file_id, "document"
    oid = execute(
        "INSERT INTO orders(user_id, product_id, receipt_id, receipt_type) VALUES(?,?,?,?)",
        (m.from_user.id, pid, rid, rtype),
    )
    await state.clear()
    await m.answer(
        "✅ Chek qabul qilindi. Admin tekshirgach, dastur sizga yuboriladi.",
        reply_markup=menu_for(m.from_user.id),
    )
    o = fetch("SELECT * FROM orders WHERE id=?", (oid,))[0]
    for aid in ADMIN_IDS:
        try:
            await send_receipt(bot, aid, o)
        except Exception as e:
            logging.warning("Adminga yuborib bo'lmadi %s: %s", aid, e)


@client.message(Buy.receipt)
async def receipt_wrong(m: Message):
    await m.answer("❗ Iltimos, chek <b>rasmini</b> yuboring yoki «❌ Bekor qilish» ni bosing.")


# ---------------------------------------------------------------- Run
async def main():
    logging.basicConfig(level=logging.INFO)
    if not BOT_TOKEN or not ADMIN_IDS:
        raise SystemExit(".env faylida BOT_TOKEN va ADMIN_IDS ni to'ldiring")
    init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    # tartib muhim: common -> admin -> client
    dp.include_router(common)
    dp.include_router(admin)
    dp.include_router(client)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

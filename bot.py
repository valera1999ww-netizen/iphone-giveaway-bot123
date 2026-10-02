import asyncio, os, secrets, sqlite3
from pathlib import Path
from aiohttp import web
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "your_bot")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_PATH = Path(os.getenv("DB_PATH", "giveaway.db"))
WEBHOOK_PATH = f"/telegram/{secrets.token_urlsafe(16)}"

dp = Dispatcher()

def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        username TEXT,
        first_name TEXT,
        referrer_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS tickets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT UNIQUE NOT NULL,
        user_id INTEGER NOT NULL,
        source TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    c.commit()
    c.close()

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟 Мої квитки", callback_data="tickets"),
         InlineKeyboardButton(text="👥 Запросити друзів", callback_data="ref")],
        [InlineKeyboardButton(text="💳 Купити квиток", callback_data="buy"),
         InlineKeyboardButton(text="📜 Правила", callback_data="rules")],
        [InlineKeyboardButton(text="🏆 Переможець", callback_data="winner"),
         InlineKeyboardButton(text="🆘 Підтримка", callback_data="support")]
    ])

def back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Головне меню", callback_data="home")]
    ])

def add_ticket(c, uid, source):
    while True:
        n = f"{secrets.randbelow(900000) + 100000}"
        try:
            c.execute(
                "INSERT INTO tickets(number,user_id,source) VALUES(?,?,?)",
                (n, uid, source)
            )
            return n
        except sqlite3.IntegrityError:
            pass

def ensure_user(u, ref=None):
    c = db()
    old = c.execute(
        "SELECT * FROM users WHERE telegram_id=?", (u.id,)
    ).fetchone()

    if old:
        c.close()
        return old

    rid = None
    if ref and ref != u.id:
        r = c.execute(
            "SELECT id FROM users WHERE telegram_id=?", (ref,)
        ).fetchone()
        if r:
            rid = r["id"]

    c.execute(
        "INSERT INTO users(telegram_id,username,first_name,referrer_id) VALUES(?,?,?,?)",
        (u.id, u.username, u.first_name, rid)
    )

    if rid:
        count = c.execute(
            "SELECT COUNT(*) n FROM users WHERE referrer_id=?", (rid,)
        ).fetchone()["n"]
        have = c.execute(
            "SELECT COUNT(*) n FROM tickets WHERE user_id=? AND source='referral'",
            (rid,)
        ).fetchone()["n"]

        while have < count // 10:
            add_ticket(c, rid, "referral")
            have += 1

    c.commit()
    row = c.execute(
        "SELECT * FROM users WHERE telegram_id=?", (u.id,)
    ).fetchone()
    c.close()
    return row

@dp.message(CommandStart())
async def start(m: Message):
    parts = m.text.split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    ref = int(arg[4:]) if arg.startswith("ref_") and arg[4:].isdigit() else None

    ensure_user(m.from_user, ref)

    await m.answer(
        "📱 <b>РОЗІГРАШ iPHONE 15 PRO</b>\n\n"
        "🎁 Головний приз — iPhone 15 Pro\n\n"
        "🎟 Всього: <b>50 квитків</b>\n"
        "💰 1 квиток: <b>500 грн</b>\n\n"
        "👥 10 нових учасників за твоїм посиланням → "
        "1 безкоштовний квиток.\n\n"
        "Обери дію 👇",
        reply_markup=menu(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "home")
async def home(q: CallbackQuery):
    await q.message.edit_text(
        "📱 <b>РОЗІГРАШ iPHONE 15 PRO</b>\n\n"
        "🎟 50 квитків\n"
        "💰 500 грн\n"
        "👥 10 рефералів = 1 безкоштовний квиток\n\n"
        "Обери дію 👇",
        reply_markup=menu(),
        parse_mode="HTML"
    )
    await q.answer()

@dp.callback_query(F.data == "ref")
async def ref(q: CallbackQuery):
    ensure_user(q.from_user)
    c = db()
    u = c.execute(
        "SELECT id FROM users WHERE telegram_id=?", (q.from_user.id,)
    ).fetchone()
    refs = c.execute(
        "SELECT COUNT(*) n FROM users WHERE referrer_id=?", (u["id"],)
    ).fetchone()["n"]
    free = c.execute(
        "SELECT COUNT(*) n FROM tickets WHERE user_id=? AND source='referral'",
        (u["id"],)
    ).fetchone()["n"]
    c.close()

    left = 10 - (refs % 10)
    if left == 10:
        left = 0

    link = f"https://t.me/{BOT_USERNAME}?start=ref_{q.from_user.id}"

    await q.message.edit_text(
        f"👥 <b>ЗАПРОШУЙ ДРУЗІВ</b>\n\n"
        f"👤 Запрошено: <b>{refs}</b>\n"
        f"🎟 Безкоштовних квитків: <b>{free}</b>\n"
        f"🔥 До наступного: <b>{left}</b>\n\n"
        f"🔗 <code>{link}</code>\n\n"
        "Надішли це посилання друзям. За кожні 10 "
        "нових учасників бот видає 1 квиток.",
        reply_markup=back(),
        parse_mode="HTML"
    )
    await q.answer()

@dp.callback_query(F.data == "tickets")
async def tickets(q: CallbackQuery):
    ensure_user(q.from_user)
    c = db()
    u = c.execute(
        "SELECT id FROM users WHERE telegram_id=?", (q.from_user.id,)
    ).fetchone()
    rows = c.execute(
        "SELECT number,source FROM tickets WHERE user_id=? ORDER BY id",
        (u["id"],)
    ).fetchall()
    c.close()

    text = "🎟 <b>ТВОЇ КВИТКИ</b>\n\n"
    if rows:
        text += "\n".join(
            f"• #{r['number']} — "
            f"{'реферал' if r['source'] == 'referral' else 'купівля'}"
            for r in rows
        )
    else:
        text += "Поки немає квитків."

    await q.message.edit_text(
        text, reply_markup=back(), parse_mode="HTML"
    )
    await q.answer()

@dp.callback_query(F.data == "buy")
async def buy(q: CallbackQuery):
    await q.message.edit_text(
        "🎟️ <b>КУПІВЛЯ КВИТКА</b>\n\n"
"🎫 1 квиток — 500 грн.\n\n"
"💳 Оплата через PUMB:\n"
"https://mobile-app.pumb.ua/1TePE\n\n"
"Після оплати надішліть підтвердження адміністратору."
        reply_markup=back(),
        parse_mode="HTML"
    )
    await q.answer()

@dp.callback_query(F.data == "rules")
async def rules(q: CallbackQuery):
    await q.message.edit_text(
        "📜 <b>ПРАВИЛА</b>\n\n"
        "🎟 50 квитків.\n"
        "💰 500 грн за квиток.\n"
        "👥 10 нових учасників = 1 безкоштовний квиток.\n"
        "🚫 Самореферали не зараховуються.\n\n"
        "Перед запуском платної випадкової акції перевір "
        "її законність та правила платіжного провайдера.",
        reply_markup=back(),
        parse_mode="HTML"
    )
    await q.answer()

@dp.callback_query(F.data == "winner")
async def winner(q: CallbackQuery):
    await q.message.edit_text(
        "🏆 <b>ПЕРЕМОЖЕЦЬ</b>\n\nРозіграш ще не завершено.",
        reply_markup=back(),
        parse_mode="HTML"
    )
    await q.answer()

@dp.callback_query(F.data == "support")
async def support(q: CallbackQuery):
    await q.message.edit_text(
        "🆘 <b>ПІДТРИМКА</b>\n\n"
        "Вкажи тут свій Telegram username.",
        reply_markup=back(),
        parse_mode="HTML"
    )
    await q.answer()

@dp.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        return
    c = db()
    u = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    t = c.execute("SELECT COUNT(*) n FROM tickets").fetchone()["n"]
    c.close()
    await m.answer(
        f"📊 <b>СТАТИСТИКА</b>\n\n👥 Учасників: {u}\n🎟 Квитків: {t}",
        parse_mode="HTML"
    )

async def health(request):
    return web.Response(text="OK")

async def telegram_webhook(request):
    bot = request.app["bot"]
    data = await request.json()
    from aiogram.types import Update
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return web.Response(text="OK")

async def on_startup(app):
    init_db()
    bot = app["bot"]
    external_url = os.getenv("RENDER_EXTERNAL_URL")
    if external_url:
        await bot.set_webhook(
            external_url.rstrip("/") + WEBHOOK_PATH,
            drop_pending_updates=True
        )

async def on_cleanup(app):
    await app["bot"].delete_webhook()
    await app["bot"].session.close()

def create_app():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")

    bot = Bot(BOT_TOKEN)
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", health)
    app.router.add_post(WEBHOOK_PATH, telegram_webhook)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app

if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", "10000"))
    web.run_app(app, host="0.0.0.0", port=port)

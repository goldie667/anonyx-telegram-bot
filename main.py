import asyncio
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
from bot.memory_store import MemoryStore
from sqlalchemy import func, select

from bot.config import config
from bot.db import Session, User, Report, Block, ensure_user, init_db, engine
from bot.keyboards import main_menu, gender_kb, chat_kb, settings_kb, admin_kb
from bot.matching import find_partner, disconnect, leave_queue
from bot.states import ProfileForm, SettingsForm

logging.basicConfig(level=logging.INFO)
# In-memory flood control. Run one bot process on this HOKAS Free instance.
_message_windows = defaultdict(deque)

def rate_limited(user_id: int, limit: int = 8, window_seconds: int = 10) -> bool:
    now = time.monotonic()
    q = _message_windows[user_id]
    while q and now - q[0] > window_seconds:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False
bot = Bot(config.bot_token)
redis = MemoryStore()
dp = Dispatcher(storage=MemoryStorage())

def is_admin(user_id: int) -> bool:
    return user_id in config.admin_ids

async def profile_complete(user_id: int) -> bool:
    async with Session() as s:
        u = await s.get(User, user_id)
        return bool(u and u.gender and u.age and u.country)

async def chat_status(user_id: int):
    p = await redis.hget("chat:active", str(user_id))
    return int(p) if p else None

async def start_profile(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("ANONYX предназначен только для совершеннолетних. Укажи свой возраст, чтобы продолжить.")
    await state.set_state(ProfileForm.age)
    await message.answer("Укажи свой возраст (18–99):")

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    async with Session() as s:
        user = await ensure_user(s, message.from_user)
        if user.is_banned:
            await message.answer("Доступ к боту ограничен администрацией.")
            return
        complete = bool(user.gender and user.age and user.country)
    if not complete:
        await start_profile(message, state)
    else:
        await message.answer("Привет! Добро пожаловать в ANONYX — знакомься и общайся анонимно.", reply_markup=main_menu())

@dp.message(ProfileForm.age)
async def profile_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
    except (ValueError, AttributeError):
        await message.answer("Введи возраст числом от 18 до 99.")
        return
    if age < 18 or age > 99:
        await message.answer("Этот бот предназначен для совершеннолетних. Возраст должен быть от 18 до 99.")
        return
    async with Session() as s:
        u = await s.get(User, message.from_user.id)
        u.age = age
        await s.commit()
    await state.clear()
    await message.answer("Выбери пол:", reply_markup=gender_kb())

@dp.callback_query(F.data.startswith("gender:"))
async def set_gender(c: CallbackQuery):
    value = c.data.split(":")[1]
    async with Session() as s:
        u = await s.get(User, c.from_user.id)
        if not u:
            await c.answer("Сначала /start", show_alert=True); return
        u.gender = value
        await s.commit()
    await c.message.answer("Укажи страну проживания (например, Украина, Польша, Словакия):")
    await c.answer()
    # Reuse FSM by assigning state through dispatcher context is not available here;
    # store the pending profile field in Redis for the next message.
    await redis.set(f"profile:country:{c.from_user.id}", "1", ex=600)

async def text_router(message: Message, state: FSMContext):
    uid = message.from_user.id
    if rate_limited(uid):
        await message.answer("Немного медленнее 🙂 Подожди несколько секунд.")
        return
    # Profile country prompt
    if await redis.get(f"profile:country:{uid}"):
        country = (message.text or "").strip()[:64]
        if len(country) < 2:
            await message.answer("Введи название страны текстом."); return
        async with Session() as s:
            u = await s.get(User, uid); u.country = country; await s.commit()
        await redis.delete(f"profile:country:{uid}")
        await message.answer("Напиши интересы через запятую (например: музыка, игры, путешествия). Можно написать «пропустить».")
        await redis.set(f"profile:interests:{uid}", "1", ex=600)
        return
    if await redis.get(f"profile:interests:{uid}"):
        interests = "" if (message.text or "").lower().strip() in ("пропустить", "skip") else (message.text or "")[:500]
        async with Session() as s:
            u = await s.get(User, uid); u.interests = interests; await s.commit()
        await redis.delete(f"profile:interests:{uid}")
        await message.answer("Профиль готов. Можешь начинать поиск.", reply_markup=main_menu())
        return

    if message.text:
        text = message.text.strip()
        if text == "👤 Мой профиль" or text == "/profile":
            async with Session() as s:
                u = await s.get(User, uid)
                await message.answer(f"Твой профиль ANONYX:\nПол: {u.gender}\nВозраст: {u.age}\nСтрана: {u.country}\nИнтересы: {u.interests or 'не указаны'}")
            return
        if text == "⚙️ Настройки" or text == "/settings":
            await message.answer("Настройки поиска:", reply_markup=settings_kb()); return
        if text == "🔎 Найти собеседника" or text == "/search":
            await begin_search(message); return
        if text == "⛔ Завершить" or text == "/stop":
            await stop_chat(message); return
        if text == "⭐ Premium":
            async with Session() as s:
                u = await s.get(User, uid)
                if u and u.is_premium and u.premium_until and (u.premium_until.replace(tzinfo=timezone.utc) if u.premium_until.tzinfo is None else u.premium_until) > datetime.now(timezone.utc):
                    await message.answer(f"⭐ ANONYX Premium активен до {u.premium_until:%d.%m.%Y %H:%M} UTC.")
                else:
                    await send_premium_invoice(message)
            return
        if text == "🆘 Помощь" or text == "/help":
            await message.answer("Нажми «Найти собеседника». Сообщения пересылаются анонимно. Не отправляй личные данные. Используй жалобу или блокировку, если собеседник нарушает правила."); return

    partner = await chat_status(uid)
    if partner:
        # Forward supported content without revealing sender identity.
        try:
            await message.copy_to(partner)
        except Exception:
            await message.answer("Не удалось доставить сообщение. Попробуй другой формат.")
    else:
        await message.answer("Сейчас ты не в чате. Нажми «Найти собеседника».", reply_markup=main_menu())

async def begin_search_for_user(uid: int, send_message):
    if not await profile_complete(uid):
        await send_message("Сначала заполни профиль через /start.")
        return
    async with Session() as s:
        u = await s.get(User, uid)
        if not u or u.is_banned:
            await send_message("Доступ ограничен.")
            return
    partner = await chat_status(uid)
    if partner:
        await send_message("Ты уже в чате.")
        return
    progress = await bot.send_message(uid, "🔎 ANONYX ищет собеседника…")
    partner = await find_partner(redis, uid)
    if partner:
        try:
            await progress.edit_text("🎉 Собеседник найден!")
        except Exception:
            pass
        await send_message("Можешь начинать общение.")
        try:
            await bot.send_message(partner, "🎉 Собеседник найден! Можешь начинать общение.", reply_markup=chat_kb())
        except Exception:
            await disconnect(redis, uid)
            await send_message("Собеседник вышел. Попробуй ещё раз.")
    else:
        try:
            await progress.edit_text("🔎 Ищу собеседника…\n\nОставайся на связи. Нажми /stop, чтобы отменить поиск.")
        except Exception:
            await send_message("🔎 Ищу собеседника… Оставайся на связи. Нажми /stop, чтобы отменить поиск.")

async def begin_search(message: Message):
    await begin_search_for_user(message.from_user.id, message.answer)

async def stop_chat(message: Message, notify: bool = True):
    uid = message.from_user.id
    await leave_queue(redis, uid)
    partner = await disconnect(redis, uid)
    if partner and notify:
        try:
            await bot.send_message(partner, "Собеседник завершил чат.", reply_markup=main_menu())
        except Exception:
            pass
    await message.answer("Чат завершён.", reply_markup=main_menu())

@dp.callback_query(F.data.startswith("chat:"))
async def chat_actions(c: CallbackQuery):
    action = c.data.split(":")[1]
    uid = c.from_user.id
    partner = await chat_status(uid)
    if action == "stop":
        await leave_queue(redis, uid)
        partner = await disconnect(redis, uid)
        if partner:
            try: await bot.send_message(partner, "Собеседник завершил чат.", reply_markup=main_menu())
            except Exception: pass
        await c.message.answer("Чат завершён.", reply_markup=main_menu())
    elif action == "next":
        await leave_queue(redis, uid)
        if partner:
            await disconnect(redis, uid)
            try:
                await bot.send_message(partner, "Собеседник завершил чат.", reply_markup=main_menu())
            except Exception:
                pass
        await begin_search_for_user(uid, lambda text: bot.send_message(uid, text, reply_markup=chat_kb()))
    elif action in ("report", "block"):
        if not partner:
            await c.answer("Нет активного собеседника.", show_alert=True); return
        async with Session() as s:
            if action == "report":
                s.add(Report(reporter_id=uid, reported_id=partner, reason="User report"))
            else:
                s.add(Block(blocker_id=uid, blocked_id=partner))
            await s.commit()
        await leave_queue(redis, uid)
        await disconnect(redis, uid)
        try: await bot.send_message(partner, "Чат завершён.", reply_markup=main_menu())
        except Exception: pass
        await c.message.answer("Спасибо. Чат завершён.")
    await c.answer()

@dp.callback_query(F.data.startswith("set:"))
async def settings_actions(c: CallbackQuery, state: FSMContext):
    key = c.data.split(":")[1]
    if key == "gender":
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Любой", callback_data="prefgender:any"),
            InlineKeyboardButton(text="Мужчина", callback_data="prefgender:male"),
            InlineKeyboardButton(text="Женщина", callback_data="prefgender:female")
        ]])
        await c.message.answer("Кого искать?", reply_markup=kb)
    elif key == "age":
        await c.message.answer("Введи минимальный и максимальный возраст через пробел, например: 18 35")
        await state.set_state(SettingsForm.age_range)
    elif key == "country":
        await c.message.answer("Введи страну или «any» для любой страны.")
        await state.set_state(SettingsForm.country)
    elif key == "interests":
        async with Session() as s:
            u = await s.get(User, c.from_user.id); u.match_interests = not u.match_interests; await s.commit()
            val = u.match_interests
        await c.message.answer(f"Поиск по общим интересам: {'включён' if val else 'выключен'}.")
    await c.answer()

@dp.callback_query(F.data.startswith("prefgender:"))
async def pref_gender(c: CallbackQuery):
    val = c.data.split(":")[1]
    async with Session() as s:
        u = await s.get(User, c.from_user.id); u.looking_gender = val; await s.commit()
    await c.message.answer("Предпочтение по полу сохранено.")
    await c.answer()

@dp.message(SettingsForm.age_range)
async def pref_age(message: Message, state: FSMContext):
    try:
        low, high = map(int, message.text.split())
        if low < 18 or high > 99 or low > high: raise ValueError
    except Exception:
        await message.answer("Формат: 18 35. Диапазон должен быть от 18 до 99."); return
    async with Session() as s:
        u = await s.get(User, message.from_user.id); u.min_age=low; u.max_age=high; await s.commit()
    await state.clear(); await message.answer("Возрастной диапазон сохранён.")

@dp.message(SettingsForm.country)
async def pref_country(message: Message, state: FSMContext):
    val = (message.text or "").strip()[:64]
    if not val: await message.answer("Введи страну или any."); return
    async with Session() as s:
        u = await s.get(User, message.from_user.id); u.looking_country=val; await s.commit()
    await state.clear(); await message.answer("Страна для поиска сохранена.")

async def send_premium_invoice(message: Message):
    await message.answer_invoice(
        title="ANONYX Premium на 30 дней",
        description="ANONYX Premium: поддержи проект и получи приоритетный поиск и расширенные настройки.",
        payload=f"premium:{message.from_user.id}:{int(time.time())}",
        currency="XTR",
        prices=[LabeledPrice(label="Premium", amount=config.premium_price_stars)],
        provider_token=""
    )

@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    if not message.successful_payment or message.successful_payment.currency != "XTR":
        return
    until = datetime.now(timezone.utc) + timedelta(days=config.premium_days)
    async with Session() as s:
        u = await s.get(User, message.from_user.id)
        if u:
            existing_until = u.premium_until.replace(tzinfo=timezone.utc) if u.premium_until and u.premium_until.tzinfo is None else u.premium_until
            base = existing_until if existing_until and existing_until > datetime.now(timezone.utc) else datetime.now(timezone.utc)
            u.premium_until = base.replace(tzinfo=None) + timedelta(days=config.premium_days)
            u.is_premium = True
            await s.commit()
    await message.answer("⭐ Спасибо! Premium активирован.")

@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if not is_admin(message.from_user.id): return
    await message.answer("Панель администратора", reply_markup=admin_kb())

@dp.callback_query(F.data == "admin:reports")
async def admin_reports(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("Нет доступа", show_alert=True)
        return
    async with Session() as s:
        rows = (await s.scalars(select(Report).order_by(Report.created_at.desc()).limit(15))).all()
    if not rows:
        await c.message.answer("Новых жалоб нет.")
    else:
        lines = ["🚩 Последние жалобы:"]
        for r in rows:
            lines.append(f"#{r.id} · от {r.reporter_id} на {r.reported_id} · {r.reason}")
        await c.message.answer("\n".join(lines))
    await c.answer()

@dp.callback_query(F.data == "admin:stats")
async def admin_stats(c: CallbackQuery):
    if not is_admin(c.from_user.id): await c.answer("Нет доступа", show_alert=True); return
    async with Session() as s:
        total = await s.scalar(select(func.count()).select_from(User))
        banned = await s.scalar(select(func.count()).select_from(User).where(User.is_banned.is_(True)))
        premium = await s.scalar(select(func.count()).select_from(User).where(User.is_premium.is_(True)))
        reports = await s.scalar(select(func.count()).select_from(Report))
    active = len(await redis.hkeys("chat:active")) // 2
    waiting = await redis.zcard("match:queue")
    await c.message.answer(f"📊 ANONYX — статистика\nПользователей: {total}\nВ чатах сейчас: {active}\nВ очереди поиска: {waiting}\nЗаблокировано: {banned}\nPremium: {premium}\nЖалоб: {reports}")
    await c.answer()

@dp.message(Command("ban"))
async def ban_cmd(message: Message):
    if not is_admin(message.from_user.id): return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /ban TELEGRAM_ID [причина]"); return
    target = int(parts[1])
    async with Session() as s:
        u = await s.get(User, target)
        if not u: await message.answer("Пользователь не найден."); return
        u.is_banned = True; await s.commit()
    partner = await disconnect(redis, target)
    if partner:
        try: await bot.send_message(partner, "Чат завершён администрацией.", reply_markup=main_menu())
        except Exception: pass
    await message.answer(f"Пользователь {target} заблокирован.")

@dp.message(Command("unban"))
async def unban_cmd(message: Message):
    if not is_admin(message.from_user.id): return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /unban TELEGRAM_ID"); return
    async with Session() as s:
        u = await s.get(User, int(parts[1]))
        if not u: await message.answer("Пользователь не найден."); return
        u.is_banned = False; await s.commit()
    await message.answer("Блокировка снята.")

@dp.message(Command("broadcast"))
async def broadcast_cmd(message: Message):
    if not is_admin(message.from_user.id): return
    body = (message.text or "").partition(" ")[2].strip()
    if not body:
        await message.answer("Использование: /broadcast текст сообщения"); return
    async with Session() as s:
        ids = list((await s.scalars(select(User.id).where(User.is_banned.is_(False)))).all())
    ok = 0
    for uid in ids:
        try:
            await bot.send_message(uid, body)
            ok += 1
            await asyncio.sleep(config.broadcast_delay_seconds)
        except Exception:
            continue
    await message.answer(f"Рассылка завершена. Доставлено: {ok}/{len(ids)}")

# Register the generic message handler last. This is important: state-specific
# handlers and commands such as /ban must be evaluated before this fallback.
dp.message.register(text_router)

async def main():
    await init_db()
    logging.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await redis.close()
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())

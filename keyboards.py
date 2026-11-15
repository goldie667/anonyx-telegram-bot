from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🔎 Найти собеседника"), KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="⭐ Premium")],
        [KeyboardButton(text="🆘 Помощь")]
    ], resize_keyboard=True)

def gender_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Мужчина", callback_data="gender:male"),
        InlineKeyboardButton(text="Женщина", callback_data="gender:female")
    ]])

def yes_no_kb(prefix: str):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да", callback_data=f"{prefix}:yes"),
        InlineKeyboardButton(text="Нет", callback_data=f"{prefix}:no")
    ]])

def chat_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Следующий", callback_data="chat:next"),
         InlineKeyboardButton(text="⛔ Завершить", callback_data="chat:stop")],
        [InlineKeyboardButton(text="🚩 Пожаловаться", callback_data="chat:report"),
         InlineKeyboardButton(text="🚫 Заблокировать", callback_data="chat:block")]
    ])

def settings_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пол собеседника", callback_data="set:gender")],
        [InlineKeyboardButton(text="Возрастной диапазон", callback_data="set:age")],
        [InlineKeyboardButton(text="Страна", callback_data="set:country")],
        [InlineKeyboardButton(text="Общие интересы", callback_data="set:interests")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="🚩 Последние жалобы", callback_data="admin:reports")]
    ])

from aiogram.fsm.state import State, StatesGroup

class ProfileForm(StatesGroup):
    age = State()
    country = State()
    interests = State()

class SettingsForm(StatesGroup):
    age_range = State()
    country = State()

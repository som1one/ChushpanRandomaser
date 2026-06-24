from aiogram.fsm.state import State, StatesGroup


class QuizCreationStates(StatesGroup):
    choosing_columns = State()
    waiting_for_photo_and_text = State()
    collecting_options = State()
    waiting_for_max_votes = State()
    waiting_for_allow_change = State()
    final = State()

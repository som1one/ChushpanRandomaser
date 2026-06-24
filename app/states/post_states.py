from aiogram.fsm.state import State, StatesGroup


class PostBuilderStates(StatesGroup):
    waiting_for_content = State()
    adding_buttons = State()
    waiting_for_button_url = State()
    preview = State()

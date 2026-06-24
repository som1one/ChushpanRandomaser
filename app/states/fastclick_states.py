from aiogram.fsm.state import State, StatesGroup


class FastClickStates(StatesGroup):
    waiting_for_text = State()
    confirm = State()


class FastClickEditStates(StatesGroup):
    waiting_for_intrigue_input = State()

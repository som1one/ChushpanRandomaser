from aiogram.fsm.state import State, StatesGroup


class ListManageStates(StatesGroup):
    list_main = State()
    choosing_event = State()
    managing_event = State()
    editing_winners = State()
    editing_participants = State()
    editing_button_text = State()
    additional_menu = State()
    autobytes_menu = State()
    editing_autobytes_interval = State()
    sponsor_menu = State()
    sponsor_adding = State()
    sponsor_deleting = State()
    share_menu = State()

from aiogram.fsm.state import State, StatesGroup


class FastConnectStates(StatesGroup):
    waiting_for_email = State()
    waiting_for_password = State()


class FastConnectLoginStates(StatesGroup):
    waiting_for_email = State()
    waiting_for_password = State()


class ChannelStates(StatesGroup):
    waiting_for_channel_username = State()
    waiting_for_channel_selection = State()

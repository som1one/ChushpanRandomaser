from aiogram.fsm.state import State, StatesGroup


class MailingStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_image = State()
    waiting_for_batch_size = State()
    waiting_for_delay = State()
    waiting_for_button_text = State()
    waiting_for_button_url = State()
    confirm_mailing = State()


class SubscriptionStates(StatesGroup):
    waiting_for_action = State()
    waiting_for_user_input = State()


class AdminContestManagementStates(StatesGroup):
    choosing_contest = State()
    choosing_action = State()
    waiting_for_user_id_to_boost = State()
    waiting_for_boost_amount = State()
    waiting_for_guaranteed_winners = State()

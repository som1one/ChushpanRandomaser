from aiogram.fsm.state import State, StatesGroup


class LotMenuStates(StatesGroup):
    choosing_type = State()

    # Contest States
    waiting_for_contest_text = State()
    waiting_for_contest_participants = State()
    contest_waiting_for_finish_value = State()
    waiting_for_contest_winners = State()
    waiting_for_contest_sponsors = State()
    waiting_for_contest_vote_required = State()
    waiting_for_contest_button_text = State()
    waiting_for_contest_schedule = State()
    contest_waiting_for_plan_time = State()
    waiting_for_contest_publication = State()
    contest_waiting_for_cond_id = State()

    # Lottery States
    waiting_for_lottery_text = State()
    waiting_for_lottery_tickets = State()
    lottery_enter_custom_tickets = State()
    waiting_for_lottery_sponsors = State()
    waiting_for_lottery_vote_required = State()
    waiting_for_lottery_publication = State()

    # Referral States
    waiting_for_ref_text = State()
    waiting_for_ref_participants = State()
    ref_waiting_for_finish_value = State()
    waiting_for_ref_winners = State()
    waiting_for_ref_sponsors = State()
    waiting_for_ref_vote_required = State()
    waiting_for_ref_button_text = State()
    waiting_for_ref_schedule = State()
    ref_waiting_for_plan_time = State()
    waiting_for_ref_publication = State()
    waiting_for_ref_condition = State()

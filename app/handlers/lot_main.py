"""Handler for /lot command — event type selection."""

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from app.states import LotMenuStates

lot_main_router = Router()


@lot_main_router.message(Command("lot"))
async def cmd_lot(message: types.Message, state: FSMContext):
    await state.clear()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🎉 Конкурс", callback_data="lot_type:contest"),
            types.InlineKeyboardButton(text="🍀 Лотерея", callback_data="lot_type:lottery"),
            types.InlineKeyboardButton(text="🔗 Реферальный", callback_data="lot_type:referral"),
        ]
    ])
    await message.answer("🎟️ Выберите тип события:", reply_markup=kb)
    await state.set_state(LotMenuStates.choosing_type)


@lot_main_router.callback_query(LotMenuStates.choosing_type, F.data.startswith("lot_type:"))
async def on_lot_type_chosen(callback: types.CallbackQuery, state: FSMContext):
    event_type = callback.data.split(":")[1]
    await state.update_data(lot_type=event_type)

    if event_type == "contest":
        await callback.message.edit_text("📝 Отправьте текст конкурса (можно с фото/видео):")
        await state.set_state(LotMenuStates.waiting_for_contest_text)
    elif event_type == "lottery":
        await callback.message.edit_text("📝 Отправьте текст лотереи:")
        await state.set_state(LotMenuStates.waiting_for_lottery_text)
    elif event_type == "referral":
        await callback.message.edit_text("📝 Отправьте текст реферального конкурса:")
        await state.set_state(LotMenuStates.waiting_for_ref_text)

    await callback.answer()

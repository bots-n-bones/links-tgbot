"""Accept/Decline на адресный DM-инвайт (личный кабинет v2, волна 5) —
намеренно НЕ проверяет is_whitelisted/require_authorized: приглашённый по
определению ещё не в whitelist, это и есть весь смысл кнопки. Защита от
чужого тапа — сверка target_telegram_id внутри access.redeem_invite_by_id/
decline_invite_by_id по фактическому callback.from_user.id (не
callback.message.from_user — это бот, см. гочу в bot/access.py)."""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.access import decline_invite_by_id, redeem_invite_by_id
from bot.keyboards import CB_INVITE_ACCEPT_PREFIX, CB_INVITE_DECLINE_PREFIX

router = Router()


@router.callback_query(F.data.startswith(CB_INVITE_ACCEPT_PREFIX))
async def cb_invite_accept(callback: CallbackQuery) -> None:
    invite_id = int(callback.data.removeprefix(CB_INVITE_ACCEPT_PREFIX))
    ok = await redeem_invite_by_id(invite_id, callback.from_user.id)
    if not ok:
        await callback.answer("This invite is no longer valid.", show_alert=True)
        return
    if callback.message:
        await callback.message.edit_text("You've joined the team. Send /help to get started.")
    await callback.answer()


@router.callback_query(F.data.startswith(CB_INVITE_DECLINE_PREFIX))
async def cb_invite_decline(callback: CallbackQuery) -> None:
    invite_id = int(callback.data.removeprefix(CB_INVITE_DECLINE_PREFIX))
    ok = await decline_invite_by_id(invite_id, callback.from_user.id)
    if not ok:
        await callback.answer("This invite is no longer valid.", show_alert=True)
        return
    if callback.message:
        await callback.message.edit_text("Invite declined.")
    await callback.answer()

"""Инлайн-меню — основной способ взаимодействия с ботом (не команды вводом)."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CB_DAILY_DIGEST = "menu:daily_digest"
CB_WEEKLY_DIGEST = "menu:weekly_digest"
CB_ASK = "menu:ask"
CB_SEARCH = "menu:search"
CB_STATS = "menu:stats"
CB_HELP = "menu:help"


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📥 Daily digest", callback_data=CB_DAILY_DIGEST),
                InlineKeyboardButton(text="🗓 Weekly digest", callback_data=CB_WEEKLY_DIGEST),
            ],
            [
                InlineKeyboardButton(text="❓ Ask", callback_data=CB_ASK),
                InlineKeyboardButton(text="🔍 Search", callback_data=CB_SEARCH),
            ],
            [
                InlineKeyboardButton(text="📊 Stats", callback_data=CB_STATS),
                InlineKeyboardButton(text="🆘 Help", callback_data=CB_HELP),
            ],
        ]
    )

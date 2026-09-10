"""Инлайн-меню — основной способ взаимодействия с ботом (не команды вводом)."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CB_DAILY_DIGEST = "menu:daily_digest"
CB_WEEKLY_DIGEST = "menu:weekly_digest"
CB_ASK = "menu:ask"
CB_SEARCH = "menu:search"
CB_STATS = "menu:stats"
CB_HELP = "menu:help"

CB_INVITE_ACCEPT_PREFIX = "invite:accept:"
CB_INVITE_DECLINE_PREFIX = "invite:decline:"


def invite_decision_keyboard(invite_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Accept", callback_data=f"{CB_INVITE_ACCEPT_PREFIX}{invite_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Decline", callback_data=f"{CB_INVITE_DECLINE_PREFIX}{invite_id}"
                ),
            ]
        ]
    )


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


# --- Разметка ссылки прямо в чате ---------------------------------------
# Разметка «на месте» существует потому, что момент, когда человек кинул
# ссылку, — единственный, когда он точно помнит, зачем. Дойти до дашборда
# успевают не всегда, и запись остаётся неразобранной.

CB_LINK_PREFIX = "link:"


def link_cb(action: str, link_id: int, value: str = "") -> str:
    return f"{CB_LINK_PREFIX}{action}:{link_id}" + (f":{value}" if value else "")


def parse_link_cb(data: str) -> tuple[str, int, str] | None:
    """('reviewed', 12, '') из 'link:reviewed:12'. None — не наш callback."""
    if not data.startswith(CB_LINK_PREFIX):
        return None
    parts = data[len(CB_LINK_PREFIX) :].split(":")
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    return parts[0], int(parts[1]), parts[2] if len(parts) > 2 else ""


def link_actions_keyboard(link_id: int, dashboard_url: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📥 Разобрано", callback_data=link_cb("reviewed", link_id)),
            InlineKeyboardButton(text="✅ Проверено", callback_data=link_cb("tested", link_id)),
        ],
        [
            InlineKeyboardButton(text="⬆️ Важное", callback_data=link_cb("prio", link_id, "high")),
            InlineKeyboardButton(text="🗂 Area", callback_data=link_cb("areas", link_id)),
            InlineKeyboardButton(text="🙈 Скрыть", callback_data=link_cb("hide", link_id)),
        ],
    ]
    if dashboard_url:
        rows.append(
            [InlineKeyboardButton(text="Открыть в COLLECT", url=f"{dashboard_url}/links/{link_id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def link_area_keyboard(link_id: int, areas: list[str]) -> InlineKeyboardMarkup:
    """Area — короткий фиксированный список, поэтому помещается кнопками.
    Теги произвольные и в клавиатуру не влезают: их правят в дашборде."""
    rows = [
        [
            InlineKeyboardButton(text=area, callback_data=link_cb("area", link_id, area))
            for area in areas[index : index + 3]
        ]
        for index in range(0, len(areas), 3)
    ]
    rows.append([InlineKeyboardButton(text="← назад", callback_data=link_cb("back", link_id))])
    return InlineKeyboardMarkup(inline_keyboard=rows)

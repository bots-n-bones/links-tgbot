"""Общая логика захвата постов (F: вкладка Posts) — используется и в
группах (bot/handlers/group.py, только сообщения с внешней ссылкой), и в
личке (bot/handlers/private.py, только форварды из публичных каналов)."""

from aiogram.types import Message, MessageOriginChannel


def resolve_post_url(message: Message) -> str:
    """Форвард из публичного канала — ссылка на оригинальный пост (у него
    есть нормальный Telegram-превью). Иначе — внутренний deep-link,
    открывается только у участников чата/самого пользователя."""
    origin = message.forward_origin
    if isinstance(origin, MessageOriginChannel) and origin.chat.username:
        return f"https://t.me/{origin.chat.username}/{origin.message_id}"

    chat_id_str = str(message.chat.id)
    internal_id = chat_id_str[4:] if chat_id_str.startswith("-100") else chat_id_str.lstrip("-")
    return f"https://t.me/c/{internal_id}/{message.message_id}"


def is_public_channel_forward(message: Message) -> bool:
    origin = message.forward_origin
    return isinstance(origin, MessageOriginChannel) and bool(origin.chat.username)


def build_post_payload(message: Message, urls: list[str]) -> dict:
    # Форвард из канала в личку: message.chat — это ЛС с ботом (без title),
    # реальное имя канала — в forward_origin.chat.title.
    origin = message.forward_origin
    chat_title = (
        origin.chat.title
        if isinstance(origin, MessageOriginChannel) and origin.chat.title
        else message.chat.title
    )
    return {
        "chat_id": message.chat.id,
        "message_id": message.message_id,
        "chat_title": chat_title,
        "sender_id": message.from_user.id if message.from_user else None,
        "sender_name": message.from_user.full_name if message.from_user else None,
        "text": message.text or message.caption,
        "urls": urls,
        "post_url": resolve_post_url(message),
        "photo_file_id": message.photo[-1].file_id if message.photo else None,
    }

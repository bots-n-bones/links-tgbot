from dataclasses import dataclass, field

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select

import bot.handlers.commands as commands_module
import bot.handlers.group as group_module
import bot.handlers.private as private_module
from bot.access import INVITE_INVALID_TEXT, INVITE_REDEEMED_TEXT, NO_ACCESS_TEXT, create_invite
from bot.handlers.private import HELP_HINT_TEXT
from db.models import Collection, Link, LinkStatus, LinkTag, RawMessage, SourceType, Tag
from tests.bot.conftest import WHITELISTED_USER_ID


def make_state(sender_id: int) -> FSMContext:
    return FSMContext(
        storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=sender_id, user_id=sender_id)
    )


@dataclass
class FakeUser:
    id: int
    username: str | None = None
    full_name: str | None = None


@dataclass
class FakeChat:
    id: int
    type: str
    title: str | None = None


@dataclass
class FakeMessage:
    chat: FakeChat
    from_user: FakeUser | None
    message_id: int
    text: str | None = None
    caption: str | None = None
    entities: list | None = field(default_factory=list)
    caption_entities: list | None = field(default_factory=list)
    reply_to_message: "FakeMessage | None" = None
    photo: list | None = None
    forward_origin: object | None = None
    sent: list[str] = field(default_factory=list)

    async def answer(self, text: str, **kwargs) -> None:
        self.sent.append(text)

    async def reply(self, text: str, **kwargs) -> None:
        self.sent.append(text)


BOT_FAKE_USER_ID = 0  # callback.message.from_user — это бот, не нажавший кнопку человек


@dataclass
class FakeCallbackQuery:
    data: str
    message: FakeMessage
    from_user: FakeUser
    answered: list[str | None] = field(default_factory=list)

    async def answer(self, text: str | None = None, **kwargs) -> None:
        self.answered.append(text)


def make_callback(data: str, message: FakeMessage, sender_id: int) -> FakeCallbackQuery:
    """message.from_user всегда 'бот' (как в реальном aiogram — сообщение с
    кнопкой отправил бот), sender_id — реальный нажавший кнопку пользователь."""
    message.from_user = FakeUser(id=BOT_FAKE_USER_ID)
    return FakeCallbackQuery(data=data, message=message, from_user=FakeUser(id=sender_id))


def make_group_message(
    message_id: int,
    text: str,
    sender_id: int = 1,
    reply_to_message: FakeMessage | None = None,
) -> FakeMessage:
    return FakeMessage(
        chat=FakeChat(id=-100123, type="group"),
        from_user=FakeUser(id=sender_id),
        message_id=message_id,
        text=text,
        reply_to_message=reply_to_message,
    )


def make_private_message(message_id: int, text: str | None, sender_id: int) -> FakeMessage:
    return FakeMessage(
        chat=FakeChat(id=sender_id, type="private"),
        from_user=FakeUser(id=sender_id),
        message_id=message_id,
        text=text,
    )


# --- group handler ---


async def test_group_handler_ingests_url_and_enqueues(db_session, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(group_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    msg = make_group_message(1, "смотрите https://example.com/a")
    await group_module.handle_group_message(msg)

    rows = (await db_session.execute(select(RawMessage))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source_type == SourceType.group
    assert len(enqueued) == 1


async def test_group_handler_ignores_telegram_channel_links(db_session, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(group_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    msg = make_group_message(4, "Подписывайтесь на канал: https://t.me/some_channel/42")
    await group_module.handle_group_message(msg)

    rows = (await db_session.execute(select(RawMessage))).scalars().all()
    assert len(rows) == 0
    assert enqueued == []


async def test_group_handler_keeps_non_telegram_link_alongside_telegram_one(
    db_session, monkeypatch
):
    enqueued: list[int] = []
    monkeypatch.setattr(group_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    msg = make_group_message(5, "https://example.com/article смотрите также https://t.me/x/1")
    await group_module.handle_group_message(msg)

    rows = (await db_session.execute(select(RawMessage))).scalars().all()
    assert len(rows) == 1  # raw_message сохраняется целиком, фильтруется только список URL
    assert len(enqueued) == 1


# --- Posts capture (F: вкладка Posts, сохраняем каждое сообщение) ---


async def test_group_handler_enqueues_post_with_link_and_delay(db_session, monkeypatch):
    calls: list[tuple[dict, int]] = []
    monkeypatch.setattr(
        group_module,
        "enqueue_post_processing",
        lambda payload, countdown=0: calls.append((payload, countdown)),
    )
    monkeypatch.setattr(group_module, "enqueue_processing", lambda rid: None)

    msg = make_group_message(60, "check https://example.com/a")
    await group_module.handle_group_message(msg)

    assert len(calls) == 1
    payload, countdown = calls[0]
    assert payload["urls"] == ["https://example.com/a"]
    assert countdown == 20  # с задержкой, чтобы ссылка успела обработаться


async def test_group_handler_enqueues_post_without_link_immediately(db_session, monkeypatch):
    calls: list[tuple[dict, int]] = []
    monkeypatch.setattr(
        group_module,
        "enqueue_post_processing",
        lambda payload, countdown=0: calls.append((payload, countdown)),
    )

    msg = make_group_message(61, "просто болтовня без ссылок")
    await group_module.handle_group_message(msg)

    assert len(calls) == 1
    payload, countdown = calls[0]
    assert payload["urls"] == []
    assert countdown == 0


async def test_group_handler_skips_post_enqueue_for_empty_message(db_session, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        group_module, "enqueue_post_processing", lambda payload, **kw: calls.append(payload)
    )

    msg = make_group_message(62, None)
    await group_module.handle_group_message(msg)

    assert calls == []


def test_resolve_post_url_uses_original_channel_post_for_public_forwards():
    from datetime import UTC, datetime

    from aiogram.types import Chat, MessageOriginChannel

    from bot.post_capture import resolve_post_url

    origin = MessageOriginChannel(
        type="channel",
        date=datetime.now(UTC),
        chat=Chat(id=-1001111111111, type="channel", username="somechannel"),
        message_id=777,
    )
    msg = make_group_message(63, "forwarded post")
    msg.forward_origin = origin

    assert resolve_post_url(msg) == "https://t.me/somechannel/777"


def test_resolve_post_url_falls_back_to_internal_deep_link_without_forward():
    from bot.post_capture import resolve_post_url

    msg = make_group_message(64, "own message")
    msg.chat = FakeChat(id=-100123456789, type="group")

    assert resolve_post_url(msg) == "https://t.me/c/123456789/64"


async def test_group_handler_no_url_ignored_silently(db_session, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(group_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    msg = make_group_message(2, "просто болтовня без ссылок")
    await group_module.handle_group_message(msg)

    rows = (await db_session.execute(select(RawMessage))).scalars().all()
    assert len(rows) == 0
    assert msg.sent == []
    assert enqueued == []


async def test_group_handler_idempotent_on_duplicate_message(db_session, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(group_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    msg1 = make_group_message(3, "https://example.com/dup")
    msg2 = make_group_message(3, "https://example.com/dup")  # тот же message_id
    await group_module.handle_group_message(msg1)
    await group_module.handle_group_message(msg2)

    rows = (await db_session.execute(select(RawMessage))).scalars().all()
    assert len(rows) == 1
    assert len(enqueued) == 1  # второй раз не поставлено в очередь


async def test_group_handler_ignores_plain_mention_without_bot_username(db_session):
    # без bot_username (не передан из workflow_data) — мы не можем узнать, что
    # это обращение к боту, тихо игнорируем
    msg = make_group_message(6, "@testbot а что там про RAG?")
    await group_module.handle_group_message(msg)
    assert msg.sent == []


async def test_group_handler_replies_to_mention_without_citations(db_session):
    # ENV=test => FakeLLMClient/FakeEmbeddingClient (см. tests/bot/conftest.py)
    msg = make_group_message(7, "@testbot а что там про RAG?")
    await group_module.handle_group_message(msg, bot_username="testbot")
    assert len(msg.sent) == 1
    assert "Фейковый ответ LLM." in msg.sent[0]
    assert "Источники" not in msg.sent[0]


async def test_group_handler_mention_is_case_insensitive_and_stripped(db_session):
    msg = make_group_message(8, "@TestBot есть что про RAG?")
    await group_module.handle_group_message(msg, bot_username="testbot")
    assert len(msg.sent) == 1


async def test_group_handler_replies_to_bot_message_continues_dialog(db_session):
    # Ответ (reply) на предыдущее сообщение бота — продолжение диалога без
    # повторного @упоминания.
    bots_message = make_group_message(9, "Имя просто такое", sender_id=0)
    bots_message.from_user = FakeUser(id=0, username="testbot")

    msg = make_group_message(10, "А мне кажется нет", reply_to_message=bots_message)
    await group_module.handle_group_message(msg, bot_username="testbot")

    assert len(msg.sent) == 1
    assert "Фейковый ответ LLM." in msg.sent[0]


async def test_group_handler_ignores_reply_to_other_user(db_session):
    someone_elses_message = make_group_message(11, "привет всем", sender_id=5)
    msg = make_group_message(12, "ты о чём?", reply_to_message=someone_elses_message)
    await group_module.handle_group_message(msg, bot_username="testbot")
    assert msg.sent == []


# --- private handler: whitelist ---


async def test_private_handler_denies_non_whitelisted(db_session):
    msg = make_private_message(10, "https://example.com/a", sender_id=1)  # не в whitelist
    await private_module.handle_private_message(msg, make_state(1))

    assert msg.sent == [NO_ACCESS_TEXT]
    rows = (await db_session.execute(select(RawMessage))).scalars().all()
    assert len(rows) == 0


async def test_private_handler_redeems_valid_invite_code(db_session):
    code = await create_invite(created_by=WHITELISTED_USER_ID)

    msg = make_private_message(14, code, sender_id=42)  # не в whitelist
    await private_module.handle_private_message(msg, make_state(42))
    assert msg.sent == [INVITE_REDEEMED_TEXT]

    # код одноразовый — второй пользователь тем же кодом доступ не получает
    msg2 = make_private_message(15, code, sender_id=43)
    await private_module.handle_private_message(msg2, make_state(43))
    assert msg2.sent == [INVITE_INVALID_TEXT]

    # погасивший код пользователь теперь в whitelist
    msg3 = make_private_message(16, None, sender_id=42)
    await private_module.handle_private_message(msg3, make_state(42))
    assert msg3.sent == [HELP_HINT_TEXT]


async def test_private_handler_rejects_unknown_invite_code(db_session):
    msg = make_private_message(17, "NOPE1234", sender_id=44)
    await private_module.handle_private_message(msg, make_state(44))
    assert msg.sent == [INVITE_INVALID_TEXT]


async def test_private_handler_whitelisted_with_url_ingests(db_session, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(private_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    msg = make_private_message(11, "https://example.com/b", sender_id=WHITELISTED_USER_ID)
    await private_module.handle_private_message(msg, make_state(WHITELISTED_USER_ID))

    assert msg.sent == []  # подтверждение шлёт воркер (Фаза 4), не сразу
    rows = (await db_session.execute(select(RawMessage))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source_type == SourceType.direct
    assert len(enqueued) == 1


async def test_private_handler_whitelisted_no_url_routes_to_qa(db_session):
    # ENV=test (см. tests/bot/conftest.py) => worker.rag использует FakeLLMClient/
    # FakeEmbeddingClient, реальные вызовы OpenAI не выполняются
    msg = make_private_message(12, "а есть что-то про RAG?", sender_id=WHITELISTED_USER_ID)
    await private_module.handle_private_message(msg, make_state(WHITELISTED_USER_ID))
    assert len(msg.sent) == 1
    assert "Фейковый ответ LLM." in msg.sent[0]
    # свободный текст (не /ask) — просто ответ, без списка источников
    assert "Источники" not in msg.sent[0]


async def test_private_handler_whitelisted_no_text_routes_to_help_hint(db_session):
    msg = make_private_message(13, None, sender_id=WHITELISTED_USER_ID)
    await private_module.handle_private_message(msg, make_state(WHITELISTED_USER_ID))
    assert msg.sent == [HELP_HINT_TEXT]


def _make_public_channel_origin(message_id: int = 100, username: str = "somechannel"):
    from datetime import UTC, datetime

    from aiogram.types import Chat, MessageOriginChannel

    return MessageOriginChannel(
        type="channel",
        date=datetime.now(UTC),
        chat=Chat(id=-1001111111111, type="channel", username=username),
        message_id=message_id,
    )


def _make_private_channel_origin(message_id: int = 100):
    from datetime import UTC, datetime

    from aiogram.types import Chat, MessageOriginChannel

    return MessageOriginChannel(
        type="channel",
        date=datetime.now(UTC),
        chat=Chat(id=-1002222222222, type="channel", username=None),
        message_id=message_id,
    )


async def test_private_handler_captures_public_channel_forward_without_links(
    db_session, monkeypatch
):
    calls: list[tuple[dict, int]] = []
    monkeypatch.setattr(
        private_module,
        "enqueue_post_processing",
        lambda payload, countdown=0: calls.append((payload, countdown)),
    )

    msg = make_private_message(70, "some interesting post", sender_id=WHITELISTED_USER_ID)
    msg.forward_origin = _make_public_channel_origin()
    await private_module.handle_private_message(msg, make_state(WHITELISTED_USER_ID))

    assert len(calls) == 1
    payload, countdown = calls[0]
    assert payload["post_url"] == "https://t.me/somechannel/100"
    assert countdown == 0
    assert msg.sent == []  # чистый форвард без ссылок — просто сохранили, без ответа


async def test_private_handler_captures_public_channel_forward_with_link(
    db_session, monkeypatch
):
    post_calls: list[tuple[dict, int]] = []
    monkeypatch.setattr(
        private_module,
        "enqueue_post_processing",
        lambda payload, countdown=0: post_calls.append((payload, countdown)),
    )
    enqueued: list[int] = []
    monkeypatch.setattr(private_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    msg = make_private_message(
        71, "check this https://example.com/a", sender_id=WHITELISTED_USER_ID
    )
    msg.forward_origin = _make_public_channel_origin(message_id=200)
    await private_module.handle_private_message(msg, make_state(WHITELISTED_USER_ID))

    assert len(post_calls) == 1
    payload, countdown = post_calls[0]
    assert payload["urls"] == ["https://example.com/a"]
    assert countdown == 20
    assert len(enqueued) == 1  # ссылка всё равно идёт в обычный link-пайплайн

    rows = (await db_session.execute(select(RawMessage))).scalars().all()
    assert len(rows) == 1


async def test_private_handler_ignores_forward_from_private_channel(db_session, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        private_module, "enqueue_post_processing", lambda payload, **kw: calls.append(payload)
    )

    msg = make_private_message(72, "some post", sender_id=WHITELISTED_USER_ID)
    msg.forward_origin = _make_private_channel_origin()
    await private_module.handle_private_message(msg, make_state(WHITELISTED_USER_ID))

    assert calls == []  # не публичный канал — постом не считаем
    assert len(msg.sent) == 1  # ушло в обычный casual chat как текст


# --- commands ---


async def test_cmd_start_denied_for_non_whitelisted(db_session):
    msg = make_private_message(20, "/start", sender_id=1)
    await commands_module.cmd_start(msg)
    assert msg.sent == [NO_ACCESS_TEXT]


async def test_cmd_start_whitelisted(db_session):
    msg = make_private_message(21, "/start", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_start(msg)
    assert msg.sent == [commands_module.START_TEXT]


async def test_cmd_help_whitelisted():
    msg = make_private_message(22, "/help", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_help(msg)
    assert msg.sent == [commands_module.HELP_TEXT]


async def test_cmd_invite_denied_for_non_admin(db_session):
    msg = make_private_message(31, "/invite", sender_id=WHITELISTED_USER_ID)  # не админ
    await commands_module.cmd_invite(msg)
    assert msg.sent == ["Эта команда доступна только администратору."]


async def test_cmd_invite_generates_redeemable_code(db_session, monkeypatch):
    monkeypatch.setenv("ADMIN_USER_ID", "777")
    from shared import config as config_module

    config_module.get_settings.cache_clear()

    msg = make_private_message(32, "/invite", sender_id=777)
    await commands_module.cmd_invite(msg)
    assert len(msg.sent) == 1
    assert "Инвайт-код:" in msg.sent[0]
    code = msg.sent[0].split("Инвайт-код:")[1].splitlines()[0].strip()

    redeem_msg = make_private_message(33, code, sender_id=55)
    await private_module.handle_private_message(redeem_msg, make_state(55))
    assert redeem_msg.sent == [INVITE_REDEEMED_TEXT]


@dataclass
class FakeCommandObject:
    args: str | None


async def test_cmd_ask_without_question_shows_usage(db_session):
    msg = make_private_message(23, "/ask", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_ask(msg, FakeCommandObject(args=None))
    assert msg.sent == ["Использование: /ask <вопрос>"]


async def test_cmd_ask_with_question_answers(db_session):
    msg = make_private_message(24, "/ask что у нас есть про RAG?", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_ask(msg, FakeCommandObject(args="что у нас есть про RAG?"))
    assert len(msg.sent) == 1
    assert "Фейковый ответ LLM." in msg.sent[0]


async def test_cmd_search_without_topic_shows_usage(db_session):
    msg = make_private_message(25, "/search", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_search(msg, FakeCommandObject(args=None))
    assert msg.sent == ["Использование: /search <тема>"]


async def test_cmd_search_returns_bare_list(db_session):
    link = Link(
        url="https://a.com",
        normalized_url="a.com",
        url_hash="h-search",
        title="Статья про RAG",
        status=LinkStatus.done,
    )
    db_session.add(link)
    await db_session.commit()

    msg = make_private_message(26, "/search RAG", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_search(msg, FakeCommandObject(args="RAG"))
    assert len(msg.sent) == 1
    assert '<a href="https://a.com">Статья про RAG</a>' in msg.sent[0]


async def test_cmd_search_no_results(db_session):
    msg = make_private_message(27, "/search несуществующее", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_search(msg, FakeCommandObject(args="несуществующее"))
    assert msg.sent == ["Ничего не найдено."]


async def test_cmd_daily_digest_no_collections_yet(db_session):
    msg = make_private_message(28, "/daily_digest", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_daily_digest(msg)
    assert "Подборок пока нет" in msg.sent[0]


async def test_cmd_weekly_digest_no_collections_yet(db_session):
    msg = make_private_message(281, "/weekly_digest", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_weekly_digest(msg)
    assert "Подборок пока нет" in msg.sent[0]


# --- commands: работают в группах без whitelist ---


async def test_cmd_start_works_in_group_for_non_whitelisted_sender():
    msg = make_group_message(40, "/start", sender_id=999999)  # не в whitelist, но группа доверена
    await commands_module.cmd_start(msg)
    assert msg.sent == [commands_module.START_TEXT]


async def test_cmd_stats_works_in_group_for_non_whitelisted_sender(db_session):
    msg = make_group_message(41, "/stats", sender_id=999999)
    await commands_module.cmd_stats(msg)
    assert "Всего ссылок в базе" in msg.sent[0]


async def test_cmd_weekly_digest_returns_latest_collection(db_session):
    from datetime import date

    collection = Collection(
        title="Weekly digest — Jul 07, 2026",
        theme="weekly-digest",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 7),
        summary_md="",
        articles=[{"title": "Great find", "url": "https://a.com", "description": "why it matters"}],
    )
    db_session.add(collection)
    await db_session.commit()

    msg = make_private_message(29, "/weekly_digest", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_weekly_digest(msg)
    assert "Weekly digest — Jul 07, 2026" in msg.sent[0]
    assert "Great find — https://a.com" in msg.sent[0]
    assert "why it matters" in msg.sent[0]


async def test_cmd_daily_digest_ignores_weekly_collection(db_session):
    from datetime import date

    collection = Collection(
        title="Weekly digest — Jul 07, 2026",
        theme="weekly-digest",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 7),
        summary_md="",
        articles=[{"title": "Great find", "url": "https://a.com", "description": "why it matters"}],
    )
    db_session.add(collection)
    await db_session.commit()

    msg = make_private_message(291, "/daily_digest", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_daily_digest(msg)
    assert "Подборок пока нет" in msg.sent[0]


async def test_cmd_stats_reports_counts_and_top_tags(db_session):
    link = Link(
        url="https://a.com",
        normalized_url="a.com",
        url_hash="h-stats",
        title="A",
        status=LinkStatus.done,
    )
    db_session.add(link)
    await db_session.flush()
    tag = Tag(name="ai", slug="ai")
    db_session.add(tag)
    await db_session.flush()
    db_session.add(LinkTag(link_id=link.id, tag_id=tag.id))
    await db_session.commit()

    msg = make_private_message(30, "/stats", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_stats(msg)
    assert "Всего ссылок в базе: 1" in msg.sent[0]
    assert "ai: 1" in msg.sent[0]


# --- главное меню на кнопках (не команды вводом) ---


async def test_cmd_start_attaches_main_menu(db_session):
    msg = make_private_message(50, "/start", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_start(msg)
    assert msg.sent == [commands_module.START_TEXT]


async def test_cb_stats_replies_and_acknowledges(db_session):
    msg = make_private_message(51, None, sender_id=WHITELISTED_USER_ID)
    cb = make_callback(commands_module.CB_STATS, msg, sender_id=WHITELISTED_USER_ID)
    await commands_module.cb_stats(cb)
    assert "Всего ссылок в базе" in msg.sent[0]
    assert cb.answered == [None]


async def test_cb_daily_digest_denied_for_non_whitelisted(db_session):
    msg = make_private_message(52, None, sender_id=WHITELISTED_USER_ID)
    cb = make_callback(commands_module.CB_DAILY_DIGEST, msg, sender_id=999999)
    await commands_module.cb_daily_digest(cb)
    assert msg.sent == [NO_ACCESS_TEXT]


async def test_cb_uses_clicking_user_not_bot_message_author(db_session):
    # Регрессия: callback.message.from_user — это бот, а не нажавший кнопку
    # человек. Whitelisted-пользователь жмёт кнопку под сообщением, которое
    # формально "от бота" (id=0, не в whitelist) — доступ всё равно должен быть.
    msg = make_private_message(521, None, sender_id=WHITELISTED_USER_ID)
    cb = make_callback(commands_module.CB_STATS, msg, sender_id=WHITELISTED_USER_ID)
    assert cb.message.from_user.id != WHITELISTED_USER_ID  # бот, не человек

    await commands_module.cb_stats(cb)

    assert "Всего ссылок в базе" in msg.sent[0]
    assert NO_ACCESS_TEXT not in msg.sent


async def test_cb_ask_sets_state_and_prompts(db_session):
    msg = make_private_message(53, None, sender_id=WHITELISTED_USER_ID)
    cb = make_callback(commands_module.CB_ASK, msg, sender_id=WHITELISTED_USER_ID)
    state = make_state(WHITELISTED_USER_ID)

    await commands_module.cb_ask_prompt(cb, state)

    assert "Напишите ваш вопрос" in msg.sent[0]
    assert await state.get_state() == "MenuState:waiting_for_ask"


async def test_ask_button_flow_answers_next_message_as_question(db_session):
    prompt_msg = make_private_message(54, None, sender_id=WHITELISTED_USER_ID)
    cb = make_callback(commands_module.CB_ASK, prompt_msg, sender_id=WHITELISTED_USER_ID)
    state = make_state(WHITELISTED_USER_ID)
    await commands_module.cb_ask_prompt(cb, state)

    follow_up = make_private_message(55, "что там про RAG?", sender_id=WHITELISTED_USER_ID)
    await private_module.handle_private_message(follow_up, state)

    assert len(follow_up.sent) == 1
    assert "Фейковый ответ LLM." in follow_up.sent[0]
    assert await state.get_state() is None  # состояние очищено после обработки


async def test_search_button_flow_answers_next_message_as_topic(db_session):
    link = Link(
        url="https://a.com",
        normalized_url="a.com",
        url_hash="h-search-btn",
        title="Статья про RAG",
        status=LinkStatus.done,
    )
    db_session.add(link)
    await db_session.commit()

    prompt_msg = make_private_message(56, None, sender_id=WHITELISTED_USER_ID)
    cb = make_callback(commands_module.CB_SEARCH, prompt_msg, sender_id=WHITELISTED_USER_ID)
    state = make_state(WHITELISTED_USER_ID)
    await commands_module.cb_search_prompt(cb, state)

    follow_up = make_private_message(57, "RAG", sender_id=WHITELISTED_USER_ID)
    await private_module.handle_private_message(follow_up, state)

    assert '<a href="https://a.com">Статья про RAG</a>' in follow_up.sent[0]
    assert await state.get_state() is None


async def test_private_handler_without_pending_state_falls_back_to_casual_chat(db_session):
    state = make_state(WHITELISTED_USER_ID)
    msg = make_private_message(58, "как дела?", sender_id=WHITELISTED_USER_ID)
    await private_module.handle_private_message(msg, state)
    assert "Фейковый ответ LLM." in msg.sent[0]

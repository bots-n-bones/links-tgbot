from dataclasses import dataclass, field

from sqlalchemy import select

import bot.handlers.commands as commands_module
import bot.handlers.group as group_module
import bot.handlers.private as private_module
from bot.access import INVITE_INVALID_TEXT, INVITE_REDEEMED_TEXT, NO_ACCESS_TEXT, create_invite
from bot.handlers.private import HELP_HINT_TEXT
from db.models import Collection, Link, LinkStatus, LinkTag, RawMessage, SourceType, Tag
from tests.bot.conftest import WHITELISTED_USER_ID


@dataclass
class FakeUser:
    id: int
    username: str | None = None


@dataclass
class FakeChat:
    id: int
    type: str


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
    sent: list[str] = field(default_factory=list)

    async def answer(self, text: str, **kwargs) -> None:
        self.sent.append(text)

    async def reply(self, text: str, **kwargs) -> None:
        self.sent.append(text)


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
    await private_module.handle_private_message(msg)

    assert msg.sent == [NO_ACCESS_TEXT]
    rows = (await db_session.execute(select(RawMessage))).scalars().all()
    assert len(rows) == 0


async def test_private_handler_redeems_valid_invite_code(db_session):
    code = await create_invite(created_by=WHITELISTED_USER_ID)

    msg = make_private_message(14, code, sender_id=42)  # не в whitelist
    await private_module.handle_private_message(msg)
    assert msg.sent == [INVITE_REDEEMED_TEXT]

    # код одноразовый — второй пользователь тем же кодом доступ не получает
    msg2 = make_private_message(15, code, sender_id=43)
    await private_module.handle_private_message(msg2)
    assert msg2.sent == [INVITE_INVALID_TEXT]

    # погасивший код пользователь теперь в whitelist
    msg3 = make_private_message(16, None, sender_id=42)
    await private_module.handle_private_message(msg3)
    assert msg3.sent == [HELP_HINT_TEXT]


async def test_private_handler_rejects_unknown_invite_code(db_session):
    msg = make_private_message(17, "NOPE1234", sender_id=44)
    await private_module.handle_private_message(msg)
    assert msg.sent == [INVITE_INVALID_TEXT]


async def test_private_handler_whitelisted_with_url_ingests(db_session, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(private_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    msg = make_private_message(11, "https://example.com/b", sender_id=WHITELISTED_USER_ID)
    await private_module.handle_private_message(msg)

    assert msg.sent == []  # подтверждение шлёт воркер (Фаза 4), не сразу
    rows = (await db_session.execute(select(RawMessage))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source_type == SourceType.direct
    assert len(enqueued) == 1


async def test_private_handler_whitelisted_no_url_routes_to_qa(db_session):
    # ENV=test (см. tests/bot/conftest.py) => worker.rag использует FakeLLMClient/
    # FakeEmbeddingClient, реальные вызовы OpenAI не выполняются
    msg = make_private_message(12, "а есть что-то про RAG?", sender_id=WHITELISTED_USER_ID)
    await private_module.handle_private_message(msg)
    assert len(msg.sent) == 1
    assert "Фейковый ответ LLM." in msg.sent[0]
    # свободный текст (не /ask) — просто ответ, без списка источников
    assert "Источники" not in msg.sent[0]


async def test_private_handler_whitelisted_no_text_routes_to_help_hint(db_session):
    msg = make_private_message(13, None, sender_id=WHITELISTED_USER_ID)
    await private_module.handle_private_message(msg)
    assert msg.sent == [HELP_HINT_TEXT]


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
    await private_module.handle_private_message(redeem_msg)
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


async def test_cmd_digest_no_collections_yet(db_session):
    msg = make_private_message(28, "/digest", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_digest(msg)
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


async def test_cmd_digest_returns_latest_collection(db_session):
    from datetime import date

    collection = Collection(
        title="Подборка недели",
        theme="ai",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 7),
        summary_md="Главное за неделю: всё хорошо.",
    )
    db_session.add(collection)
    await db_session.commit()

    msg = make_private_message(29, "/digest", sender_id=WHITELISTED_USER_ID)
    await commands_module.cmd_digest(msg)
    assert "Подборка недели" in msg.sent[0]
    assert "Главное за неделю" in msg.sent[0]


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

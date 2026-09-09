import api.main as main_module
from db.models import RawMessage, SourceType


async def test_add_link_manual_enqueues_processing(db_session, authed_client, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(main_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    resp = authed_client.post("/links/add", data={"url": "https://example.com/manual"})

    assert resp.status_code == 200
    assert "Добавлено" in resp.text
    assert len(enqueued) == 1

    row = (await db_session.execute(RawMessage.__table__.select())).mappings().one()
    assert row["source_type"] == SourceType.manual
    assert row["text"] == "https://example.com/manual"


async def test_add_link_manual_rejects_empty_url(db_session, authed_client, monkeypatch):
    enqueued: list[int] = []
    monkeypatch.setattr(main_module, "enqueue_processing", lambda rid: enqueued.append(rid))

    resp = authed_client.post("/links/add", data={"url": "   "})

    assert resp.status_code == 200
    assert "Введите ссылку" in resp.text
    assert enqueued == []


async def test_manual_note_lands_where_a_chat_reply_lands(db_session, authed_client, monkeypatch):
    """Заметка при ручном добавлении идёт в текст сообщения, рядом с URL.

    Это то же поле, в котором живёт реплика из чата, поэтому в каталоге не
    появляется два разных «почему»: карточка читает одно. Побочно заметка
    достаётся LLM (worker передаёт message_text в describe_link), то есть
    объяснение своими словами улучшает автоописание и теги."""
    monkeypatch.setattr(main_module, "enqueue_processing", lambda rid: None)

    resp = authed_client.post(
        "/links/add",
        data={
            "url": "https://example.com/manual",
            "note": "кажется, это заменит нам две тулзы",
        },
    )
    assert resp.status_code == 200

    row = (await db_session.execute(RawMessage.__table__.select())).mappings().one()
    assert row["text"] == "https://example.com/manual\nкажется, это заменит нам две тулзы"
    # Ручное добавление тоже подписано — иначе в каталоге оно безымянное.
    assert row["sender_name"] is not None
    assert row["chat_title"] == "Добавлено вручную"

from starlette.testclient import TestClient

import api.main as main_module
from api.main import app


async def test_add_post_manual_enqueues_processing(db_session, monkeypatch):
    enqueued: list[dict] = []
    monkeypatch.setattr(
        main_module, "enqueue_post_processing", lambda payload, **kw: enqueued.append(payload)
    )

    async def fake_fetch(url):
        from worker.fetcher import PageMeta

        return PageMeta(
            title="Channel post",
            description="Some post text",
            favicon_url=None,
            domain="t.me",
            raw_text="Some post text",
        )

    monkeypatch.setattr(main_module, "fetch_metadata", fake_fetch)

    with TestClient(app) as client:
        resp = client.post("/posts/add", data={"url": "https://t.me/somechannel/42"})

    assert resp.status_code == 200
    assert "Added" in resp.text
    assert len(enqueued) == 1
    payload = enqueued[0]
    assert payload["chat_title"] == "somechannel"
    assert payload["message_id"] == 42
    assert payload["post_url"] == "https://t.me/somechannel/42"
    assert payload["text"] == "Some post text"


async def test_add_post_manual_rejects_invalid_url(db_session, monkeypatch):
    enqueued: list[dict] = []
    monkeypatch.setattr(
        main_module, "enqueue_post_processing", lambda payload, **kw: enqueued.append(payload)
    )

    with TestClient(app) as client:
        resp = client.post("/posts/add", data={"url": "https://example.com/not-a-post"})

    assert resp.status_code == 200
    assert "Enter a public post link" in resp.text
    assert enqueued == []


async def test_add_post_manual_falls_back_when_fetch_fails(db_session, monkeypatch):
    enqueued: list[dict] = []
    monkeypatch.setattr(
        main_module, "enqueue_post_processing", lambda payload, **kw: enqueued.append(payload)
    )

    async def fake_fetch(url):
        from worker.fetcher import FetchError

        raise FetchError("boom")

    monkeypatch.setattr(main_module, "fetch_metadata", fake_fetch)

    with TestClient(app) as client:
        resp = client.post("/posts/add", data={"url": "https://t.me/somechannel/7"})

    assert resp.status_code == 200
    assert "Added" in resp.text
    assert enqueued[0]["text"] is None

from db.models import Post


async def _make_post(db_session, workspace_id: int, **kwargs) -> Post:
    defaults = dict(
        workspace_id=workspace_id,
        chat_id=-100123,
        message_id=1,
        chat_title="Team chat",
        text="hello",
        post_url="https://t.me/c/123/1",
    )
    defaults.update(kwargs)
    post = Post(**defaults)
    db_session.add(post)
    await db_session.commit()
    await db_session.refresh(post)
    return post


async def test_hide_post_removes_it_from_default_list(db_session, workspace_id, authed_client):
    post = await _make_post(db_session, workspace_id)

    resp = authed_client.patch(f"/api/posts/{post.id}/hide", params={"hidden": "true"})
    assert resp.status_code == 200

    list_resp = authed_client.get("/posts")
    assert "Team chat —" not in list_resp.text

    await db_session.refresh(post)
    assert post.is_hidden is True


async def test_hide_post_htmx_request_returns_empty_body(db_session, workspace_id, authed_client):
    post = await _make_post(db_session, workspace_id)

    resp = authed_client.patch(
        f"/api/posts/{post.id}/hide",
        params={"hidden": "true"},
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    assert resp.text == ""


async def test_hide_post_404_for_missing_post(db_session, authed_client):
    resp = authed_client.patch("/api/posts/999999/hide", params={"hidden": "true"})
    assert resp.status_code == 404

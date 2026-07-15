from db.models import Post


async def _make_post(db_session, workspace_id: int, **kwargs) -> Post:
    defaults = dict(
        workspace_id=workspace_id,
        chat_id=-100123,
        message_id=1,
        chat_title="Team chat",
        text="hello",
        post_url="https://t.me/c/123/1",
        summary="A quick note about something useful.",
        area="tech",
    )
    defaults.update(kwargs)
    post = Post(**defaults)
    db_session.add(post)
    await db_session.commit()
    await db_session.refresh(post)
    return post


async def test_posts_page_renders_list(db_session, workspace_id, authed_client):
    await _make_post(db_session, workspace_id)

    resp = authed_client.get("/posts")
    assert resp.status_code == 200
    assert "hello" in resp.text  # текст поста показан приоритетнее summary
    assert 'href="https://t.me/c/123/1"' in resp.text
    assert "Preview post" in resp.text


async def test_posts_page_falls_back_to_summary_without_text(
    db_session, workspace_id, authed_client
):
    await _make_post(db_session, workspace_id, text=None)

    resp = authed_client.get("/posts")
    assert resp.status_code == 200
    assert "A quick note about something useful." in resp.text


async def test_posts_page_preview_uses_iframe_for_public_posts(
    db_session, workspace_id, authed_client
):
    await _make_post(db_session, workspace_id, post_url="https://t.me/somechannel/42")

    resp = authed_client.get("/posts")
    assert '<iframe src="https://t.me/somechannel/42?embed=1"' in resp.text


async def test_posts_page_preview_uses_fallback_card_for_private_posts(
    db_session, workspace_id, authed_client
):
    await _make_post(db_session, workspace_id, post_url="https://t.me/c/123/1")

    resp = authed_client.get("/posts")
    assert "<iframe" not in resp.text
    assert "Open in Telegram" in resp.text


async def test_posts_page_filters_by_area(db_session, workspace_id, authed_client):
    await _make_post(db_session, workspace_id, message_id=2, area="design")
    await _make_post(db_session, workspace_id, message_id=3, area="tech")

    resp = authed_client.get("/posts", params={"area": "design"})
    assert resp.status_code == 200
    data = resp.text
    # только один пост из двух должен попасть в выдачу
    assert data.count(">Team chat<") == 1


async def test_posts_page_empty_state(db_session, authed_client):
    resp = authed_client.get("/posts")
    assert resp.status_code == 200
    assert "No posts yet." in resp.text


async def test_posts_page_filters_by_tag(db_session, workspace_id, authed_client):
    from db.models import PostTag, Tag

    tag = Tag(workspace_id=workspace_id, name="dev", slug="dev")
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)

    tagged = await _make_post(db_session, workspace_id, message_id=10)
    await _make_post(db_session, workspace_id, message_id=11)
    db_session.add(PostTag(post_id=tagged.id, tag_id=tag.id))
    await db_session.commit()

    resp = authed_client.get("/posts", params={"tag": "dev"})
    assert resp.status_code == 200
    assert resp.text.count(">Team chat<") == 1


async def test_posts_page_sorts_by_priority(db_session, workspace_id, authed_client):
    low = await _make_post(db_session, workspace_id, message_id=20)
    high = await _make_post(db_session, workspace_id, message_id=21)
    low.priority_score = 1.0
    high.priority_score = 9.0
    await db_session.commit()

    resp = authed_client.get("/posts", params={"sort": "priority"})
    assert resp.status_code == 200
    assert resp.text.index(f"preview-{high.id}") < resp.text.index(f"preview-{low.id}")

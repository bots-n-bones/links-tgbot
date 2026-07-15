"""Волна 4 плана "Личный кабинет + workspace": данные другого workspace не
должны быть видны и не должны редактироваться через API — эти тесты
специально гоняют authed_client (владелец workspace_id из фикстуры) против
ссылки, которая принадлежит ДРУГОМУ workspace."""

import hashlib

from db.models import Link, LinkStatus, Workspace


async def _make_link(db_session, workspace_id: int, *, url: str) -> Link:
    link = Link(
        workspace_id=workspace_id,
        url=url,
        normalized_url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        title="Foreign link",
        status=LinkStatus.done,
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(link)
    return link


async def test_list_links_excludes_other_workspace(db_session, workspace_id, authed_client):
    other_ws = Workspace(name="Other workspace")
    db_session.add(other_ws)
    await db_session.commit()
    await db_session.refresh(other_ws)

    await _make_link(db_session, workspace_id, url="https://mine.com")
    await _make_link(db_session, other_ws.id, url="https://theirs.com")

    resp = authed_client.get("/api/links")
    urls = {item["url"] for item in resp.json()["items"]}
    assert urls == {"https://mine.com"}


async def test_get_link_detail_404_for_other_workspace_link(
    db_session, workspace_id, authed_client
):
    other_ws = Workspace(name="Other workspace")
    db_session.add(other_ws)
    await db_session.commit()
    await db_session.refresh(other_ws)

    foreign_link = await _make_link(db_session, other_ws.id, url="https://theirs.com")

    resp = authed_client.get(f"/api/links/{foreign_link.id}")
    assert resp.status_code == 404


async def test_update_link_404_for_other_workspace_link(db_session, workspace_id, authed_client):
    other_ws = Workspace(name="Other workspace")
    db_session.add(other_ws)
    await db_session.commit()
    await db_session.refresh(other_ws)

    foreign_link = await _make_link(db_session, other_ws.id, url="https://theirs.com")

    resp = authed_client.patch(
        f"/api/links/{foreign_link.id}", data={"title": "Hijacked", "description": "", "tags": ""}
    )
    assert resp.status_code == 404

    await db_session.refresh(foreign_link)
    assert foreign_link.title == "Foreign link"  # не изменилось

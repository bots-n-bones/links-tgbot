"""Сохранённые виды каталога — набор фильтров под именем."""

from db.models import CatalogView


async def test_saving_a_view_captures_the_current_filters(db_session, workspace_id, authed_client):
    resp = authed_client.post(
        "/api/links/views?mode=all&area=ai&sort=usefulness&page=3",
        data={"name": "что тестировать"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "что тестировать" in resp.text

    view = (await db_session.execute(CatalogView.__table__.select())).mappings().one()
    assert view["name"] == "что тестировать"
    # Страница не сохраняется: вид — это «что показывать», а не «где я
    # остановился».
    assert view["params_json"] == {"mode": "all", "area": "ai", "sort": "usefulness"}


async def test_saving_under_an_existing_name_updates_it(db_session, workspace_id, authed_client):
    """«Сохранить под тем же именем» читается как «обновить», а не как
    ошибка уникальности."""
    authed_client.post(
        "/api/links/views?mode=all&area=ai",
        data={"name": "мой вид"},
        headers={"HX-Request": "true"},
    )
    authed_client.post(
        "/api/links/views?mode=inbox&area=design",
        data={"name": "мой вид"},
        headers={"HX-Request": "true"},
    )

    rows = (await db_session.execute(CatalogView.__table__.select())).mappings().all()
    assert len(rows) == 1
    assert rows[0]["params_json"] == {"mode": "inbox", "area": "design"}


async def test_view_name_cannot_be_blank(db_session, workspace_id, authed_client):
    resp = authed_client.post(
        "/api/links/views?mode=all", data={"name": "   "}, headers={"HX-Request": "true"}
    )
    assert resp.status_code == 422


async def test_view_can_be_deleted(db_session, workspace_id, authed_client):
    authed_client.post(
        "/api/links/views?mode=all", data={"name": "лишний"}, headers={"HX-Request": "true"}
    )
    view = (await db_session.execute(CatalogView.__table__.select())).mappings().one()

    resp = authed_client.delete(f"/api/links/views/{view['id']}", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "лишний" not in resp.text

    rows = (await db_session.execute(CatalogView.__table__.select())).mappings().all()
    assert rows == []


async def test_view_of_another_workspace_is_not_reachable(db_session, workspace_id, authed_client):
    from db.models import Workspace

    other = Workspace(name="Чужая команда")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    foreign = CatalogView(workspace_id=other.id, name="чужой", params_json={"mode": "all"})
    db_session.add(foreign)
    await db_session.commit()
    await db_session.refresh(foreign)

    assert authed_client.delete(f"/api/links/views/{foreign.id}").status_code == 404
    # И в списке своего workspace его тоже не видно.
    assert "чужой" not in authed_client.get("/").text

"""Волна 6: личный watchlist каналов — POST/DELETE /api/account/watchlist."""

from sqlalchemy import select

from db.models import ChannelWatch, User


async def test_add_to_watchlist_creates_row(db_session, workspace_id, authed_client):
    resp = authed_client.post("/api/account/watchlist", json={"channel_username": "@testchannel"})
    assert resp.status_code == 200
    assert resp.json() == {"channel_username": "testchannel"}

    user = await db_session.scalar(select(User).where(User.telegram_id == 900001))
    watches = (
        (await db_session.execute(select(ChannelWatch).where(ChannelWatch.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(watches) == 1
    assert watches[0].channel_username == "testchannel"


async def test_add_to_watchlist_is_idempotent(db_session, workspace_id, authed_client):
    authed_client.post("/api/account/watchlist", json={"channel_username": "testchannel"})
    resp = authed_client.post("/api/account/watchlist", json={"channel_username": "testchannel"})
    assert resp.status_code == 200

    user = await db_session.scalar(select(User).where(User.telegram_id == 900001))
    watches = (
        (await db_session.execute(select(ChannelWatch).where(ChannelWatch.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(watches) == 1  # уникальность (user_id, channel_username), не задублировалось


async def test_add_to_watchlist_rejects_invalid_username(db_session, workspace_id, authed_client):
    resp = authed_client.post("/api/account/watchlist", json={"channel_username": "not valid!"})
    assert resp.status_code == 422


async def test_remove_from_watchlist(db_session, workspace_id, authed_client):
    authed_client.post("/api/account/watchlist", json={"channel_username": "testchannel"})

    resp = authed_client.delete("/api/account/watchlist/testchannel")
    assert resp.status_code == 200

    user = await db_session.scalar(select(User).where(User.telegram_id == 900001))
    watches = (
        (await db_session.execute(select(ChannelWatch).where(ChannelWatch.user_id == user.id)))
        .scalars()
        .all()
    )
    assert watches == []


async def test_remove_from_watchlist_is_a_no_op_when_not_watched(
    db_session, workspace_id, authed_client
):
    resp = authed_client.delete("/api/account/watchlist/neverwatched")
    assert resp.status_code == 200

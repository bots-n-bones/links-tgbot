from sqlalchemy import select

import bot.handlers.invites as invites_module
from bot.access import create_invite
from db.models import Invite, User, Workspace, WorkspaceMember
from tests.bot.test_handlers import FakeChat, FakeMessage, make_callback


async def _make_pending_invite(db_session, target_telegram_id: int) -> int:
    workspace = Workspace(name="Test workspace")
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)

    code = await create_invite(
        created_by=1, workspace_id=workspace.id, target_telegram_id=target_telegram_id
    )
    invite_id = await db_session.scalar(select(Invite.id).where(Invite.code == code))
    return invite_id


async def test_cb_invite_accept_creates_membership(db_session):
    invite_id = await _make_pending_invite(db_session, target_telegram_id=42)
    msg = FakeMessage(chat=FakeChat(id=42, type="private"), from_user=None, message_id=1)
    callback = make_callback(f"invite:accept:{invite_id}", msg, sender_id=42)

    await invites_module.cb_invite_accept(callback)

    invite = await db_session.get(Invite, invite_id)
    await db_session.refresh(invite)
    assert invite.status == "accepted"

    user = await db_session.scalar(select(User).where(User.telegram_id == 42))
    membership = await db_session.scalar(
        select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
    )
    assert membership is not None
    assert "joined" in msg.sent[0].lower()


async def test_cb_invite_accept_rejects_wrong_user(db_session):
    invite_id = await _make_pending_invite(db_session, target_telegram_id=42)
    msg = FakeMessage(chat=FakeChat(id=999, type="private"), from_user=None, message_id=1)
    callback = make_callback(f"invite:accept:{invite_id}", msg, sender_id=999)

    await invites_module.cb_invite_accept(callback)

    invite = await db_session.get(Invite, invite_id)
    await db_session.refresh(invite)
    assert invite.status == "pending"
    assert callback.answered[0] is not None  # alert about invalid invite


async def test_cb_invite_decline_sets_status(db_session):
    invite_id = await _make_pending_invite(db_session, target_telegram_id=42)
    msg = FakeMessage(chat=FakeChat(id=42, type="private"), from_user=None, message_id=1)
    callback = make_callback(f"invite:decline:{invite_id}", msg, sender_id=42)

    await invites_module.cb_invite_decline(callback)

    invite = await db_session.get(Invite, invite_id)
    await db_session.refresh(invite)
    assert invite.status == "declined"
    assert "declined" in msg.sent[0].lower()

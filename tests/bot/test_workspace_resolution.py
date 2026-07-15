"""Волна 5 плана "Личный кабинет + workspace": резолюция workspace по чату
(WorkspaceChat, /register_chat) для группы, по WorkspaceMember отправителя
для личных сообщений — и /invite, доступный любому owner'у, не только
статическому ADMIN_USER_ID."""

from sqlalchemy import select

import bot.handlers.commands as commands_module
import bot.handlers.group as group_module
from bot.access import (
    get_owned_workspace_id,
    is_whitelisted,
    register_chat,
    resolve_group_chat_workspace_id,
    resolve_ingest_workspace_id,
)
from db.models import RawMessage, User, Workspace, WorkspaceMember, WorkspaceRole
from tests.bot.test_handlers import make_group_message, make_private_message


async def _make_owner(db_session, telegram_id: int, workspace: Workspace) -> User:
    user = User(telegram_id=telegram_id)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    await db_session.commit()
    return user


async def test_unregistered_group_chat_falls_back_to_default_workspace(
    db_session, _default_workspace
):
    workspace_id = await resolve_ingest_workspace_id(chat_id=-100999, is_group=True)
    assert workspace_id == _default_workspace.id


async def test_register_chat_binds_chat_to_owned_workspace(db_session, _default_workspace):
    other_workspace = Workspace(name="Other workspace")
    db_session.add(other_workspace)
    await db_session.commit()
    await db_session.refresh(other_workspace)

    await register_chat(other_workspace.id, chat_id=-100555)

    assert await resolve_group_chat_workspace_id(-100555) == other_workspace.id
    workspace_id = await resolve_ingest_workspace_id(chat_id=-100555, is_group=True)
    assert workspace_id == other_workspace.id
    # незарегистрированный чат по-прежнему падает в дефолтный
    assert (
        await resolve_ingest_workspace_id(chat_id=-100556, is_group=True) == _default_workspace.id
    )


async def test_register_chat_command_requires_ownership(db_session, _default_workspace):
    msg = make_group_message(1, "/register_chat", sender_id=555)  # не владелец
    await commands_module.cmd_register_chat(msg)
    assert msg.sent == ["Привязать чат к workspace может только его владелец."]


async def test_register_chat_command_succeeds_for_owner(db_session, _default_workspace):
    workspace = Workspace(name="Team workspace")
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)
    await _make_owner(db_session, 777, workspace)

    msg = make_group_message(2, "/register_chat", sender_id=777)
    await commands_module.cmd_register_chat(msg)

    assert msg.sent == ["Готово — этот чат привязан к вашему workspace."]
    assert await resolve_group_chat_workspace_id(msg.chat.id) == workspace.id


async def test_register_chat_command_rejected_in_private_chat(db_session, _default_workspace):
    msg = make_private_message(3, "/register_chat", sender_id=777)
    await commands_module.cmd_register_chat(msg)
    assert msg.sent == ["Эта команда работает только в групповых чатах."]


async def test_group_message_link_lands_in_registered_workspace(
    db_session, _default_workspace, monkeypatch
):
    team_workspace = Workspace(name="Team workspace")
    db_session.add(team_workspace)
    await db_session.commit()
    await db_session.refresh(team_workspace)

    msg = make_group_message(10, "https://example.com/registered-chat-test")
    await register_chat(team_workspace.id, msg.chat.id)

    monkeypatch.setattr(group_module, "enqueue_processing", lambda rid: None)
    await group_module.handle_group_message(msg)

    row = (await db_session.execute(select(RawMessage))).scalars().one()
    assert row.workspace_id == team_workspace.id


async def test_invite_available_to_any_workspace_owner_not_just_static_admin(
    db_session, _default_workspace
):
    workspace = Workspace(name="Team workspace")
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)
    await _make_owner(db_session, 42, workspace)

    # 42 не является ADMIN_USER_ID/ALLOWED_USER_IDS, но владеет workspace
    msg = make_private_message(20, "/invite", sender_id=42)
    await commands_module.cmd_invite(msg)

    assert len(msg.sent) == 1
    assert "Инвайт-код:" in msg.sent[0]


async def test_is_whitelisted_true_for_workspace_member_without_static_whitelist(
    db_session, _default_workspace
):
    user = User(telegram_id=321)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(WorkspaceMember(workspace_id=_default_workspace.id, user_id=user.id))
    await db_session.commit()

    assert await is_whitelisted(321) is True


async def test_is_whitelisted_false_without_workspace_membership_or_static_whitelist(
    db_session, _default_workspace
):
    assert await is_whitelisted(999999) is False


async def test_get_owned_workspace_id_none_for_member_role(db_session, _default_workspace):
    user = User(telegram_id=654)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(
            workspace_id=_default_workspace.id, user_id=user.id, role=WorkspaceRole.member
        )
    )
    await db_session.commit()

    assert await get_owned_workspace_id(654) is None

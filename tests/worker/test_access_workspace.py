from sqlalchemy import select

from bot.access import create_invite, get_owned_workspace_id, redeem_invite
from db.models import User, Workspace, WorkspaceMember, WorkspaceRole


async def _make_workspace(db_session, name="Test workspace") -> Workspace:
    workspace = Workspace(name=name)
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)
    return workspace


async def test_redeem_invite_creates_workspace_membership(db_session):
    workspace = await _make_workspace(db_session)
    code = await create_invite(created_by=1, workspace_id=workspace.id)

    ok = await redeem_invite(user_id=999, code=code)
    assert ok is True

    user = await db_session.scalar(select(User).where(User.telegram_id == 999))
    assert user is not None
    membership = await db_session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id
        )
    )
    assert membership is not None
    assert membership.role == WorkspaceRole.member


async def test_redeem_invite_does_not_duplicate_existing_membership(db_session):
    workspace = await _make_workspace(db_session)
    user = User(telegram_id=999)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    await db_session.commit()

    code = await create_invite(created_by=1, workspace_id=workspace.id)
    ok = await redeem_invite(user_id=999, code=code)
    assert ok is True

    memberships = (
        (
            await db_session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(memberships) == 1
    assert memberships[0].role == WorkspaceRole.owner  # не перезаписан на member


async def test_get_owned_workspace_id_returns_owned_workspace(db_session):
    workspace = await _make_workspace(db_session)
    user = User(telegram_id=555)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    await db_session.commit()

    result = await get_owned_workspace_id(555)
    assert result == workspace.id


async def test_get_owned_workspace_id_returns_none_for_non_owner(db_session):
    workspace = await _make_workspace(db_session)
    user = User(telegram_id=556)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.member)
    )
    await db_session.commit()

    result = await get_owned_workspace_id(556)
    assert result is None


async def test_get_owned_workspace_id_returns_none_for_unknown_user(db_session):
    result = await get_owned_workspace_id(999999)
    assert result is None

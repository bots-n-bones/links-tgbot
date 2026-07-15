import pytest
from sqlalchemy.exc import IntegrityError

from db.models import User, Workspace, WorkspaceMember, WorkspaceRole


async def _make_workspace(db_session, name="Test workspace") -> Workspace:
    workspace = Workspace(name=name)
    db_session.add(workspace)
    await db_session.commit()
    await db_session.refresh(workspace)
    return workspace


async def _make_user(db_session, telegram_id=1) -> User:
    user = User(telegram_id=telegram_id)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def test_workspace_defaults_to_free_plan(db_session):
    workspace = await _make_workspace(db_session)
    assert workspace.plan == "free"


async def test_workspace_member_defaults_to_member_role(db_session):
    workspace = await _make_workspace(db_session)
    user = await _make_user(db_session)
    member = WorkspaceMember(workspace_id=workspace.id, user_id=user.id)
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    assert member.role == WorkspaceRole.member


async def test_user_telegram_id_is_unique(db_session):
    await _make_user(db_session, telegram_id=42)
    db_session.add(User(telegram_id=42))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_workspace_member_unique_per_workspace_and_user(db_session):
    workspace = await _make_workspace(db_session)
    user = await _make_user(db_session)
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id))
    await db_session.commit()

    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_deleting_workspace_cascades_to_members(db_session):
    from sqlalchemy import select

    workspace = await _make_workspace(db_session)
    user = await _make_user(db_session)
    db_session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    await db_session.commit()

    await db_session.delete(workspace)
    await db_session.commit()

    remaining = (await db_session.execute(select(WorkspaceMember))).scalars().all()
    assert remaining == []


async def test_deleting_user_cascades_to_memberships(db_session):
    from sqlalchemy import select

    workspace = await _make_workspace(db_session)
    user = await _make_user(db_session)
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id))
    await db_session.commit()

    await db_session.delete(user)
    await db_session.commit()

    remaining = (await db_session.execute(select(WorkspaceMember))).scalars().all()
    assert remaining == []

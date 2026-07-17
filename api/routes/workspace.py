"""Создание/переименование команды (личный кабинет v2) — отдельно от
api/routes/account.py, т.к. это про workspace, а не про самого юзера."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from api.deps import get_current_user
from api.templates_env import _TAG_COLOR_VARS
from db.models import Workspace, WorkspaceMember, WorkspaceRole
from db.session import get_sessionmaker

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class WorkspaceIn(BaseModel):
    name: str
    color: str


@router.post("")
async def create_or_update_workspace(request: Request, body: WorkspaceIn):
    user = await get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    name = body.name.strip()[:200]
    if not name:
        raise HTTPException(status_code=422, detail="Name is required")
    if body.color not in _TAG_COLOR_VARS:
        raise HTTPException(status_code=422, detail="Invalid color")

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        membership = await session.scalar(
            select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
        )
        if membership is None:
            # "Create a team" — у юзера ещё нет workspace, эта команда становится его.
            workspace = Workspace(name=name, color=body.color)
            session.add(workspace)
            await session.flush()
            session.add(
                WorkspaceMember(
                    workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner
                )
            )
            await session.commit()
            return {"id": workspace.id, "name": workspace.name, "color": workspace.color}

        if membership.role != WorkspaceRole.owner:
            raise HTTPException(status_code=403, detail="Only the workspace owner can edit it")

        workspace = await session.get(Workspace, membership.workspace_id)
        workspace.name = name
        workspace.color = body.color
        await session.commit()
        return {"id": workspace.id, "name": workspace.name, "color": workspace.color}

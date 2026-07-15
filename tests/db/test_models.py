import pytest
from sqlalchemy.exc import IntegrityError

from db.models import Link, LinkStatus, RawMessage, SourceType


async def test_link_url_hash_unique(db_session, workspace_id):
    db_session.add(
        Link(
            workspace_id=workspace_id,
            url="https://a.com",
            normalized_url="a.com",
            url_hash="hash1",
            status=LinkStatus.done,
        )
    )
    await db_session.commit()

    db_session.add(
        Link(
            workspace_id=workspace_id,
            url="https://a.com/other",
            normalized_url="a.com/other",
            url_hash="hash1",
            status=LinkStatus.done,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_raw_message_chat_message_unique(db_session, workspace_id):
    db_session.add(
        RawMessage(
            workspace_id=workspace_id,
            chat_id=1,
            message_id=1,
            source_type=SourceType.group,
            text="hi",
        )
    )
    await db_session.commit()

    db_session.add(
        RawMessage(
            workspace_id=workspace_id,
            chat_id=1,
            message_id=1,
            source_type=SourceType.group,
            text="dup",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_raw_message_different_chat_allowed(db_session, workspace_id):
    db_session.add(
        RawMessage(
            workspace_id=workspace_id,
            chat_id=1,
            message_id=1,
            source_type=SourceType.group,
            text="a",
        )
    )
    db_session.add(
        RawMessage(
            workspace_id=workspace_id,
            chat_id=2,
            message_id=1,
            source_type=SourceType.group,
            text="b",
        )
    )
    await db_session.commit()

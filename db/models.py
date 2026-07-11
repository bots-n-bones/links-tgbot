import enum
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class LinkStatus(str, enum.Enum):
    pending = "pending"
    fetching = "fetching"
    processing = "processing"
    done = "done"
    failed = "failed"
    fetch_failed = "fetch_failed"


class SourceType(str, enum.Enum):
    group = "group"
    direct = "direct"
    manual = "manual"  # добавлено вручную через дашборд, не через бота


class Link(Base):
    __tablename__ = "links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    area: Mapped[str | None] = mapped_column(
        String(50)
    )  # coarse category, see worker/llm.AREA_CHOICES
    # GPT-рубрика 0-10 (depth 0-4 + novelty 0-3 + actionability 0-3), см.
    # worker/llm.UsefulnessScore. usefulness_breakdown хранит компоненты для
    # тултипа на дашборде — "как посчитана оценка".
    usefulness_score: Mapped[float | None] = mapped_column()
    usefulness_breakdown: Mapped[dict | None] = mapped_column(JSONB)
    domain: Mapped[str | None] = mapped_column(String(255))
    favicon_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[LinkStatus] = mapped_column(
        Enum(LinkStatus, name="link_status"), default=LinkStatus.pending
    )
    fetch_error: Mapped[str | None] = mapped_column(Text)
    source_count: Mapped[int] = mapped_column(Integer, default=1)
    unique_senders: Mapped[int] = mapped_column(Integer, default=1)
    priority_score: Mapped[float] = mapped_column(default=0)
    click_count: Mapped[int] = mapped_column(Integer, default=0)  # переходов по ссылке с дашборда
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sources: Mapped[list["LinkSource"]] = relationship(
        back_populates="link", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(secondary="link_tags", back_populates="links")


class LinkSource(Base):
    __tablename__ = "link_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("links.id"))
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    chat_title: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    sender_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_name: Mapped[str | None] = mapped_column(Text)
    message_text: Mapped[str | None] = mapped_column(Text)
    reply_to_text: Mapped[str | None] = mapped_column(Text)
    forwarded_from: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    link: Mapped["Link"] = relationship(back_populates="sources")


class RawMessage(Base):
    __tablename__ = "raw_messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "message_id", name="uq_raw_messages_chat_message"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_id: Mapped[int | None] = mapped_column(BigInteger)
    text: Mapped[str | None] = mapped_column(Text)
    entities_json: Mapped[dict | None] = mapped_column(JSONB)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type"), nullable=False
    )
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    links: Mapped[list["Link"]] = relationship(secondary="link_tags", back_populates="tags")
    posts: Mapped[list["Post"]] = relationship(secondary="post_tags", back_populates="tags")


class LinkTag(Base):
    __tablename__ = "link_tags"

    link_id: Mapped[int] = mapped_column(ForeignKey("links.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class Post(Base):
    """Каждое сообщение из отслеживаемых групп (F: вкладка Posts) — со
    ссылками или без. Если в посте были ссылки, они всё равно уходят по
    обычному пайплайну в links; тут хранится сам пост как отдельная единица."""

    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("chat_id", "message_id", name="uq_posts_chat_message"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_title: Mapped[str | None] = mapped_column(Text)
    sender_id: Mapped[int | None] = mapped_column(BigInteger)
    sender_name: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    # Публичная ссылка на оригинальный пост в канале (если это форвард из
    # публичного канала) — иначе внутренний deep-link t.me/c/... для участников.
    post_url: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    area: Mapped[str | None] = mapped_column(String(50))
    photo_url: Mapped[str | None] = mapped_column(Text)
    link_ids: Mapped[list | None] = mapped_column(JSONB)
    # Тот же recency-decay из worker/priority.py, что и у Link.priority_score
    # (source_count=unique_senders=1 — у поста нет концепции повторных
    # источников), пересчитывается той же ежедневной beat-задачей.
    priority_score: Mapped[float] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tags: Mapped[list["Tag"]] = relationship(secondary="post_tags", back_populates="posts")


class PostTag(Base):
    __tablename__ = "post_tags"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class TagSynonym(Base):
    __tablename__ = "tag_synonyms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_value: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    canonical_tag: Mapped[str] = mapped_column(String(100), nullable=False)


class ResearchReport(Base):
    __tablename__ = "research_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("links.id"))
    topic: Mapped[str | None] = mapped_column(Text)
    report_md: Mapped[str] = mapped_column(Text, nullable=False)
    sources_json: Mapped[dict | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(50))
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    theme: Mapped[str | None] = mapped_column(String(100))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False)
    link_ids: Mapped[list | None] = mapped_column(JSONB)
    # Внешние статьи, найденные веб-поиском для daily/weekly digest (не наши
    # сохранённые ссылки) — [{"title": str, "url": str, "description": str}, ...]
    articles: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    redeemed_by: Mapped[int | None] = mapped_column(BigInteger)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthorizedUser(Base):
    __tablename__ = "authorized_users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    invite_code: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QALog(Base):
    __tablename__ = "qa_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_md: Mapped[str] = mapped_column(Text, nullable=False)
    matched_link_ids: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

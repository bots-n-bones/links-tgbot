"""CSV/MD export для результатов Channel Parser (шаг 3 wizard'а)."""

from api.export import _to_csv, _to_markdown
from db.models import ChannelParsedPost

CHANNEL_POST_COLUMNS = [
    "post_url",
    "published_at",
    "text",
    "views",
    "reactions_total",
    "comments_count",
    "word_count",
    "is_forward",
    "has_media",
]


def _channel_post_row(post: ChannelParsedPost) -> dict:
    return {
        "post_url": post.post_url,
        "published_at": post.published_at.isoformat() if post.published_at else "",
        "text": post.text or "",
        "views": post.views if post.views is not None else "",
        "reactions_total": post.reactions_total if post.reactions_total is not None else "",
        "comments_count": post.comments_count if post.comments_count is not None else "",
        "word_count": post.word_count if post.word_count is not None else "",
        "is_forward": post.is_forward,
        "has_media": post.has_media,
    }


def channel_posts_to_csv(posts: list[ChannelParsedPost]) -> str:
    return _to_csv(CHANNEL_POST_COLUMNS, [_channel_post_row(post) for post in posts])


def channel_posts_to_markdown(posts: list[ChannelParsedPost]) -> str:
    return _to_markdown(CHANNEL_POST_COLUMNS, [_channel_post_row(post) for post in posts])

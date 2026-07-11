"""CSV/MD export для страниц Links и Posts (кнопка "Download all data")."""

import csv
import io

from db.models import Link, Post

LINK_COLUMNS = [
    "id",
    "title",
    "url",
    "description",
    "area",
    "tags",
    "usefulness_score",
    "click_count",
    "priority_score",
    "created_at",
]

POST_COLUMNS = [
    "id",
    "post_url",
    "chat_title",
    "text",
    "summary",
    "area",
    "tags",
    "link_ids",
    "created_at",
]


def _link_row(link: Link) -> dict:
    return {
        "id": link.id,
        "title": link.title or "",
        "url": link.url,
        "description": link.description or "",
        "area": link.area or "",
        "tags": ", ".join(t.name for t in link.tags),
        "usefulness_score": link.usefulness_score if link.usefulness_score is not None else "",
        "click_count": link.click_count,
        "priority_score": link.priority_score,
        "created_at": link.created_at.isoformat() if link.created_at else "",
    }


def _post_row(post: Post) -> dict:
    return {
        "id": post.id,
        "post_url": post.post_url or "",
        "chat_title": post.chat_title or "",
        "text": post.text or "",
        "summary": post.summary or "",
        "area": post.area or "",
        "tags": ", ".join(t.name for t in post.tags),
        "link_ids": ", ".join(str(i) for i in (post.link_ids or [])),
        "created_at": post.created_at.isoformat() if post.created_at else "",
    }


def _to_csv(columns: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _md_escape(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _to_markdown(columns: list[str], rows: list[dict]) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md_escape(row[c]) for c in columns) + " |")
    return "\n".join(lines) + "\n"


def links_to_csv(links: list[Link]) -> str:
    return _to_csv(LINK_COLUMNS, [_link_row(link) for link in links])


def links_to_markdown(links: list[Link]) -> str:
    return _to_markdown(LINK_COLUMNS, [_link_row(link) for link in links])


def posts_to_csv(posts: list[Post]) -> str:
    return _to_csv(POST_COLUMNS, [_post_row(post) for post in posts])


def posts_to_markdown(posts: list[Post]) -> str:
    return _to_markdown(POST_COLUMNS, [_post_row(post) for post in posts])

from bot.formatting import format_link_list_html, format_qa_reply_html
from db.models import Link, LinkStatus
from worker.rag import MatchedLink, QAResult


def _link(url: str, title: str | None) -> Link:
    return Link(url=url, normalized_url=url, url_hash=url, title=title, status=LinkStatus.done)


def test_format_qa_reply_html_wraps_title_as_link():
    result = QAResult(
        question="q",
        answer="Ответ",
        matched_links=[
            MatchedLink(
                id=1,
                url="https://a.com",
                title="Статья про RAG",
                description=None,
                source_count=3,
                unique_senders=2,
            )
        ],
    )
    text = format_qa_reply_html(result)
    assert '<a href="https://a.com">Статья про RAG</a>' in text
    assert "https://a.com)" not in text  # старый формат "title (url)" не используется


def test_format_qa_reply_html_escapes_title_and_answer():
    result = QAResult(
        question="q",
        answer="<script>alert(1)</script>",
        matched_links=[
            MatchedLink(
                id=1,
                url="https://a.com",
                title="<b>жирный</b> заголовок",
                description=None,
                source_count=1,
                unique_senders=1,
            )
        ],
    )
    text = format_qa_reply_html(result)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "<b>жирный</b>" not in text
    assert "&lt;b&gt;жирный&lt;/b&gt;" in text


def test_format_qa_reply_html_falls_back_to_url_without_title():
    result = QAResult(
        question="q",
        answer="Ответ",
        matched_links=[
            MatchedLink(
                id=1,
                url="https://a.com",
                title=None,
                description=None,
                source_count=1,
                unique_senders=1,
            )
        ],
    )
    text = format_qa_reply_html(result)
    assert '<a href="https://a.com">https://a.com</a>' in text


def test_format_qa_reply_html_converts_markdown_links_in_answer_text():
    # Модель сама пишет markdown-ссылки в тексте ответа — их нужно превратить
    # в кликабельные <a>, а не просто экранировать как текст (баг F-подборка).
    answer = (
        "Дела идут хорошо! Вот полезная ссылка:\n"
        "1. [Tactiq AI для перевода встреч](https://tactiq.io/translate/russian-translate) "
        "— инструмент для перевода (популярность: 1)"
    )
    result = QAResult(question="q", answer=answer, matched_links=[])
    text = format_qa_reply_html(result)
    expected = (
        '<a href="https://tactiq.io/translate/russian-translate">'
        "Tactiq AI для перевода встреч</a>"
    )
    assert expected in text
    assert "[Tactiq AI" not in text
    assert "](https://tactiq.io" not in text


def test_format_link_list_html_wraps_titles():
    links = [_link("https://a.com", "Статья A"), _link("https://b.com", None)]
    text = format_link_list_html(links)
    assert '<a href="https://a.com">Статья A</a>' in text
    assert '<a href="https://b.com">https://b.com</a>' in text

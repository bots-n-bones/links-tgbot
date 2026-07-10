from dataclasses import dataclass, field

from bot.extractors import extract_urls


@dataclass
class FakeEntity:
    type: str
    offset: int = 0
    length: int = 0
    url: str | None = None


@dataclass
class FakeMessage:
    text: str | None = None
    caption: str | None = None
    entities: list | None = field(default_factory=list)
    caption_entities: list | None = field(default_factory=list)


def test_extracts_from_url_entity():
    text = "смотрите https://example.com/a вот тут"
    offset = text.index("https://")
    length = len("https://example.com/a")
    msg = FakeMessage(text=text, entities=[FakeEntity(type="url", offset=offset, length=length)])
    assert extract_urls(msg) == ["https://example.com/a"]


def test_extracts_from_text_link_entity():
    text = "полезная статья"
    msg = FakeMessage(
        text=text,
        entities=[FakeEntity(type="text_link", url="https://example.com/hidden")],
    )
    assert extract_urls(msg) == ["https://example.com/hidden"]


def test_regex_fallback_no_entities():
    msg = FakeMessage(text="гляньте www.example.com/page и всё")
    assert extract_urls(msg) == ["www.example.com/page"]


def test_extracts_from_caption():
    msg = FakeMessage(caption="фото отсюда https://example.com/photo")
    assert extract_urls(msg) == ["https://example.com/photo"]


def test_multiple_urls_deduped_and_ordered():
    text = "https://a.com и https://b.com и снова https://a.com"
    msg = FakeMessage(text=text)
    assert extract_urls(msg) == ["https://a.com", "https://b.com"]


def test_no_url_returns_empty():
    msg = FakeMessage(text="просто текст без ссылок")
    assert extract_urls(msg) == []


def test_forwarded_message_content_extracted_same_way():
    # Telegram кладёт переслан. текст в text/entities как обычно —
    # extractor не требует специальной обработки forward-метаданных.
    msg = FakeMessage(text="переслано: https://example.com/forwarded")
    assert extract_urls(msg) == ["https://example.com/forwarded"]


def test_url_trailing_punctuation_stripped_by_regex():
    msg = FakeMessage(text="статья тут: https://example.com/a.")
    assert extract_urls(msg) == ["https://example.com/a"]

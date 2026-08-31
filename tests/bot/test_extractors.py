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


def _utf16_offset(text: str, substring: str) -> int:
    """Telegram-style offset — в UTF-16 code units, не в Python-символах."""
    idx = text.index(substring)
    return len(text[:idx].encode("utf-16-le")) // 2


def test_url_entity_offset_correct_with_astral_emoji_before_it():
    """Регресс: astral-эмодзи (🗣🎼💥 и т.п.) занимают 2 UTF-16 code units, но
    1 Python-символ — сырой text[offset:offset+length] на реальном
    production-сообщении уезжал вперёд и прихватывал "\\n\\n@cgevent" в конец
    URL, из-за чего httpx падал с InvalidURL и валил всю Celery-задачу."""
    text = (
        "На входе звук, на выходе:\n🗣 Dialogue\n🎼 Music\n💥 SFX\n\n"
        "Всё в WAV.\n\nhttps://github.com/wassermanproductions/stem-studio\n\n@cgevent"
    )
    url = "https://github.com/wassermanproductions/stem-studio"
    offset = _utf16_offset(text, url)
    msg = FakeMessage(text=text, entities=[FakeEntity(type="url", offset=offset, length=len(url))])
    assert extract_urls(msg) == [url]


def test_url_entity_offset_correct_with_multiple_astral_emoji_and_custom_emoji():
    text = "👋 Заголовок\n\n▶️ Смотри тут: \nhttps://youtu.be/KctaE734Z3c\n\nещё текст"
    url = "https://youtu.be/KctaE734Z3c"
    offset = _utf16_offset(text, url)
    msg = FakeMessage(text=text, entities=[FakeEntity(type="url", offset=offset, length=len(url))])
    assert extract_urls(msg) == [url]

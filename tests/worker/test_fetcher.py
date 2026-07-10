import httpx
import pytest
import respx

from worker.fetcher import FetchError, fetch_metadata

HTML = """
<html>
<head>
  <title>Заголовок страницы</title>
  <meta property="og:description" content="Описание для og" />
  <link rel="icon" href="/favicon.ico" />
</head>
<body>
  <script>var x = 1;</script>
  <p>Полезный текст статьи.</p>
</body>
</html>
"""


@respx.mock
async def test_fetch_metadata_success():
    respx.get("https://example.com/a").mock(return_value=httpx.Response(200, text=HTML))

    meta = await fetch_metadata("https://example.com/a")

    assert meta.title == "Заголовок страницы"
    assert meta.description == "Описание для og"
    assert meta.favicon_url == "https://example.com/favicon.ico"
    assert meta.domain == "example.com"
    assert "Полезный текст статьи." in meta.raw_text
    assert "var x = 1" not in meta.raw_text  # script вырезан


@respx.mock
async def test_fetch_metadata_403_raises_fetch_error():
    respx.get("https://example.com/forbidden").mock(return_value=httpx.Response(403))

    with pytest.raises(FetchError):
        await fetch_metadata("https://example.com/forbidden")


@respx.mock
async def test_fetch_metadata_timeout_raises_fetch_error():
    respx.get("https://example.com/slow").mock(side_effect=httpx.TimeoutException("timed out"))

    with pytest.raises(FetchError):
        await fetch_metadata("https://example.com/slow")


@respx.mock
async def test_fetch_metadata_truncates_text_to_limit():
    long_text = "слово " * 2000
    respx.get("https://example.com/long").mock(
        return_value=httpx.Response(200, text=f"<html><body><p>{long_text}</p></body></html>")
    )

    meta = await fetch_metadata("https://example.com/long", text_limit=100)

    assert len(meta.raw_text) <= 100


@respx.mock
async def test_fetch_metadata_missing_meta_returns_none_fields():
    respx.get("https://example.com/bare").mock(
        return_value=httpx.Response(200, text="<html><body><p>Просто текст</p></body></html>")
    )

    meta = await fetch_metadata("https://example.com/bare")

    assert meta.title is None
    assert meta.description is None
    assert meta.favicon_url == "https://example.com/favicon.ico"  # дефолтный путь

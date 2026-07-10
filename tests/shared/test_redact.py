from shared.redact import redact_text, redact_url_tokens


def test_redacts_known_token_params():
    url = "https://example.com/a?token=secret123&id=5"
    assert redact_url_tokens(url) == "https://example.com/a?token=%2A%2A%2A&id=5"


def test_redacts_api_key_param():
    url = "https://example.com/a?api_key=abcdef"
    result = redact_url_tokens(url)
    assert "abcdef" not in result
    assert "api_key=%2A%2A%2A" in result  # '***' процент-кодируется в query string


def test_leaves_non_token_params_untouched():
    url = "https://example.com/a?id=5&page=2"
    assert redact_url_tokens(url) == url


def test_url_without_query_unchanged():
    url = "https://example.com/a"
    assert redact_url_tokens(url) == url


def test_redact_text_masks_urls_with_tokens_in_free_text():
    text = "fetch failed for https://example.com/a?token=abc123: 403 Forbidden"
    result = redact_text(text)
    assert "abc123" not in result
    assert "fetch failed for" in result
    assert "403 Forbidden" in result


def test_redact_text_no_urls_unchanged():
    text = "просто текст без ссылок"
    assert redact_text(text) == text

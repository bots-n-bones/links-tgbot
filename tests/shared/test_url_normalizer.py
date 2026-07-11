from shared.url_normalizer import is_telegram_link, normalize_url, url_hash


def test_lowercases_scheme_and_host():
    assert normalize_url("HTTPS://Example.COM/Path") == "https://example.com/Path"


def test_strips_trailing_slash():
    assert normalize_url("https://example.com/path/") == "https://example.com/path"


def test_keeps_root_slash():
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_strips_utm_params():
    url = "https://example.com/a?utm_source=tg&utm_medium=chat&id=5"
    assert normalize_url(url) == "https://example.com/a?id=5"


def test_strips_fbclid():
    url = "https://example.com/a?fbclid=abc123&id=5"
    assert normalize_url(url) == "https://example.com/a?id=5"


def test_sorts_remaining_query_params():
    url = "https://example.com/a?z=1&a=2"
    assert normalize_url(url) == "https://example.com/a?a=2&z=1"


def test_strips_fragment():
    assert normalize_url("https://example.com/a#section") == "https://example.com/a"


def test_strips_default_https_port():
    assert normalize_url("https://example.com:443/a") == "https://example.com/a"


def test_adds_scheme_if_missing():
    assert normalize_url("example.com/a") == "https://example.com/a"


def test_equivalent_urls_produce_same_hash():
    a = normalize_url("https://Example.com/a/?utm_source=x")
    b = normalize_url("https://example.com/a?utm_campaign=y")
    assert a == b
    assert url_hash(a) == url_hash(b)


def test_different_paths_produce_different_hash():
    a = url_hash(normalize_url("https://example.com/a"))
    b = url_hash(normalize_url("https://example.com/b"))
    assert a != b


def test_url_hash_is_sha256_hex():
    h = url_hash("https://example.com/a")
    assert len(h) == 64
    int(h, 16)  # не бросает ValueError


def test_is_telegram_link_true_for_t_me():
    assert is_telegram_link("https://t.me/some_channel/123")
    assert is_telegram_link("t.me/+abc123")
    assert is_telegram_link("https://telegram.me/some_channel")
    assert is_telegram_link("https://www.t.me/some_channel")


def test_is_telegram_link_false_for_other_domains():
    assert not is_telegram_link("https://example.com/a")
    assert not is_telegram_link("https://telegra.ph/some-article")

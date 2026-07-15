import hashlib
import hmac
import time

from shared.telegram_auth import verify_telegram_login

BOT_TOKEN = "123456:test-bot-token"


def _sign(payload: dict, bot_token: str = BOT_TOKEN) -> dict:
    data_check_string = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    signed = dict(payload)
    signed["hash"] = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return signed


def _payload(**overrides) -> dict:
    base = {
        "id": "12345",
        "first_name": "Test",
        "username": "testuser",
        "auth_date": str(int(time.time())),
    }
    base.update(overrides)
    return base


def test_valid_signature_passes():
    signed = _sign(_payload())
    assert verify_telegram_login(signed, BOT_TOKEN) is True


def test_tampered_field_fails():
    signed = _sign(_payload())
    signed["id"] = "99999"
    assert verify_telegram_login(signed, BOT_TOKEN) is False


def test_wrong_bot_token_fails():
    signed = _sign(_payload(), bot_token="other-token")
    assert verify_telegram_login(signed, BOT_TOKEN) is False


def test_missing_hash_fails():
    payload = _payload()
    assert verify_telegram_login(payload, BOT_TOKEN) is False


def test_stale_auth_date_fails():
    stale = _sign(_payload(auth_date=str(int(time.time()) - 90000)))
    assert verify_telegram_login(stale, BOT_TOKEN) is False


def test_missing_auth_date_fails():
    payload = {"id": "12345", "first_name": "Test"}
    signed = _sign(payload)
    assert verify_telegram_login(signed, BOT_TOKEN) is False

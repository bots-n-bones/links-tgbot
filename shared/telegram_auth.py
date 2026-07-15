"""Проверка данных Telegram Login Widget (личный кабинет, см. план
"Личный кабинет + workspace"). Алгоритм — ровно как в официальной
документации: https://core.telegram.org/widgets/login#checking-authorization
"""

import hashlib
import hmac
import time

AUTH_MAX_AGE_SECONDS = 86400  # сутки — payload с более старым auth_date отклоняем


def verify_telegram_login(data: dict, bot_token: str) -> bool:
    """`data` — query-параметры, которые Telegram кладёт в data-auth-url
    (id, first_name, last_name, username, photo_url, auth_date, hash).
    Мутирует свою копию, оригинал вызывающего кода не трогает."""
    payload = dict(data)
    received_hash = payload.pop("hash", None)
    if not received_hash:
        return False

    auth_date_raw = payload.get("auth_date")
    if not auth_date_raw:
        return False
    try:
        auth_date = int(auth_date_raw)
    except (TypeError, ValueError):
        return False
    if time.time() - auth_date > AUTH_MAX_AGE_SECONDS:
        return False

    data_check_string = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed_hash, received_hash)

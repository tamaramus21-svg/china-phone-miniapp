import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl

from aiogram.types import User


class AuthError(ValueError):
    pass


def validate_init_data(raw, bot_token, max_age=3600, now=None):
    """Telegram token-based HMAC verification. initDataUnsafe is never accepted."""
    try:
        if not raw or len(raw.encode()) > 16_384:
            raise ValueError
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=32)
        fields = dict(pairs)
        if len(fields) != len(pairs) or any("\n" in key or "\r" in key for key in fields):
            raise ValueError
        supplied_hash = fields.pop("hash")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", supplied_hash):
            raise ValueError
        check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, supplied_hash.lower()):
            raise ValueError
        timestamp = int(fields["auth_date"])
        current = time.time() if now is None else now
        if timestamp > current + 30 or current - timestamp > max_age:
            raise ValueError
        user = json.loads(fields["user"])
        if not isinstance(user, dict) or type(user.get("id")) is not int or not 0 < user["id"] < 2**63:
            raise ValueError
        first = user.get("first_name")
        if not isinstance(first, str) or not first.strip() or len(first) > 256:
            raise ValueError
        return User(id=user["id"], is_bot=False, first_name=first,
                    last_name=user.get("last_name"), username=user.get("username"))
    except (ValueError, KeyError, TypeError, OverflowError):
        raise AuthError("Откройте магазин заново через кнопку в Telegram: авторизация отсутствует или истекла.") from None

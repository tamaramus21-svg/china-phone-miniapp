import re

MAX_PRICE = 1_000_000_000
MAX_PHOTOS = 10
MAX_PHOTO_BYTES = 10 * 1024 * 1024


def text(value, limit=100, label="Поле"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} не может быть пустым.")
    value = value.strip()
    if len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"{label}: максимум {limit} символов, без управляющих знаков.")
    return value


def price(value):
    value = str(value).replace(" ", "").replace("\u00a0", "")
    if not re.fullmatch(r"[0-9]{1,10}", value) or not 0 < int(value) <= MAX_PRICE:
        raise ValueError("Цена должна быть целым числом от 1 до 1 000 000 000 сом.")
    return int(value)


def options(value):
    items = [text(x, 32, "Вариант") for x in value.split(",")]
    if not 1 <= len(items) <= 12 or len(set(x.casefold() for x in items)) != len(items):
        raise ValueError("Укажите от 1 до 12 разных вариантов через запятую.")
    if any("|" in x or "=" in x or "\n" in x for x in items):
        raise ValueError("Варианты не должны содержать |, = или перенос строки.")
    return items


def username(value):
    value = value.strip().removeprefix("@")
    if value and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", value):
        raise ValueError("Username: 5–32 латинских символа, цифры и _, начало с буквы. Без ссылки.")
    return value


def stock(value):
    value = value.strip().lower()
    if re.fullmatch(r"[0-9]{1,7}", value):
        qty = int(value)
        return {"availability": "in_stock" if qty else "out", "quantity": qty}
    states = {"в наличии": "in_stock", "под заказ": "preorder", "нет": "out"}
    if value not in states:
        raise ValueError("Введите количество (0–9999999) или: в наличии / под заказ / нет.")
    return {"availability": states[value], "quantity": None}


def variant_prices(value, colors, memories):
    """Memory defaults first, explicit color-memory prices take precedence."""
    if value.strip() == "-":
        return []
    memory_prices, combinations = {}, {}
    for line in value.strip().splitlines():
        if line.count("=") != 1:
            raise ValueError("Формат строки: 256 ГБ = 50000 или Чёрный | 256 ГБ = 51000")
        key, amount = (x.strip() for x in line.split("="))
        amount = price(amount)
        if "|" in key:
            parts = tuple(x.strip() for x in key.split("|"))
            if len(parts) != 2 or parts[0] not in colors or parts[1] not in memories:
                raise ValueError("Цвет или память не совпадают с указанными вариантами.")
            if parts in combinations:
                raise ValueError("Повтор цены комбинации.")
            combinations[parts] = amount
        else:
            if key not in memories or key in memory_prices:
                raise ValueError("Неизвестная или повторная память в ценах.")
            memory_prices[key] = amount
    return [{"color": c, "memory": m, "price": combinations.get((c, m), memory_prices.get(m))}
            for c in colors for m in memories
            if (c, m) in combinations or m in memory_prices]


def validate_product(data):
    result = dict(data)
    for key, limit in {"name": 100, "brand": 40, "model": 60, "short_description": 240,
                       "description": 1600, "specs": 500}.items():
        result[key] = text(data.get(key), limit, key)
    result["price"] = price(data.get("price"))
    for key in ("colors", "memories"):
        if not isinstance(data.get(key), list):
            raise ValueError("Не заданы варианты товара.")
        result[key] = options(",".join(data[key]))
    images = data.get("images", [])
    if not 1 <= len(images) <= MAX_PHOTOS or any(not isinstance(x, str) or not x or len(x) > 512 for x in images):
        raise ValueError("Требуется от 1 до 10 фотографий Telegram.")
    result["images"] = list(images)
    qty = data.get("quantity")
    if qty is not None and (type(qty) is not int or not 0 <= qty <= 9_999_999):
        raise ValueError("Неверное количество.")
    if data.get("availability") not in {"in_stock", "preorder", "out"}:
        raise ValueError("Неверный статус наличия.")
    if qty == 0:
        result["availability"] = "out"
    seen = set()
    result.setdefault("variants", [])
    for v in result.get("variants", []):
        pair = (v["color"], v["memory"])
        if pair in seen or pair[0] not in result["colors"] or pair[1] not in result["memories"]:
            raise ValueError("Неверная комбинация вариантов.")
        price(v["price"])
        seen.add(pair)
    return result

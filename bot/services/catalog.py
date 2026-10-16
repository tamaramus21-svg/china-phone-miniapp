from database.repository import effective_price, ensure_available


def checkout_step(draft, product):
    ensure_available(product)
    if draft["color"] is None:
        return "color", product["colors"]
    if draft["memory"] is None:
        return "memory", product["memories"]
    return "confirm", effective_price(product, draft["color"], draft["memory"])

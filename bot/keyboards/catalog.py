from bot.keyboards.main import keyboard
from utils.formatters import money


def pagination(prefix, page, total):
    row = []
    if page > 0:
        row.append(("⬅️ Назад", f"{prefix}:{page-1}"))
    if (page + 1) * 5 < total:
        row.append(("Вперёд ➡️", f"{prefix}:{page+1}"))
    return [row] if row else []


def catalog_keyboard(products, page, total, admin=False):
    rows = [[(f"{p['name']} · {money(p['min_price'])} сом"[:64], f"{'ap' if admin else 'p'}:{p['id']}")] for p in products]
    rows += pagination("alist" if admin else "cat", page, total)
    if not admin:
        rows += [[("🔎 Поиск", "search"), ("⚙️ Фильтры", "filters")]]
    rows += [[("Сбросить поиск", "aall")], [("◀️ Админ-панель", "admin")]] if admin else [[("🏠 Главное меню", "home")]]
    return keyboard(rows)


def product_keyboard(p):
    rows = []
    if p["availability"] != "out" and p["quantity"] != 0:
        rows.append([("🛒 Заказать", f"buy:{p['id']}")])
    rows += [[("🔄 Обновить карточку", f"refresh:{p['id']}")],
             [("🖼 Фотографии", f"photos:{p['id']}")],
             [("◀️ Назад в каталог", "cat:0")], [("🏠 Главное меню", "home")]]
    return keyboard(rows)

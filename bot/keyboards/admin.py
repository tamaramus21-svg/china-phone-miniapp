from bot.keyboards.main import keyboard
from database.models import STATUSES

FIELDS = {
    "name": "Название", "brand": "Бренд", "model": "Модель",
    "short_description": "Краткое описание", "description": "Полное описание",
    "price": "Базовая цена", "images": "Фотографии", "colors": "Цвета",
    "memories": "Память", "variants": "Цены вариантов", "specs": "Характеристики",
    "stock": "Наличие и количество",
}


def admin_menu():
    return keyboard([
        [("➕ Добавить товар", "aadd")], [("✏️ Редактировать товар", "afind:edit")],
        [("🗑 Удалить товар", "afind:delete")], [("📋 Все товары", "aall")],
        [("📦 Управление наличием", "afind:stock")], [("🧾 Все заказы", "aorders:0")],
        [("🔎 Найти товар по ID", "afind:view")], [("📊 Статистика магазина", "astats")],
        [("⚙️ Настройки магазина", "asettings")], [("🏠 Главное меню", "home")],
    ])


def product_actions(p):
    pid = p["id"]
    rows = [[(f"✏️ {label}", f"ae:{pid}:{key}")] for key, label in FIELDS.items()]
    rows += [[("📄 Все цены вариантов", f"apricelist:{pid}")], [("🖼 Посмотреть карточку с фото", f"p:{pid}")],
             [("🗑 Удалить товар", f"adel:{pid}:{p['revision']}")], [("📋 Все товары", "aall")], [("◀️ Админ-панель", "admin")]]
    return keyboard(rows)


def order_actions(o):
    return keyboard([[(f"📦 Статус: {STATUSES[o['status']]}", f"astatus:{o['id']}")],
                     [("🧾 Все заказы", "aorders:0")]])


def status_keyboard(order_id):
    return keyboard([[(label, f"as:{order_id}:{key}")] for key, label in STATUSES.items()] +
                    [[("◀️ Заказ", f"ao:{order_id}")]])

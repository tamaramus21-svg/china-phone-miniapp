from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton, WebAppInfo


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data=data) for label, data in row] for row in rows])


def main_menu(webapp_url=""):
    if webapp_url:
        pages = [("🛍 Открыть магазин", ""), ("📱 Каталог товаров", "/catalog"),
                 ("🔎 Поиск товара", "/catalog?search=1"), ("📦 Мои заказы", "/orders"),
                 ("ℹ️ О магазине", "/about"), ("📞 Связаться с продавцом", "/contact")]
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=label, web_app=WebAppInfo(url=webapp_url + "/#" + route))] for label, route in pages])
    return keyboard([
        [("🛍 Открыть магазин", "open_shop")], [("📱 Каталог в чате", "cat:0")],
        [("🔎 Поиск товара", "search")], [("📦 Мои заказы", "my:0")],
        [("ℹ️ О магазине", "about")], [("📞 Связаться с продавцом", "contact")],
    ])


def home():
    return keyboard([[("🏠 Главное меню", "home")]])


def cancel():
    return keyboard([[("Отмена", "cancel")]])


def contact_keyboard(username, order_text=None):
    rows = []
    if username:
        url = f"https://t.me/{username}"
        if order_text:
            url += "?text=" + quote(order_text, safe="")
        rows.append([InlineKeyboardButton(text="📞 Связаться с продавцом", url=url)])
    if order_text:
        # Bot API CopyTextButton accepts at most 256 characters. The complete
        # message remains available as a code block for single-copy in clients.
        if len(order_text) <= 256:
            rows.append([InlineKeyboardButton(text="📋 Скопировать заказ", copy_text=CopyTextButton(text=order_text))])
        else:
            rows.append([InlineKeyboardButton(text="📋 Как скопировать заказ", callback_data="copy_help")])
    rows.append([InlineKeyboardButton(text="📦 Мои заказы", callback_data="my:0")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

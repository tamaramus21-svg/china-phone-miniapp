from datetime import datetime, timedelta, timezone
from html import escape

from database.models import AVAILABILITY, STATUSES


def money(value):
    return f"{value:,}".replace(",", " ")


def date(value):
    return datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=6))).strftime("%d.%m.%Y %H:%M")


def product_card(p):
    prices = [v["price"] for v in p["variants"]] or [p["price"]]
    price_label = ("от " if min(prices) != max(prices) else "") + money(min(prices))
    qty = f" · {p['quantity']} шт." if p["quantity"] is not None else ""
    return (f"📱 <b>{escape(p['name'])}</b>\n\n🆔 ID товара: <code>{p['id']}</code>\n"
            f"💰 Цена: <b>{price_label} сом</b>\n"
            f"🏷 {escape(p['brand'])} · {escape(p['model'])}\n\n"
            f"🎨 Цвета: {escape(', '.join(p['colors']))}\n💾 Память: {escape(', '.join(p['memories']))}\n"
            f"📦 Наличие: {AVAILABILITY[p['availability']]}{qty}\n\n"
            f"{escape(p['description'])}\n\n<b>Характеристики</b>\n{escape(p['specs'])}\n\n"
            f"Добавлен: {date(p['created_at'])}\n"
            "Точную цену выбранного варианта покажем до подтверждения.")


def order_message(o):
    return ("Здравствуйте! Хочу заказать товар из вашего магазина.\n\n"
            f"📱 Товар: {o['product_name']}\n🆔 ID товара: {o['product_id']}\n"
            f"🎨 Цвет: {o['color']}\n💾 Память: {o['memory']}\n"
            f"💰 Цена: {money(o['price'])} сом\n🔢 Номер заказа: {o['number']}\n\n"
            "Подскажите, пожалуйста, по наличию и доставке.")


def order_card(o, admin=False):
    buyer = ""
    if admin:
        handle = f" @{escape(o['buyer_username'])}" if o["buyer_username"] else ""
        buyer = f"\nПокупатель: {escape(o['buyer_name'])}{handle}\nTelegram ID: <code>{o['user_id']}</code>\n"
    return (f"🧾 <b>{o['number']}</b>\n{escape(o['product_name'])} · ID {o['product_id']}\n"
            f"🎨 {escape(o['color'])} · 💾 {escape(o['memory'])}\n💰 {money(o['price'])} сом\n"
            f"📦 {STATUSES[o['status']]}\n🕒 {date(o['created_at'])} (UTC+6){buyer}")

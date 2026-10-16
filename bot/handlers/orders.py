from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards.main import keyboard, contact_keyboard
from bot.keyboards.catalog import pagination
from bot.services.catalog import checkout_step
from bot.ui import screen
from utils.formatters import order_message, order_card, money

router = Router(name="orders")


async def show_checkout(callback, repo, token):
    d, p = await repo.checkout(callback.from_user.id, token)
    step, value = checkout_step(d, p)
    if step in {"color", "memory"}:
        label = "🎨 Выберите цвет" if step == "color" else "💾 Выберите память"
        prefix = "oc" if step == "color" else "om"
        rows = [[(v, f"{prefix}:{token}:{i}")] for i, v in enumerate(value)]
        text = f"📱 <b>{escape(p['name'])}</b>\n\n{label}"
    else:
        rows = [[("✅ Подтвердить заказ", f"confirm:{token}")]]
        text = (f"🛒 <b>Подтверждение заказа</b>\n\n📱 {escape(p['name'])}\n🆔 ID товара: {p['id']}\n"
                f"🎨 Цвет: {escape(d['color'])}\n💾 Память: {escape(d['memory'])}\n"
                f"💰 Итоговая цена: <b>{money(value)} сом</b>\n\n"
                "После подтверждения заказ сохранится и будет передан продавцу. "
                "Наличие и доставку согласует продавец.")
    rows.append([("Отмена", f"ocancel:{token}")])
    await screen(callback, text, keyboard(rows))


@router.callback_query(F.data.startswith("buy:"))
async def buy(callback: CallbackQuery, state: FSMContext, repo):
    await state.set_state(None)
    token = await repo.begin_checkout(callback.from_user.id, int(callback.data.split(":")[1]))
    await show_checkout(callback, repo, token)


@router.callback_query(F.data.startswith("oc:"))
@router.callback_query(F.data.startswith("om:"))
async def choose(callback: CallbackQuery, repo):
    prefix, token, index = callback.data.split(":")
    await repo.checkout(callback.from_user.id, token, "color" if prefix == "oc" else "memory", int(index))
    await show_checkout(callback, repo, token)


@router.callback_query(F.data.startswith("ocancel:"))
async def cancel_checkout(callback: CallbackQuery, repo):
    cancelled = await repo.cancel_checkout(callback.from_user.id, callback.data.split(":")[1])
    await screen(callback, "Заказ не оформлен. Выбор отменён." if cancelled else "Этот выбор уже отменён или устарел.",
                 keyboard([[("📱 Каталог", "cat:0")]]))


async def receipt(event, o, repo, config):
    username = await repo.get_setting("admin_username", config.admin_username)
    status = ("Заказ сохранён, ожидает подтверждения продавца." if not o["admin_notified"] else
              "Заказ сохранён. Уведомление передано продавцу; ожидайте подтверждения.")
    msg = order_message(o)
    await screen(event, f"✅ <b>{o['number']}</b>\n{status}\n\n"
                 f"<pre>{escape(msg)}</pre>\n\n"
                 "Скопируйте текст из блока или перешлите это сообщение. "
                 + ("Кнопка откроет чат продавца; если текст не подставился, вставьте его вручную." if username else
                    "Прямая связь появится после настройки username продавца."), contact_keyboard(username, msg))


@router.callback_query(F.data.startswith("confirm:"))
async def confirm(callback: CallbackQuery, repo, config, order_service):
    o, _ = await order_service.confirm(callback.from_user.id, callback.data.split(":")[1])
    await receipt(callback, o, repo, config)


@router.callback_query(F.data.startswith("my:"))
async def my_orders(callback: CallbackQuery, state: FSMContext, repo):
    await state.set_state(None)
    orders, total, page = await repo.orders(callback.from_user.id, int(callback.data.split(":")[1]))
    rows = [[(f"{o['number']} · {o['product_name']}"[:64], f"order:{o['id']}")] for o in orders]
    rows += pagination("my", page, total) + [[("🏠 Главное меню", "home")]]
    text = "📦 <b>Мои заказы</b>\n\n" + ("\n\n".join(order_card(o) for o in orders) if orders else "Вы пока не оформляли заказы.")
    await screen(callback, text, keyboard(rows))


@router.callback_query(F.data.startswith("order:"))
async def order_detail(callback: CallbackQuery, repo, config):
    o = await repo.get_order(callback.from_user.id, int(callback.data.split(":")[1]))
    username = await repo.get_setting("admin_username", config.admin_username)
    msg = order_message(o)
    await screen(callback, order_card(o) + f"\n\n<pre>{escape(msg)}</pre>", contact_keyboard(username, msg))

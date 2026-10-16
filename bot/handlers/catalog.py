from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.keyboards.catalog import catalog_keyboard
from bot.keyboards.main import keyboard, cancel
from bot.ui import screen
from utils.validators import text, price
from utils.formatters import money

router = Router(name="catalog")


class Search(StatesGroup):
    query = State()
    brand = State()
    price_range = State()


async def show_catalog(event, state, repo, page=0):
    await state.set_state(None)
    data = await state.get_data()
    filters = data.get("filters", {})
    products, total, page = await repo.products(page=page, **filters)
    labels = []
    for key, label in (("query", "Поиск"), ("brand", "Бренд"), ("minimum", "Цена от"), ("maximum", "Цена до")):
        if key in filters:
            labels.append(f"{label}: {escape(str(filters[key]))}")
    if filters.get("available"):
        labels.append("Только в наличии")
    heading = "📱 <b>Каталог товаров</b>" + ("\n" + " · ".join(labels) if labels else "")
    if not products:
        body = "Ничего не найдено. Попробуйте изменить поиск или сбросить фильтры." if filters else "Каталог пока пуст. Скоро здесь появятся товары"
    else:
        lines = []
        for p in products:
            prefix = "от " if p["min_price"] != p["max_price"] else ""
            lines.append(f"📱 <b>{escape(p['name'])}</b> · ID {p['id']}\n{escape(p['short_description'])}\n"
                         f"💰 {prefix}{money(p['min_price'])} сом")
        body = f"Страница {page+1} из {(total+4)//5} · Товаров: {total}\n\n" + "\n\n".join(lines)
    await screen(event, heading + "\n\n" + body, catalog_keyboard(products, page, total))


@router.callback_query(F.data.startswith("cat:"))
async def catalog(callback: CallbackQuery, state: FSMContext, repo):
    await show_catalog(callback, state, repo, int(callback.data.split(":")[1]))


@router.callback_query(F.data == "search")
async def search(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Search.query)
    await screen(callback, "🔎 Введите название, бренд или модель (до 100 символов).\nДля отмены: /cancel", cancel())


@router.message(Search.query)
async def query(message: Message, state: FSMContext, repo):
    value = text(message.text, 100, "Поиск")
    data = await state.get_data()
    filters = data.get("filters", {})
    filters["query"] = value
    await state.update_data(filters=filters)
    await show_catalog(message, state, repo)


@router.callback_query(F.data == "filters")
async def filters_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await screen(callback, "⚙️ Фильтры каталога\n\nЦена проверяется по вариантам товара. "
                 "В результатах могут быть и другие варианты с иной ценой.", keyboard([
                     [("🏷 Бренд", "filter:brand")], [("💰 Диапазон цены", "filter:price")],
                     [("📦 Переключить «Только в наличии»", "filter:stock")],
                     [("Сбросить поиск и фильтры", "filter:reset")], [("📱 Показать каталог", "cat:0")]]))


@router.callback_query(F.data.startswith("filter:"))
async def filter_action(callback: CallbackQuery, state: FSMContext, repo):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    filters = data.get("filters", {})
    if action == "brand":
        await state.set_state(Search.brand)
        await screen(callback, "Введите точное название бренда или - для сброса.", cancel())
    elif action == "price":
        await state.set_state(Search.price_range)
        await screen(callback, "Введите минимум и максимум в сомах через пробел, например: 10000 90000.\n"
                     "Для сброса диапазона отправьте -.", cancel())
    elif action in {"stock", "reset"}:
        if action == "reset":
            filters = {}
        else:
            filters["available"] = not filters.get("available", False)
        await state.update_data(filters=filters)
        await show_catalog(callback, state, repo)
    else:
        raise ValueError("Откройте фильтры заново.")


@router.message(Search.brand)
@router.message(Search.price_range)
async def filter_value(message: Message, state: FSMContext, repo):
    value = text(message.text, 100)
    data = await state.get_data()
    filters = data.get("filters", {})
    if await state.get_state() == Search.brand.state:
        if value == "-":
            filters.pop("brand", None)
        else:
            filters["brand"] = text(value, 40, "Бренд")
    elif value == "-":
        filters.pop("minimum", None)
        filters.pop("maximum", None)
    else:
        pieces = value.split()
        if len(pieces) != 2:
            raise ValueError("Введите два целых числа через пробел без разделителей тысяч.")
        low, high = (price(x) for x in pieces)
        if low > high:
            raise ValueError("Минимум не должен превышать максимум.")
        filters.update(minimum=low, maximum=high)
    await state.update_data(filters=filters)
    await show_catalog(message, state, repo)

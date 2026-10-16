import secrets
from html import escape

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, BufferedInputFile

from bot.keyboards.admin import admin_menu, product_actions, FIELDS, status_keyboard, order_actions
from bot.keyboards.catalog import catalog_keyboard, pagination
from bot.keyboards.main import keyboard, cancel
from bot.services.admin_service import AdminService
from bot.ui import screen
from config import ADMIN_ID
from database.models import STATUSES
from database.repository import require_admin, now
from utils import validators as v
from utils.formatters import product_card, order_card, money


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery):
        return event.from_user.id == ADMIN_ID


router = Router(name="admin")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class AdminState(StatesGroup):
    product = State()
    find = State()
    setting = State()


PROMPTS = {
    "name": "Введите название (до 100 символов).",
    "brand": "Введите бренд (до 40 символов).",
    "model": "Введите модель (до 60 символов).",
    "short_description": "Введите краткое описание (до 240 символов).",
    "description": "Введите полное описание (до 1600 символов).",
    "price": "Введите базовую цену в целых сомах (положительное число).\nЦены вариантов задаются отдельно.",
    "images": "Пришлите 1–10 фотографий как фото (не документ), каждая до 10 МБ. "
              "Можно отправить альбом. Затем нажмите «Готово» или /done.\nДобавленные фото можно удалить кнопками ниже.",
    "colors": "Введите доступные цвета через запятую (1–12 вариантов, до 32 символов каждый).",
    "memories": "Введите варианты памяти через запятую (1–12 вариантов, до 32 символов каждый).",
    "variants": "Укажите цены вариантов, каждая строка отдельно:\n<code>256 ГБ = 50000</code>\n"
                "<code>Чёрный | 256 ГБ = 51000</code>\n\nИспользуйте точные названия цвета и памяти. "
                "Цена комбинации важнее цены памяти. Неуказанные варианты используют базовую цену. "
                "Отправьте <code>-</code>, если все цены равны базовой. Список полностью заменяется.",
    "specs": "Введите характеристики (до 500 символов). Если нечего добавить, напишите «Уточняйте у продавца».",
    "stock": "Введите количество (например, 5; 0 — нет в наличии) или статус: "
             "<b>в наличии</b> / <b>под заказ</b> / <b>нет</b>.\n"
             "Статус без числа убирает учёт количества. Остаток уточняет продавец; заявки его не списывают.",
}
STEPS = list(PROMPTS)


def auth(event):
    require_admin(event.from_user.id)


async def show_admin_product(event, repo, pid):
    auth(event)
    p = await repo.get_product(pid)
    await screen(event, "⚙️ <b>Управление товаром</b>\n\n" + product_card(p), product_actions(p))


@router.message(Command("admin"))
@router.callback_query(F.data == "admin")
async def panel(event: Message | CallbackQuery, state: FSMContext):
    auth(event)
    await state.clear()
    await screen(event, "⚙️ <b>Панель администратора</b>\nВыберите действие.", admin_menu())


async def prompt_product(event, state):
    data = await state.get_data()
    field = data["field"]
    note = ""
    if data.get("edit_id") and field in {"colors", "memories"}:
        note = "\n⚠️ Изменение вариантов сбросит индивидуальные цены к базовой. После сохранения задайте их заново."
    if data.get("edit_id") and field == "price":
        note = "\nИзменится базовая цена; индивидуальные цены, отличавшиеся от старой базовой, сохранятся."
    if data.get("edit_id") and field not in {"images", "variants", "stock"}:
        current = data["draft"][field]
        if isinstance(current, list):
            current = ", ".join(current)
        note += f"\n\nТекущее значение:\n{escape(str(current))}"
    if field == "variants":
        note += (f"\n\nЦвета: {escape(', '.join(data['draft']['colors']))}\n"
                 f"Память: {escape(', '.join(data['draft']['memories']))}\nБазовая цена: {data['draft']['price']} сом")
    rows = []
    if field == "images":
        rows = [[("✅ Готово", f"adone:{data['nonce']}")]]
        rows += [[(f"🗑 Удалить фото {i+1}", f"arm:{data['nonce']}:{i}")] for i in range(len(data["draft"].get("images", []))) ]
        note += f"\nСохранено фото: {len(data['draft'].get('images', []))}"
    rows.append([("Отмена", "cancel")])
    await screen(event, f"✏️ <b>{FIELDS[field]}</b>\n\n{PROMPTS[field]}{note}\n\nОтмена на любом шаге: /cancel", keyboard(rows))


@router.callback_query(F.data == "aadd")
async def add(callback: CallbackQuery, state: FSMContext):
    auth(callback)
    await state.clear()
    await state.set_state(AdminState.product)
    await state.update_data(draft={"images": [], "variants": []}, field=STEPS[0], nonce=secrets.token_hex(4))
    await prompt_product(callback, state)


@router.callback_query(F.data.startswith("afind:"))
async def find_start(callback: CallbackQuery, state: FSMContext):
    auth(callback)
    action = callback.data.split(":")[1]
    if action not in {"edit", "delete", "stock", "view"}:
        raise ValueError("Неизвестное действие.")
    await state.clear()
    await state.set_state(AdminState.find)
    await state.update_data(find_action=action)
    await screen(callback, "Введите ID товара или часть названия, бренда или модели.", cancel())


@router.message(AdminState.find)
async def find_result(message: Message, state: FSMContext, repo):
    auth(message)
    value = v.text(message.text, 100, "Поиск")
    action = (await state.get_data())["find_action"]
    if value.isascii() and value.isdigit():
        p = await repo.get_product(int(value))
        await state.set_state(None)
        if action == "stock":
            await begin_edit(message, state, repo, p["id"], "stock")
        elif action == "delete":
            await delete_prompt(message, p)
        else:
            await show_admin_product(message, repo, p["id"])
    else:
        # Keep the query in state so pagination always uses the same search.
        await state.update_data(admin_query=value)
        await show_admin_list(message, state, repo)


async def show_admin_list(event, state, repo, page=0):
    auth(event)
    await state.set_state(None)
    query = (await state.get_data()).get("admin_query", "")
    products, total, page = await repo.products(page, query=query)
    await screen(event, f"📋 <b>Все товары</b> · {total}\nСтраница {page+1}\n"
                 + (f"Поиск: {escape(query)}\n" if query else "")
                 + ("Выберите товар для управления." if products else "Товары не найдены. Добавьте первый товар в админ-панели."),
                 catalog_keyboard(products, page, total, admin=True))


@router.callback_query(F.data.startswith("alist:"))
@router.callback_query(F.data == "aall")
async def all_products(callback: CallbackQuery, state: FSMContext, repo):
    auth(callback)
    if callback.data == "aall":
        await state.update_data(admin_query="")
    await show_admin_list(callback, state, repo, 0 if callback.data == "aall" else int(callback.data.split(":")[1]))


@router.callback_query(F.data.startswith("ap:"))
async def admin_product(callback: CallbackQuery, state: FSMContext, repo):
    auth(callback)
    await state.set_state(None)
    await show_admin_product(callback, repo, int(callback.data.split(":")[1]))


async def begin_edit(event, state, repo, pid, field):
    auth(event)
    if field not in FIELDS:
        raise ValueError("Поле не найдено.")
    p = await repo.get_product(pid)
    await state.clear()
    await state.set_state(AdminState.product)
    await state.update_data(draft=p, edit_id=pid, revision=p["revision"], field=field, nonce=secrets.token_hex(4))
    await prompt_product(event, state)


@router.callback_query(F.data.startswith("ae:"))
async def edit(callback: CallbackQuery, state: FSMContext, repo):
    auth(callback)
    _, pid, field = callback.data.split(":")
    await begin_edit(callback, state, repo, int(pid), field)


async def advance_product(event, state, repo):
    auth(event)
    data = await state.get_data()
    if data.get("edit_id"):
        p = await AdminService(repo).save(event.from_user.id, data["draft"], data["edit_id"], data["revision"])
        await state.clear()
        await show_admin_product(event, repo, p["id"])
        return
    index = STEPS.index(data["field"]) + 1
    if index < len(STEPS):
        await state.update_data(field=STEPS[index])
        await prompt_product(event, state)
    else:
        draft = v.validate_product(data["draft"])
        preview = dict(draft, id="после публикации", created_at=now())
        await state.update_data(field="publish")
        await screen(event, "✅ <b>Проверьте товар перед публикацией</b>\n\n" + product_card(preview) +
                     f"\nФото: {len(draft['images'])}", keyboard([
                         [("✅ Опубликовать", f"apublish:{data['nonce']}")], [("Отмена", "cancel")]]))


def parse_field(field, value, draft):
    if field in {"name", "brand", "model", "short_description", "description", "specs"}:
        limits = {"name": 100, "brand": 40, "model": 60, "short_description": 240, "description": 1600, "specs": 500}
        return {field: v.text(value, limits[field], FIELDS[field])}
    if field == "price":
        return {"price": v.price(value)}
    if field in {"colors", "memories"}:
        return {field: v.options(v.text(value, 500)), "variants": []}
    if field == "variants":
        return {"variants": v.variant_prices(v.text(value, 4000), draft["colors"], draft["memories"])}
    if field == "stock":
        return v.stock(v.text(value, 100))
    raise ValueError("Завершите текущий шаг кнопкой или откройте /admin.")


@router.message(AdminState.product, Command("done"))
async def photos_done_command(message: Message, state: FSMContext, repo):
    auth(message)
    await complete_photos(message, state, repo)


async def complete_photos(event, state, repo):
    auth(event)
    data = await state.get_data()
    if data.get("field") != "images" or not data.get("draft", {}).get("images"):
        raise ValueError("Сначала добавьте хотя бы одну фотографию на шаге фотографий.")
    await advance_product(event, state, repo)


@router.callback_query(F.data.startswith("adone:"))
async def photos_done(callback: CallbackQuery, state: FSMContext, repo):
    auth(callback)
    data = await state.get_data()
    if data.get("nonce") != callback.data.split(":")[1]:
        raise ValueError("Кнопка устарела. Продолжите текущий диалог или /admin.")
    await complete_photos(callback, state, repo)


@router.callback_query(F.data.startswith("arm:"))
async def remove_photo(callback: CallbackQuery, state: FSMContext):
    auth(callback)
    _, nonce, index = callback.data.split(":")
    data = await state.get_data()
    if data.get("field") != "images" or data.get("nonce") != nonce:
        raise ValueError("Кнопка устарела.")
    index = int(index)
    images = data["draft"]["images"]
    if not 0 <= index < len(images):
        raise ValueError("Фото уже удалено.")
    images.pop(index)
    # Rotate the nonce: double presses cannot remove a different image at the same index.
    await state.update_data(draft=data["draft"], nonce=secrets.token_hex(4))
    await prompt_product(callback, state)


@router.message(AdminState.product)
async def product_input(message: Message, state: FSMContext, repo):
    auth(message)
    data = await state.get_data()
    field, draft = data["field"], data["draft"]
    if field == "images":
        if not message.photo:
            raise ValueError("Отправьте фотографию как фото (не файл), затем «Готово» или /done.")
        photo = message.photo[-1]
        if not photo.file_size or photo.file_size > v.MAX_PHOTO_BYTES:
            raise ValueError("Размер фотографии должен быть известен и не превышать 10 МБ.")
        if len(draft["images"]) >= v.MAX_PHOTOS:
            raise ValueError("Максимум 10 фотографий. Удалите лишнюю или нажмите /done.")
        if photo.file_id not in draft["images"]:
            draft["images"].append(photo.file_id)
        await state.update_data(draft=draft, nonce=secrets.token_hex(4))
        await prompt_product(message, state)
        return
    if message.text is None:
        raise ValueError("На этом шаге требуется текст. Для отмены: /cancel.")
    changes = parse_field(field, message.text, draft)
    if field == "price" and data.get("edit_id"):
        # Stored rows include base-price combinations; retain only actual overrides.
        draft["variants"] = [x for x in draft["variants"] if x["price"] != draft["price"]]
    draft.update(changes)
    await state.update_data(draft=draft)
    await advance_product(message, state, repo)


@router.callback_query(F.data.startswith("apublish:"))
async def publish(callback: CallbackQuery, state: FSMContext, repo):
    auth(callback)
    data = await state.get_data()
    if data.get("field") != "publish" or data.get("nonce") != callback.data.split(":")[1]:
        raise ValueError("Товар уже опубликован или диалог завершён. Откройте /admin.")
    p = await AdminService(repo).save(callback.from_user.id, data["draft"])
    await state.clear()
    await show_admin_product(callback, repo, p["id"])


async def delete_prompt(event, p):
    auth(event)
    await screen(event, f"🗑 Удалить <b>{escape(p['name'])}</b> (ID {p['id']})?\nИстория заказов сохранится.",
                 keyboard([[("Да, удалить", f"adelete:{p['id']}:{p['revision']}")], [("Отмена", f"ap:{p['id']}")]]))


@router.callback_query(F.data.startswith("adel:"))
async def delete_start(callback: CallbackQuery, repo):
    auth(callback)
    _, pid, revision = callback.data.split(":")
    p = await repo.get_product(int(pid))
    if p["revision"] != int(revision):
        raise ValueError("Карточка изменилась. Откройте товар заново.")
    await delete_prompt(callback, p)


@router.callback_query(F.data.startswith("adelete:"))
async def delete_confirm(callback: CallbackQuery, repo):
    auth(callback)
    _, pid, revision = callback.data.split(":")
    await AdminService(repo).delete(callback.from_user.id, int(pid), int(revision))
    await screen(callback, "Товар удалён. История заказов сохранена.", admin_menu())


@router.callback_query(F.data.startswith("aorders:"))
async def all_orders(callback: CallbackQuery, state: FSMContext, repo):
    auth(callback)
    await state.set_state(None)
    orders, total, page = await repo.orders(callback.from_user.id, int(callback.data.split(":")[1]), admin=True)
    rows = [[(f"{o['number']} · {o['product_name']}"[:64], f"ao:{o['id']}")] for o in orders]
    rows += pagination("aorders", page, total) + [[("◀️ Админ-панель", "admin")]]
    await screen(callback, f"🧾 <b>Все заказы</b> · {total}\nСтраница {page+1}\n\n" +
                 ("\n\n".join(order_card(o) for o in orders) if orders else "Заказов пока нет."), keyboard(rows))


@router.callback_query(F.data.startswith("ao:"))
async def admin_order(callback: CallbackQuery, repo):
    auth(callback)
    o = await repo.get_order(callback.from_user.id, int(callback.data.split(":")[1]), admin=True)
    await screen(callback, order_card(o, True) + ("\n⚠️ Уведомление ещё не доставлено." if not o["admin_notified"] else ""), order_actions(o))


@router.callback_query(F.data.startswith("astatus:"))
async def status_menu(callback: CallbackQuery, repo):
    auth(callback)
    o = await repo.get_order(callback.from_user.id, int(callback.data.split(":")[1]), admin=True)
    await screen(callback, f"Выберите статус заказа {o['number']}", status_keyboard(o["id"]))


@router.callback_query(F.data.startswith("as:"))
async def status_change(callback: CallbackQuery, repo, order_service):
    auth(callback)
    _, oid, status = callback.data.split(":")
    changed = await repo.change_status(callback.from_user.id, int(oid), status)
    if changed:
        await order_service.deliver_pending(order_id=int(oid))
    o = await repo.get_order(callback.from_user.id, int(oid), admin=True)
    await screen(callback, order_card(o, True) + "\n\nСтатус сохранён. Уведомление покупателю отправлено или поставлено в очередь доставки.", order_actions(o))


@router.callback_query(F.data == "astats")
async def stats(callback: CallbackQuery, repo):
    auth(callback)
    users, products, rows, pending = await repo.statistics(callback.from_user.id)
    details = "\n".join(f"{STATUSES[r['status']]}: {r['count']} · {money(r['amount'])} сом" for r in rows)
    await screen(callback, f"📊 <b>Статистика</b>\nПользователей: {users}\nТоваров: {products}\n"
                 f"Уведомлений в очереди: {pending}\n\n{details}\n\nСуммы — стоимость заявок, не полученная выручка.",
                 keyboard([[("🔄 Повторить доставку уведомлений", "aretry")], [("◀️ Админ-панель", "admin")]]))


@router.callback_query(F.data == "aretry")
async def retry(callback: CallbackQuery, repo, order_service):
    auth(callback)
    await repo.retry_notifications(callback.from_user.id)
    await order_service.deliver_pending()
    await stats(callback, repo)


@router.callback_query(F.data == "asettings")
async def settings(callback: CallbackQuery, state: FSMContext, repo, config):
    auth(callback)
    await state.set_state(None)
    handle = await repo.get_setting("admin_username", config.admin_username)
    name = await repo.get_setting("shop_name", config.shop_name)
    await screen(callback, f"⚙️ <b>Настройки</b>\nНазвание: {escape(name)}\nUsername продавца: "
                 + (f"@{escape(handle)}" if handle else "не указан") + f"\nАдминистратор: {ADMIN_ID}\n\n"
                 "Для получения заказов администратор должен открыть /start в этом боте.", keyboard([
                     [("Название магазина", "aset:shop_name")], [("Username продавца", "aset:admin_username")],
                     [("Текст «О магазине»", "aset:about")], [("◀️ Админ-панель", "admin")]]))


@router.callback_query(F.data.startswith("aset:"))
async def setting_start(callback: CallbackQuery, state: FSMContext):
    auth(callback)
    key = callback.data.split(":")[1]
    if key not in {"shop_name", "admin_username", "about"}:
        raise ValueError("Неизвестная настройка.")
    await state.set_state(AdminState.setting)
    await state.update_data(setting_key=key)
    prompt = "Введите username без ссылки или - для отключения прямой связи." if key == "admin_username" else "Введите новый текст."
    await screen(callback, prompt, cancel())


@router.message(AdminState.setting)
async def setting_value(message: Message, state: FSMContext, repo):
    auth(message)
    key = (await state.get_data())["setting_key"]
    value = v.text(message.text, 1000 if key == "about" else 80)
    if key == "admin_username":
        value = v.username("" if value == "-" else value)
    await repo.set_setting(message.from_user.id, key, value)
    await state.clear()
    await message.answer("Настройка сохранена.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("apricelist:"))
async def price_list(callback: CallbackQuery, repo):
    auth(callback)
    p = await repo.get_product(int(callback.data.split(":")[1]))
    lines = [f"{x['color']} | {x['memory']} = {x['price']}" for x in p["variants"]]
    await callback.message.answer_document(BufferedInputFile("\n".join(lines).encode("utf-8-sig"), filename=f"prices-{p['id']}.txt"))

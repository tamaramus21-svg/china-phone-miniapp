from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main import main_menu, home, contact_keyboard
from bot.ui import screen
from config import ADMIN_ID

router = Router(name="start")


async def show_home(event, state, repo, config):
    await state.clear()
    name = await repo.get_setting("shop_name", config.shop_name)
    await screen(event, f"📱 <b>{escape(name)}</b>\n\nСмартфоны из Китая. Выберите модель, цвет и память — "
                 "мы подготовим заказ для продавца.\n\nУсловия наличия и доставки уточняет продавец.", main_menu(config.webapp_url))


@router.callback_query(F.data == "open_shop")
async def open_shop(callback: CallbackQuery, config):
    if config.webapp_url:
        await screen(callback, "Откройте магазин в отдельном окне Telegram.", main_menu(config.webapp_url))
    else:
        await screen(callback, "Mini App ещё не опубликован. Продавцу нужно настроить публичный HTTPS-адрес магазина. "
                     "После публикации эта кнопка откроет приложение внутри Telegram.", home())


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, repo, config, order_service):
    await show_home(message, state, repo, config)
    if message.from_user.id == ADMIN_ID:
        await repo.retry_notifications(ADMIN_ID)
        await order_service.deliver_pending()


@router.callback_query(F.data == "home")
async def home_callback(callback: CallbackQuery, state: FSMContext, repo, config):
    await show_home(callback, state, repo, config)


@router.message(Command("help"))
async def help_message(message: Message, config):
    await message.answer("Нажмите «Открыть магазин»: после публикации Mini App откроется внутри Telegram. "
                         "В приложении выберите смартфон, цвет и память и проверьте цену перед подтверждением. "
                         "Заказы и связь с продавцом доступны на нижней панели.\n\n"
                         "Каталог в чате также сохранён. В карточке нажмите «Заказать», "
                         "выберите цвет и память и подтвердите цену. Заказ появится в «Мои заказы».\n\n"
                         "Готовый текст можно скопировать и отправить продавцу. Статусы приходят в этот чат.\n"
                         "/start — меню · /cancel — отмена текущего действия.", reply_markup=main_menu(config.webapp_url))


@router.message(Command("admin"), F.from_user.id != ADMIN_ID)
async def admin_unavailable(message: Message):
    await message.answer("Команда недоступна.", reply_markup=home())


@router.message(Command("cancel"))
@router.callback_query(F.data == "cancel")
async def cancel_action(event: Message | CallbackQuery, state: FSMContext, repo, config):
    await state.clear()
    async with repo.db.connect() as db:
        await db.execute("UPDATE checkouts SET state='cancelled' WHERE user_id=? AND state='open'", (event.from_user.id,))
        await db.commit()
    await screen(event, "Действие отменено.", main_menu(config.webapp_url))


@router.callback_query(F.data == "about")
async def about(callback: CallbackQuery, repo, config):
    name = await repo.get_setting("shop_name", config.shop_name)
    description = await repo.get_setting("about", "Магазин смартфонов из Китая. Наличие, сроки, комплектация и доставка согласуются с продавцом.")
    await screen(callback, f"ℹ️ <b>{escape(name)}</b>\n\n{escape(description)}", home())


@router.callback_query(F.data == "contact")
async def contact(callback: CallbackQuery, repo, config):
    username = await repo.get_setting("admin_username", config.admin_username)
    text = "Нажмите кнопку, чтобы открыть чат с продавцом." if username else (
        "Продавец ещё не указал username для прямой связи. Оформите заказ в боте: он сохранится и "
        "будет передан продавцу. Статус можно проверить в «Мои заказы».")
    await screen(callback, text, contact_keyboard(username))


@router.callback_query(F.data == "copy_help")
async def copy_help(callback: CallbackQuery):
    await callback.message.answer("Нажмите на блок с текстом заказа и выберите «Копировать» "
                                  "или используйте значок копирования рядом с блоком (зависит от клиента Telegram). "
                                  "Также сообщение можно переслать продавцу.")

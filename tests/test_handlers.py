import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, Update, User

from bot.handlers import admin
from config import Config, ADMIN_ID
from main import build_dispatcher


class RecordingSession(BaseSession):
    """Offline Bot API responses. No HTTP request or real token is used."""
    def __init__(self):
        super().__init__()
        self.calls = []
        self.serial = 100
        self.last = {}
        self.fail_admin = False

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        name = method.__api_method__
        if name == "answerCallbackQuery":
            return True
        if self.fail_admin and name == "sendMessage" and method.chat_id == ADMIN_ID:
            raise TelegramForbiddenError(method=method, message="bot was blocked")
        if name == "getMe":
            return User(id=123456, is_bot=True, first_name="TestBot", username="test_shop_bot")
        if name in {"sendMessage", "editMessageText", "sendPhoto", "sendDocument", "sendMediaGroup"}:
            self.serial += 1
            message = Message(message_id=getattr(method, "message_id", None) or self.serial,
                              date=datetime.now(timezone.utc), chat=Chat(id=int(method.chat_id), type="private"),
                              from_user=User(id=bot.id, is_bot=True, first_name="TestBot"),
                              text=getattr(method, "text", None), reply_markup=getattr(method, "reply_markup", None))
            if message.text:
                self.last[int(method.chat_id)] = message
            return [message, message] if name == "sendMediaGroup" else message
        return True


async def test_every_admin_handler_has_own_guard():
    event = SimpleNamespace(from_user=SimpleNamespace(id=12345))
    handlers = {h.callback for observer in (admin.router.message, admin.router.callback_query) for h in observer.handlers}
    for handler in handlers:
        kwargs = {name: event if name in {"event", "message", "callback"} else None
                  for name in inspect.signature(handler).parameters}
        with pytest.raises(PermissionError):
            await handler(**kwargs)


async def test_full_shop_ui_offline(repo, tmp_path):
    session = RecordingSession()
    bot = Bot("123456:OFFLINE_TEST_TOKEN_ABCDEFGHIJKLMNOPQRSTUVWXYZ", session=session,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    config = Config("unused", tmp_path / "unused.sqlite3")
    dp = build_dispatcher(repo, config, bot)
    serial = 0

    async def message(text=None, user=ADMIN_ID, photo=None):
        nonlocal serial
        serial += 1
        m = Message(message_id=serial, date=datetime.now(timezone.utc), chat=Chat(id=user, type="private"),
                    from_user=User(id=user, is_bot=False, first_name="Тест", username="test_person"),
                    text=text, photo=photo)
        await dp.feed_update(bot, Update(update_id=serial, message=m))

    async def cb(data, user=ADMIN_ID):
        nonlocal serial
        serial += 1
        origin = session.last.get(user) or Message(message_id=1, date=datetime.now(timezone.utc),
                                                  chat=Chat(id=user, type="private"), text="menu")
        c = CallbackQuery(id=str(serial), from_user=User(id=user, is_bot=False, first_name="Тест"),
                          chat_instance="test", data=data, message=origin)
        await dp.feed_update(bot, Update(update_id=serial, callback_query=c))

    def last_text(user=ADMIN_ID):
        return session.last[user].text

    async def state_data(user=ADMIN_ID):
        return await dp.fsm.get_context(bot, user, user).get_data()

    await message("/start", user=12345)
    assert "CHINA PHONE" in last_text(12345)
    await cb("cat:0", user=12345)
    assert "Каталог пока пуст" in last_text(12345)
    await cb("aadd", user=12345)
    assert "недоступно" in last_text(12345)
    await message("/admin", user=12345)
    assert "недоступна" in last_text(12345)
    await cb("contact", user=12345)
    assert "ещё не указал username" in last_text(12345)
    await cb("about", user=12345)
    await message("/help", user=12345)

    await message("/start")
    await message("/admin")
    assert "Панель администратора" in last_text()
    await cb("aadd")
    for value in ["Тестовый товар", "ТестБренд", "ТестМодель", "Краткое", "Описание", "-1"]:
        await message(value)
    assert (await state_data())["field"] == "price"
    await message("10000")
    # Documents, absent photos and oversize photos cannot enter the product.
    await message("not a photo")
    await message(photo=[PhotoSize(file_id="too_big", file_unique_id="big", width=1000, height=1000, file_size=11*1024*1024)])
    assert not (await state_data())["draft"]["images"]
    await message(photo=[PhotoSize(file_id="test_1", file_unique_id="one", width=100, height=100, file_size=1000)])
    await message(photo=[PhotoSize(file_id="test_2", file_unique_id="two", width=100, height=100, file_size=1000)])
    nonce = (await state_data())["nonce"]
    await cb(f"arm:{nonce}:1")
    await cb(f"arm:{nonce}:0")  # Double press must not remove a different photo.
    assert (await state_data())["draft"]["images"] == ["test_1"]
    await message("/done")
    for value in ["Чёрный, Белый", "128 ГБ, 256 ГБ", "256 ГБ = 12000\nБелый | 256 ГБ = 13000", "Характеристики", "3"]:
        await message(value)
    data = await state_data()
    assert data["field"] == "publish"
    assert (await repo.products())[1] == 0
    await cb(f"apublish:{data['nonce']}")
    await cb(f"apublish:{data['nonce']}")
    assert (await repo.products())[1] == 1
    p = await repo.get_product(1)
    assert len(p["images"]) == 1 and len(p["variants"]) == 4

    # All edit types go through the same validated field handler.
    for field, value in [("name", "Обновлённый товар"), ("brand", "ОбновлённыйБренд"), ("model", "ОбновлённаяМодель"),
                         ("short_description", "Новое краткое"), ("description", "Новое полное"), ("price", "11000"),
                         ("colors", "Чёрный, Белый"), ("memories", "128 ГБ, 256 ГБ"),
                         ("variants", "256 ГБ = 12000\nБелый | 256 ГБ = 13000"), ("specs", "Новые характеристики"), ("stock", "под заказ")]:
        await cb(f"ae:1:{field}")
        await message(value)
        assert "Управление товаром" in last_text()
    await cb("ae:1:images")
    await message(photo=[PhotoSize(file_id="test_3", file_unique_id="three", width=100, height=100, file_size=1000)])
    await cb("adone:" + (await state_data())["nonce"])
    assert (await repo.get_product(1))["images"] == ["test_1", "test_3"]
    await cb("apricelist:1")
    await cb("p:1")
    await cb("photos:1")
    await cb("refresh:1")
    await cb("afind:stock")
    await message("1")
    await message("3")
    await cb("afind:view")
    await message("обновлённый")
    assert "Поиск:" in last_text()
    await cb("ap:1")

    await cb("asettings")
    await cb("aset:admin_username")
    await message("https://t.me/wrong")
    assert await repo.get_setting("admin_username") == ""
    await message("@test_seller")
    await cb("aset:shop_name")
    await message("Мой магазин")
    await cb("aset:about")
    await message("Информация о магазине")
    await cb("astats")
    await cb("aretry")
    await cb("aorders:0")
    assert "Заказов пока нет" in last_text()

    await cb("home", user=12345)
    assert "Мой магазин" in last_text(12345)
    await cb("search", user=12345)
    await message("ОБНОВЛЁННЫЙ", user=12345)
    assert "Обновлённый товар" in last_text(12345)
    await cb("filters", user=12345)
    await cb("filter:brand", user=12345)
    await message("ОбновлённыйБренд", user=12345)
    await cb("filter:price", user=12345)
    await message("10000 15000", user=12345)
    await cb("filter:stock", user=12345)
    await cb("filter:reset", user=12345)
    await cb("p:1", user=12345)
    assert "Новое полное" in last_text(12345)
    await cb("buy:1", user=12345)
    async with repo.db.connect() as db:
        token = (await (await db.execute("SELECT token FROM checkouts WHERE user_id=12345 AND state='open'")).fetchone())[0]
    await cb(f"oc:{token}:1", user=12345)
    await cb(f"om:{token}:1", user=12345)
    assert "13 000" in last_text(12345)
    assert (await repo.orders(12345))[1] == 0
    session.fail_admin = True
    await cb(f"confirm:{token}", user=12345)
    assert "Заказ сохранён, ожидает подтверждения продавца" in last_text(12345)
    await cb(f"confirm:{token}", user=12345)
    assert (await repo.orders(12345))[1] == 1
    o = (await repo.orders(12345))[0][0]
    assert o["price"] == 13000 and o["color"] == "Белый"
    assert any(b.url and b.url.startswith("https://t.me/test_seller?text=")
               for row in session.last[12345].reply_markup.inline_keyboard for b in row)
    await cb("copy_help", user=12345)
    await cb("my:0", user=12345)
    await cb(f"order:{o['id']}", user=12345)

    session.fail_admin = False
    await message("/start")
    assert (await repo.get_order(12345, o["id"]))["admin_notified"] == 1
    await cb("aorders:0")
    await cb(f"ao:{o['id']}")
    await cb(f"astatus:{o['id']}")
    await cb(f"as:{o['id']}:shipped")
    assert (await repo.get_order(12345, o["id"]))["status"] == "shipped"
    p = await repo.get_product(1)
    await cb(f"adel:1:{p['revision']}")
    assert (await repo.products())[1] == 1
    await cb(f"adelete:1:{p['revision']}")
    assert (await repo.products())[1] == 0
    assert (await repo.get_order(12345, o["id"]))["product_name"] == "Обновлённый товар"
    await cb("aadd")
    await message("/cancel")
    assert await dp.fsm.get_context(bot, ADMIN_ID, ADMIN_ID).get_state() is None
    await cb("invalid:button", user=12345)
    await message("unrecognized", user=12345)
    assert not any("Произошла ошибка" in (getattr(call, "text", "") or "") for call in session.calls)
    await dp.storage.close()
    await bot.session.close()

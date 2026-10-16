import asyncio
import logging

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import CallbackQuery, Message

log = logging.getLogger(__name__)


class ShopMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)
        message = event.message if isinstance(event, CallbackQuery) else event
        if not isinstance(message, Message) or message.chat.type != "private":
            if isinstance(event, CallbackQuery):
                await event.answer("Откройте личный чат с ботом.", show_alert=True)
            elif isinstance(message, Message):
                await message.answer("Магазин доступен в личном чате с ботом.")
            return
        try:
            if isinstance(event, CallbackQuery):
                await event.answer()
            await data["repo"].upsert_user(event.from_user)
            return await handler(event, data)
        except (ValueError, PermissionError) as exc:
            await message.answer(str(exc))
        except TelegramRetryAfter as exc:
            log.warning("Telegram rate limit: %s seconds", exc.retry_after)
            # Avoid sending again while Telegram requests a pause.
        except (TelegramAPIError, OSError, asyncio.TimeoutError) as exc:
            log.warning("Request failed: %s", type(exc).__name__)
            try:
                await message.answer("Не удалось выполнить действие. Попробуйте позже. Сохранённые заказы доступны в «Мои заказы».")
            except TelegramAPIError:
                pass
        except Exception as exc:
            log.error("Handler failed: %s", type(exc).__name__)
            try:
                await message.answer("Произошла ошибка. Попробуйте снова или откройте /start. Заказы сохранены в базе.")
            except TelegramAPIError:
                pass

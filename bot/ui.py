from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, InputMediaPhoto


async def screen(event, text, markup=None):
    if isinstance(event, CallbackQuery):
        message = event.message
        if not isinstance(message, Message):
            return await event.bot.send_message(event.from_user.id, text, reply_markup=markup)
        if message.text is not None:
            try:
                return await message.edit_text(text, reply_markup=markup)
            except TelegramBadRequest as exc:
                if "message is not modified" in exc.message:
                    return message
                if not any(x in exc.message for x in ("message can't be edited", "message to edit not found")):
                    raise
        return await message.answer(text, reply_markup=markup)
    return await event.answer(text, reply_markup=markup)


async def photos(event, product):
    bot, chat_id = event.bot, event.from_user.id
    try:
        if len(product["images"]) == 1:
            await bot.send_photo(chat_id, product["images"][0])
        elif product["images"]:
            await bot.send_media_group(chat_id, [InputMediaPhoto(media=x) for x in product["images"]])
    except TelegramBadRequest:
        await bot.send_message(chat_id, "Не удалось показать фотографии. Данные товара доступны ниже; продавец проверит фото.")

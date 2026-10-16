from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.keyboards.catalog import product_keyboard
from bot.ui import screen, photos
from utils.formatters import product_card

router = Router(name="product")


@router.callback_query(F.data.startswith("p:"))
@router.callback_query(F.data.startswith("refresh:"))
async def product(callback: CallbackQuery, state: FSMContext, repo):
    await state.set_state(None)
    p = await repo.get_product(int(callback.data.split(":")[1]))
    if callback.data.startswith("p:"):
        await photos(callback, p)
        # Put the detailed card under the photo/album.
        await callback.message.answer(product_card(p), reply_markup=product_keyboard(p))
    else:
        await screen(callback, product_card(p), product_keyboard(p))


@router.callback_query(F.data.startswith("photos:"))
async def product_photos(callback: CallbackQuery, repo):
    p = await repo.get_product(int(callback.data.split(":")[1]))
    await photos(callback, p)

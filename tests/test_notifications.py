from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from config import ADMIN_ID
from bot.services.order_service import OrderService
from tests.conftest import ready_checkout


async def test_failed_notification_keeps_order_and_retries(repo, product_data, caplog):
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await ready_checkout(repo, p)
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramForbiddenError(method=SendMessage(chat_id=ADMIN_ID, text="test"), message="secret-must-not-be-logged")
    service = OrderService(repo, bot)
    o, created = await service.confirm(12345, token)
    assert created and not o["admin_notified"]
    assert (await repo.orders(12345))[1] == 1
    assert "TelegramForbiddenError" in caplog.text
    assert "secret-must-not-be-logged" not in caplog.text
    bot.send_message.side_effect = None
    await repo.retry_notifications(ADMIN_ID)
    await service.deliver_pending()
    assert (await repo.get_order(12345, o["id"]))["admin_notified"] == 1
    await service.confirm(12345, token)
    assert bot.send_message.await_count == 2  # No duplicate notification on double confirm.


async def test_status_notification(repo, product_data):
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await ready_checkout(repo, p)
    bot = AsyncMock()
    service = OrderService(repo, bot)
    o, _ = await service.confirm(12345, token)
    await repo.change_status(ADMIN_ID, o["id"], "shipped")
    await service.deliver_pending()
    assert bot.send_message.await_count == 2
    args = bot.send_message.call_args.args
    assert args[0] == 12345 and "Отправлен" in args[1]


async def test_notification_claim_is_exclusive(repo, product_data):
    import asyncio
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await ready_checkout(repo, p)
    await repo.confirm_order(12345, token)
    claims = await asyncio.gather(*(repo.claim_notification() for _ in range(5)))
    assert len([n for n in claims if n]) == 1


async def test_unexpected_transport_failure_keeps_receipt_available(repo, product_data):
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await ready_checkout(repo, p)
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("unexpected transport failure")
    o, created = await OrderService(repo, bot).confirm(12345, token)
    assert created and o["admin_notified"] == 0

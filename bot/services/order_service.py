import asyncio
import logging
from html import escape

from aiogram.exceptions import TelegramRetryAfter

from config import ADMIN_ID
from database.models import STATUSES
from utils.formatters import order_card, order_message

log = logging.getLogger(__name__)


class OrderService:
    def __init__(self, repo, bot):
        self.repo, self.bot = repo, bot

    async def confirm(self, user_id, token):
        order, created = await self.repo.confirm_order(user_id, token)
        if created:
            await self.deliver_pending(order_id=order["id"], limit=1)
        return await self.repo.get_order(user_id, order["id"]), created

    async def deliver_pending(self, order_id=None, limit=20):
        for _ in range(limit):
            n = await self.repo.claim_notification(order_id)
            if not n:
                break
            try:
                o = await self.repo.get_order(ADMIN_ID, n["order_id"], admin=True)
                if n["kind"] == "new":
                    from bot.keyboards.admin import order_actions
                    await self.bot.send_message(n["target_id"], "🆕 Новый заказ\n\n" + order_card(o, True) +
                                                "\n\n" + escape(order_message(o)), reply_markup=order_actions(o))
                else:
                    await self.bot.send_message(n["target_id"], f"📦 Заказ {o['number']}: {STATUSES[n['status']]}")
            except Exception as exc:
                # Exception text may contain a request URL/token. Persist only the class.
                kind = type(exc).__name__
                log.warning("Notification %s for order %s failed: %s", n["id"], n["order_id"], kind)
                await self.repo.finish_notification(n, kind, exc.retry_after + 1 if isinstance(exc, TelegramRetryAfter) else None)
                if isinstance(exc, TelegramRetryAfter):
                    break
            else:
                await self.repo.finish_notification(n)

    async def worker(self):
        while True:
            try:
                await self.deliver_pending()
            except Exception as exc:
                log.error("Notification worker failed: %s", type(exc).__name__)
            await asyncio.sleep(30)

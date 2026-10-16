import asyncio
import io
import json
import logging
import re
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web
from aiogram.exceptions import TelegramAPIError

from config import ADMIN_ID, BASE_DIR
from database.models import STATUSES
from database.repository import effective_price, ensure_available, require_admin
from utils.formatters import order_message
from utils.validators import text, price
from webapp.auth import AuthError, validate_init_data

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def integer(value, minimum=1, maximum=2**63-1):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,18}", value):
        value = int(value)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ApiError(400, "Неверное числовое значение.")
    return value


async def body(request, allowed, required=None):
    if request.content_type != "application/json":
        raise ApiError(415, "Ожидается JSON.")
    try:
        data = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise ApiError(400, "Неверный JSON.") from None
    if not isinstance(data, dict) or set(data) - set(allowed) or set(required or allowed) - set(data):
        raise ApiError(400, "Неверный состав полей запроса.")
    return data


def public_order(o):
    keys = ("id", "number", "product_id", "product_name", "color", "memory", "price", "created_at", "status", "admin_notified")
    return dict({k: o[k] for k in keys}, status_label=STATUSES[o["status"]], message=order_message(o))


def public_product(p, summary=False, has_image=True):
    if summary:
        keys = ("id", "name", "brand", "model", "short_description", "availability", "quantity", "revision")
        return dict({k: p[k] for k in keys}, min_price=p["min_price"], max_price=p["max_price"],
                    image=f"/media/products/{p['id']}/0?v={p['revision']}" if has_image else None)
    result = {k: value for k, value in p.items() if k != "images"}
    result["images"] = [f"/media/products/{p['id']}/{i}?v={p['revision']}" for i in range(len(p["images"]))]
    return result


class ShopApi:
    def __init__(self, repo, config, bot, order_service, dist=None):
        self.repo, self.config, self.bot, self.orders = repo, config, bot, order_service
        self.dist = Path(dist or BASE_DIR / "frontend/dist").resolve()
        self.rate = OrderedDict()
        self.images = OrderedDict()
        self.image_bytes = 0
        self.download_slots = asyncio.Semaphore(4)
        u = urlsplit(config.webapp_url)
        self.allowed_origin = f"{u.scheme}://{u.netloc}" if config.webapp_url else ""

    def throttle(self, key, limit):
        now = time.monotonic()
        stamp, count = self.rate.pop(key, (now, 0))
        if now - stamp >= 60:
            stamp, count = now, 0
        self.rate[key] = (stamp, count + 1)
        while len(self.rate) > 10_000:
            self.rate.popitem(last=False)
        if count >= limit:
            raise ApiError(429, "Слишком много запросов. Попробуйте через минуту.")

    @web.middleware
    async def middleware(self, request, handler):
        try:
            if request.path.startswith("/api/"):
                origin = request.headers.get("Origin")
                if origin and self.allowed_origin and origin != self.allowed_origin:
                    raise ApiError(403, "Источник запроса недоступен.")
                if request.method == "OPTIONS":
                    if not self.allowed_origin or origin != self.allowed_origin:
                        raise ApiError(403, "Источник запроса недоступен.")
                    response = web.Response(status=204)
                    response.headers["Access-Control-Allow-Origin"] = origin
                    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,OPTIONS"
                    response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
                    response.headers["Access-Control-Max-Age"] = "300"
                    return response
                # The peer is used as-is; arbitrary X-Forwarded-For is not trusted.
                self.throttle(("peer", request.remote), 1200)
                raw = request.headers.get("Authorization", "")
                if not raw.startswith("tma "):
                    raise AuthError("Откройте магазин через кнопку в Telegram.")
                user = validate_init_data(raw[4:], self.config.token, self.config.init_data_max_age)
                request["user"] = user
                self.throttle(("user", user.id), 180 if request.method == "GET" else 40)
                if request.path.startswith("/api/admin/"):
                    require_admin(user.id)
                await self.repo.upsert_user(user)
            elif request.path.startswith("/media/"):
                self.throttle(("media", request.remote), 1200)
            response = await handler(request)
        except AuthError as exc:
            response = web.json_response({"error": str(exc)}, status=401)
        except PermissionError:
            response = web.json_response({"error": "Действие недоступно."}, status=403)
        except ApiError as exc:
            response = web.json_response({"error": exc.message}, status=exc.status)
        except web.HTTPException as exc:
            response = web.json_response({"error": "Запрос слишком большой." if exc.status == 413 else "Адрес или метод недоступен."}, status=exc.status)
        except ValueError as exc:
            response = web.json_response({"error": str(exc)}, status=409)
        except (TelegramAPIError, OSError, asyncio.TimeoutError) as exc:
            log.warning("API transport failed: %s", type(exc).__name__)
            response = web.json_response({"error": "Сервис временно недоступен. Попробуйте ещё раз."}, status=503)
        except Exception as exc:
            log.error("API request failed: %s", type(exc).__name__)
            response = web.json_response({"error": "Не удалось выполнить запрос. Попробуйте снова."}, status=500)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if self.allowed_origin and request.headers.get("Origin") == self.allowed_origin:
            response.headers["Access-Control-Allow-Origin"] = self.allowed_origin
            response.headers["Vary"] = "Origin"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/") else response.headers.get("Cache-Control", "no-cache")
        response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' https://telegram.org; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; "
            "font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org https://telegram.org")
        return response

    async def health(self, request):
        return web.json_response({"status": "ok"})

    async def me(self, request):
        u = request["user"]
        return web.json_response({"id": u.id, "first_name": u.first_name, "is_admin": u.id == ADMIN_ID})

    async def info(self, request):
        name = await self.repo.get_setting("shop_name", self.config.shop_name)
        about = await self.repo.get_setting("about", "Смартфоны из Китая. Комплектацию, наличие и доставку согласуем лично с вами.")
        handle = await self.repo.get_setting("admin_username", self.config.admin_username)
        brands, popular, _ = await self.repo.product_metadata()
        return web.json_response({"name": name, "about": about, "admin_username": handle or None,
                                  "brands": brands, "popular_ids": popular, "currency": "KGS"})

    async def products(self, request):
        q = request.query
        if set(q) - {"page", "query", "brand", "minimum", "maximum", "available", "sort"}:
            raise ApiError(400, "Неизвестный фильтр.")
        filters = {k: text(q[k], 100 if k == "query" else 40) for k in ("query", "brand") if q.get(k)}
        for key in ("minimum", "maximum"):
            if q.get(key):
                filters[key] = price(q[key])
        if filters.get("minimum", 0) > filters.get("maximum", 1_000_000_000):
            raise ApiError(400, "Минимальная цена превышает максимальную.")
        if q.get("available", "false") not in {"true", "false"}:
            raise ApiError(400, "Неверный фильтр наличия.")
        filters["available"] = q.get("available") == "true"
        if q.get("sort", "newest") not in {"newest", "popular"}:
            raise ApiError(400, "Неизвестная сортировка.")
        filters["sort"] = q.get("sort", "newest")
        rows, total, page = await self.repo.products(integer(q.get("page", "0"), 0, 100000), **filters)
        _, _, images = await self.repo.product_metadata()
        return web.json_response({"items": [public_product(p, True, p["id"] in images) for p in rows],
                                  "total": total, "page": page, "page_size": 5})

    async def product(self, request):
        return web.json_response(public_product(await self.repo.get_product(integer(request.match_info["pid"]))))

    async def calculate(self, request):
        data = await body(request, {"color", "memory", "revision"})
        p = await self.repo.get_product(integer(request.match_info["pid"]))
        if integer(data["revision"]) != p["revision"]:
            raise ApiError(409, "Товар изменился. Обновите карточку.")
        ensure_available(p)
        amount = effective_price(p, text(data["color"], 32), text(data["memory"], 32))
        return web.json_response({"price": amount, "revision": p["revision"], "currency": "KGS"})

    async def quote(self, request):
        data = await body(request, {"product_id", "revision", "color", "memory", "request_key"})
        key = data["request_key"]
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
            raise ApiError(400, "Неверный ключ запроса.")
        result = await self.repo.quote_checkout(request["user"].id, integer(data["product_id"]), integer(data["revision"]),
                                               text(data["color"], 32), text(data["memory"], 32), key)
        return web.json_response(result)

    async def create_order(self, request):
        data = await body(request, {"quote_token"})
        if not isinstance(data["quote_token"], str) or not re.fullmatch(r"[0-9a-f]{16}", data["quote_token"]):
            raise ApiError(400, "Неверное подтверждение заказа.")
        o, created = await self.orders.confirm(request["user"].id, data["quote_token"])
        return web.json_response({"order": public_order(o), "created": created}, status=201 if created else 200)

    async def list_orders(self, request):
        rows, total, page = await self.repo.orders(request["user"].id, integer(request.query.get("page", "0"), 0, 100000))
        return web.json_response({"items": [public_order(o) for o in rows], "total": total, "page": page, "page_size": 5})

    async def order(self, request):
        return web.json_response(public_order(await self.repo.get_order(request["user"].id, integer(request.match_info["oid"]))))

    async def admin_stats(self, request):
        require_admin(request["user"].id)
        users, products, statuses, pending = await self.repo.statistics(request["user"].id)
        return web.json_response({"users": users, "products": products, "statuses": statuses, "pending_notifications": pending})

    async def admin_orders(self, request):
        require_admin(request["user"].id)
        rows, total, page = await self.repo.orders(request["user"].id, integer(request.query.get("page", "0"), 0, 100000), admin=True)
        return web.json_response({"items": rows, "total": total, "page": page})

    async def admin_status(self, request):
        require_admin(request["user"].id)
        data = await body(request, {"status"})
        oid = integer(request.match_info["oid"])
        await self.repo.change_status(request["user"].id, oid, text(data["status"], 32))
        await self.orders.deliver_pending(order_id=oid)
        return web.json_response(public_order(await self.repo.get_order(request["user"].id, oid, admin=True)))

    async def media(self, request):
        p = await self.repo.get_product(integer(request.match_info["pid"]))
        index = integer(request.match_info["index"], 0, 9)
        if index >= len(p["images"]):
            raise ApiError(404, "Фото не найдено.")
        key = p["images"][index]
        cached = self.images.get(key)
        if cached and time.monotonic() - cached[0] < 300:
            self.images.move_to_end(key)
            data = cached[1]
        else:
            async with self.download_slots:
                file = await self.bot.get_file(key)
                if not file.file_size or file.file_size > 10 * 1024 * 1024 or not file.file_path:
                    raise ApiError(404, "Фото недоступно.")
                target = io.BytesIO()
                await self.bot.download_file(file.file_path, destination=target, timeout=30)
                data = target.getvalue()
                if len(data) > 10 * 1024 * 1024:
                    raise ApiError(413, "Фото слишком большое.")
            previous = self.images.get(key)
            if previous:
                self.image_bytes -= len(previous[1])
            self.images[key] = (time.monotonic(), data)
            self.image_bytes += len(data)
            while self.image_bytes > 32 * 1024 * 1024 or len(self.images) > 128:
                _, removed = self.images.popitem(last=False)
                self.image_bytes -= len(removed[1])
        return web.Response(body=data, content_type="image/jpeg", headers={"Cache-Control": "public,max-age=300"})

    async def static(self, request):
        name = request.match_info.get("path", "")
        path = (self.dist / name).resolve()
        if not path.is_relative_to(self.dist) or any(part.startswith('.') for part in Path(name).parts) or name.startswith("api/") or name.startswith("media/"):
            raise web.HTTPNotFound()
        if not name or not Path(name).suffix:
            path = self.dist / "index.html"
        if not path.is_file() or path.name.startswith("."):
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    def app(self):
        app = web.Application(client_max_size=32 * 1024, middlewares=[self.middleware])
        app.add_routes([web.get("/healthz", self.health), web.get("/api/me", self.me), web.get("/api/shop", self.info),
                        web.get("/api/products", self.products), web.get("/api/products/{pid}", self.product),
                        web.post("/api/products/{pid}/price", self.calculate), web.post("/api/quotes", self.quote),
                        web.post("/api/orders", self.create_order), web.get("/api/orders", self.list_orders),
                        web.get("/api/orders/{oid}", self.order), web.get("/api/admin/stats", self.admin_stats),
                        web.get("/api/admin/orders", self.admin_orders), web.patch("/api/admin/orders/{oid}/status", self.admin_status),
                        web.get("/media/products/{pid}/{index}", self.media), web.get("/{path:.*}", self.static)])
        return app


async def start_server(repo, config, bot, order_service):
    # Access logs are disabled: initData, query strings and headers must not be logged.
    runner = web.AppRunner(ShopApi(repo, config, bot, order_service).app(), access_log=None, max_field_size=20_000)
    await runner.setup()
    try:
        await web.TCPSite(runner, config.http_host, config.http_port).start()
    except Exception:
        await runner.cleanup()
        raise
    log.info("Mini App HTTP server started on port %s; public URL configured: %s", config.http_port, bool(config.webapp_url))
    return runner

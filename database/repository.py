import json
import secrets
import time
from datetime import datetime, timezone

from config import ADMIN_ID
from database.models import STATUSES
from utils.validators import validate_product


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def one(db, sql, params=()):
    row = await (await db.execute(sql, params)).fetchone()
    return dict(row) if row else None


def require_admin(actor_id):
    if actor_id != ADMIN_ID:
        raise PermissionError("Действие недоступно.")


async def load_product(db, product_id):
    p = await one(db, "SELECT * FROM products WHERE id=?", (product_id,))
    if not p:
        raise ValueError("Товар больше недоступен. Откройте каталог заново.")
    p["colors"], p["memories"] = json.loads(p["colors"]), json.loads(p["memories"])
    p["images"] = [r[0] for r in await (await db.execute(
        "SELECT file_id FROM product_images WHERE product_id=? ORDER BY position", (product_id,))).fetchall()]
    p["variants"] = [dict(r) for r in await (await db.execute(
        "SELECT color,memory,price FROM product_variants WHERE product_id=? ORDER BY id", (product_id,))).fetchall()]
    return p


def effective_price(product, color, memory):
    if color not in product["colors"] or memory not in product["memories"]:
        raise ValueError("Выберите доступные цвет и память.")
    return next((v["price"] for v in product["variants"]
                 if v["color"] == color and v["memory"] == memory), product["price"])


def ensure_available(product):
    if product["availability"] == "out" or product["quantity"] == 0:
        raise ValueError("Товара сейчас нет в наличии. Выберите другой товар.")


class Repository:
    def __init__(self, database):
        self.db = database

    async def upsert_user(self, user):
        async with self.db.connect() as db:
            await db.execute("""INSERT INTO users VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE
                SET full_name=excluded.full_name,username=excluded.username""",
                             (user.id, user.full_name, user.username, now()))
            await db.commit()

    async def get_product(self, product_id):
        async with self.db.connect() as db:
            return await load_product(db, product_id)

    async def save_product(self, actor_id, data, product_id=None, expected_revision=None):
        require_admin(actor_id)
        data = validate_product(data)
        keys = ("name", "brand", "model", "short_description", "description", "price", "colors",
                "memories", "specs", "availability", "quantity")
        values = [json.dumps(data[k], ensure_ascii=False) if k in {"colors", "memories"} else data[k] for k in keys]
        async with self.db.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            if product_id is None:
                cursor = await db.execute(f"INSERT INTO products({','.join(keys)},created_at,updated_at) "
                                          f"VALUES({','.join('?' for _ in range(len(keys)+2))})", values + [now(), now()])
                product_id = cursor.lastrowid
            else:
                current = await load_product(db, product_id)
                if expected_revision is not None and current["revision"] != expected_revision:
                    raise ValueError("Товар уже изменён. Откройте его заново перед редактированием.")
                await db.execute(f"UPDATE products SET {','.join(k+'=?' for k in keys)},"
                                 "updated_at=?,revision=revision+1 WHERE id=?", values + [now(), product_id])
                await db.execute("DELETE FROM product_images WHERE product_id=?", (product_id,))
                await db.execute("DELETE FROM product_variants WHERE product_id=?", (product_id,))
            await db.executemany("INSERT INTO product_images(product_id,file_id,position) VALUES(?,?,?)",
                                 [(product_id, file_id, i) for i, file_id in enumerate(data["images"])])
            await db.executemany("INSERT INTO product_variants(product_id,color,memory,price) VALUES(?,?,?,?)",
                                 [(product_id, c, m, effective_price(data, c, m))
                                  for c in data["colors"] for m in data["memories"]])
            await db.commit()
        return await self.get_product(product_id)

    async def delete_product(self, actor_id, product_id, revision):
        require_admin(actor_id)
        async with self.db.connect() as db:
            cursor = await db.execute("DELETE FROM products WHERE id=? AND revision=?", (product_id, revision))
            if cursor.rowcount != 1:
                raise ValueError("Товар изменён или уже удалён. Откройте его заново.")
            await db.commit()

    async def products(self, page=0, query="", brand="", minimum=None, maximum=None, available=False, sort="newest"):
        clauses, params = [], []
        if query:
            pattern = "%" + query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            clauses.append("(casefold(p.name) LIKE ? ESCAPE '\\' OR casefold(p.brand) LIKE ? ESCAPE '\\' OR casefold(p.model) LIKE ? ESCAPE '\\')")
            params.extend([pattern] * 3)
        if brand:
            clauses.append("casefold(p.brand)=?")
            params.append(brand.casefold())
        if available:
            clauses.append("p.availability='in_stock' AND (p.quantity IS NULL OR p.quantity>0)")
        variant_clauses = []
        if minimum is not None:
            variant_clauses.append("v.price>=?")
            params.append(minimum)
        if maximum is not None:
            variant_clauses.append("v.price<=?")
            params.append(maximum)
        if variant_clauses:
            clauses.append("EXISTS(SELECT 1 FROM product_variants v WHERE v.product_id=p.id AND " + " AND ".join(variant_clauses) + ")")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        order = "(SELECT count(*) FROM orders o WHERE o.product_id=p.id AND o.status!='cancelled') DESC,p.id DESC" if sort == "popular" else "p.id DESC"
        async with self.db.connect() as db:
            total = (await (await db.execute("SELECT count(*) FROM products p" + where, params)).fetchone())[0]
            page = max(0, min(page, max(0, (total - 1) // 5)))
            rows = await (await db.execute("SELECT p.*, (SELECT min(price) FROM product_variants v WHERE v.product_id=p.id) AS min_price,"
                                           "(SELECT max(price) FROM product_variants v WHERE v.product_id=p.id) AS max_price "
                                           "FROM products p" + where + " ORDER BY " + order + " LIMIT 5 OFFSET ?", params + [page * 5])).fetchall()
        return [dict(r) for r in rows], total, page

    async def get_setting(self, key, default=""):
        async with self.db.connect() as db:
            row = await one(db, "SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    async def product_metadata(self):
        async with self.db.connect() as db:
            brands = [r[0] for r in await (await db.execute("SELECT DISTINCT brand FROM products ORDER BY casefold(brand)")).fetchall()]
            counts = await (await db.execute("SELECT product_id,count(*) FROM orders WHERE status!='cancelled' GROUP BY product_id ORDER BY count(*) DESC LIMIT 5")).fetchall()
            images = await (await db.execute("SELECT product_id FROM product_images WHERE position=0")).fetchall()
        return brands, [r[0] for r in counts], {r[0] for r in images}

    async def quote_checkout(self, user_id, product_id, revision, color, memory, request_key):
        """A durable idempotency key makes quote retries safe across processes/restarts."""
        async with self.db.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            old = await one(db, "SELECT * FROM checkouts WHERE user_id=? AND request_key=?", (user_id, request_key))
            if old:
                if (old["product_id"], old["revision"], old["color"], old["memory"]) != (product_id, revision, color, memory):
                    raise ValueError("Этот ключ уже использован для другого выбора.")
                if old["state"] != "open" or old["expires_at"] < time.time():
                    raise ValueError("Выбор завершён или устарел. Проверьте «Мои заказы» и обновите товар.")
            p = await load_product(db, product_id)
            if revision != p["revision"]:
                raise ValueError("Товар изменился. Обновите карточку и проверьте актуальную цену.")
            ensure_available(p)
            amount = effective_price(p, color, memory)
            token = old["token"] if old else secrets.token_hex(8)
            if not old:
                await db.execute("INSERT INTO checkouts(token,user_id,product_id,revision,color,memory,expires_at,request_key) VALUES(?,?,?,?,?,?,?,?)",
                                 (token, user_id, product_id, revision, color, memory, int(time.time()) + 3600, request_key))
            d = await one(db, "SELECT * FROM checkouts WHERE token=?", (token,))
            await db.commit()
        return {"token": token, "product_id": p["id"], "product_name": p["name"], "revision": p["revision"],
                "color": color, "memory": memory, "price": amount, "expires_at": d["expires_at"]}

    async def set_setting(self, actor_id, key, value):
        require_admin(actor_id)
        if key not in {"admin_username", "shop_name", "about"}:
            raise ValueError("Неизвестная настройка.")
        async with self.db.connect() as db:
            await db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            await db.commit()

    async def begin_checkout(self, user_id, product_id):
        async with self.db.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            p = await load_product(db, product_id)
            ensure_available(p)
            # One active checkout per buyer; old keyboards cannot create another order.
            await db.execute("UPDATE checkouts SET state='cancelled' WHERE user_id=? AND state='open'", (user_id,))
            token = secrets.token_hex(8)
            await db.execute("INSERT INTO checkouts(token,user_id,product_id,revision,color,memory,expires_at) VALUES(?,?,?,?,?,?,?)",
                             (token, user_id, product_id, p["revision"], p["colors"][0] if len(p["colors"]) == 1 else None,
                              p["memories"][0] if len(p["memories"]) == 1 else None, int(time.time()) + 3600))
            await db.commit()
        return token

    async def _checkout(self, db, user_id, token):
        d = await one(db, "SELECT * FROM checkouts WHERE token=? AND user_id=?", (token, user_id))
        if not d or d["state"] != "open" or d["expires_at"] < time.time():
            raise ValueError("Выбор устарел или отменён. Откройте товар и нажмите «Заказать» заново.")
        p = await load_product(db, d["product_id"])
        if p["revision"] != d["revision"]:
            raise ValueError("Данные товара изменились. Откройте карточку и проверьте новую цену.")
        ensure_available(p)
        return d, p

    async def checkout(self, user_id, token, field=None, index=None):
        async with self.db.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            d, p = await self._checkout(db, user_id, token)
            if field:
                if field not in {"color", "memory"}:
                    raise ValueError("Неверный параметр.")
                values = p["colors"] if field == "color" else p["memories"]
                if index is None or not 0 <= index < len(values) or (field == "memory" and d["color"] is None):
                    raise ValueError("Сначала выберите доступный цвет.")
                # Freeze parameters once chosen; stale color/memory keyboards are harmless.
                if d[field] is not None and d[field] != values[index]:
                    raise ValueError("Параметр уже выбран. Отмените заказ для нового выбора.")
                d[field] = values[index]
                await db.execute(f"UPDATE checkouts SET {field}=? WHERE token=?", (d[field], token))
            await db.commit()
        return d, p

    async def cancel_checkout(self, user_id, token):
        async with self.db.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            d = await one(db, "SELECT state FROM checkouts WHERE token=? AND user_id=?", (token, user_id))
            if d and d["state"] == "confirmed":
                raise ValueError("Заказ уже оформлен. Его статус доступен в «Мои заказы»; для отмены свяжитесь с продавцом.")
            cursor = await db.execute("UPDATE checkouts SET state='cancelled' WHERE token=? AND user_id=? AND state='open'", (token, user_id))
            await db.commit()
            return cursor.rowcount == 1

    async def confirm_order(self, user_id, token):
        async with self.db.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            existing = await one(db, "SELECT * FROM orders WHERE checkout_token=? AND user_id=?", (token, user_id))
            if existing:
                return existing, False
            d, p = await self._checkout(db, user_id, token)
            amount = effective_price(p, d["color"], d["memory"])
            user = await one(db, "SELECT * FROM users WHERE id=?", (user_id,))
            number = "CP-" + secrets.token_hex(6).upper()
            cursor = await db.execute("""INSERT INTO orders(number,checkout_token,user_id,buyer_name,buyer_username,
                product_id,product_name,color,memory,price,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                                     (number, token, user_id, user["full_name"], user["username"], p["id"], p["name"],
                                      d["color"], d["memory"], amount, now()))
            order_id = cursor.lastrowid
            await db.execute("UPDATE checkouts SET state='confirmed' WHERE token=?", (token,))
            await db.execute("INSERT INTO notifications(order_id,kind,target_id) VALUES(?,'new',?)", (order_id, ADMIN_ID))
            order = await one(db, "SELECT * FROM orders WHERE id=?", (order_id,))
            await db.commit()
        return order, True

    async def orders(self, actor_id, page=0, admin=False):
        if admin:
            require_admin(actor_id)
        where, params = ("", []) if admin else (" WHERE user_id=?", [actor_id])
        async with self.db.connect() as db:
            total = (await (await db.execute("SELECT count(*) FROM orders" + where, params)).fetchone())[0]
            page = max(0, min(page, max(0, (total - 1) // 5)))
            rows = await (await db.execute("SELECT * FROM orders" + where + " ORDER BY id DESC LIMIT 5 OFFSET ?", params + [page * 5])).fetchall()
        return [dict(r) for r in rows], total, page

    async def get_order(self, actor_id, order_id, admin=False):
        if admin:
            require_admin(actor_id)
        async with self.db.connect() as db:
            o = await one(db, "SELECT * FROM orders WHERE id=?", (order_id,))
        if not o or (not admin and o["user_id"] != actor_id):
            raise ValueError("Заказ не найден.")
        return o

    async def change_status(self, actor_id, order_id, status):
        require_admin(actor_id)
        if status not in STATUSES:
            raise ValueError("Неизвестный статус заказа.")
        async with self.db.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            o = await one(db, "SELECT * FROM orders WHERE id=?", (order_id,))
            if not o:
                raise ValueError("Заказ не найден.")
            if status == o["status"]:
                return False
            await db.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
            await db.execute("INSERT INTO notifications(order_id,kind,target_id,status) VALUES(?,'status',?,?)", (order_id, o["user_id"], status))
            await db.commit()
        return True

    async def statistics(self, actor_id):
        require_admin(actor_id)
        async with self.db.connect() as db:
            users = (await (await db.execute("SELECT count(*) FROM users")).fetchone())[0]
            products = (await (await db.execute("SELECT count(*) FROM products")).fetchone())[0]
            rows = await (await db.execute("SELECT status,count(*) AS count,coalesce(sum(price),0) AS amount FROM orders GROUP BY status")).fetchall()
            pending = (await (await db.execute("SELECT count(*) FROM notifications WHERE done=0")).fetchone())[0]
        return users, products, [dict(r) for r in rows], pending

    async def claim_notification(self, order_id=None):
        async with self.db.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            query = "SELECT * FROM notifications WHERE done=0 AND next_attempt<=?"
            params = [int(time.time())]
            if order_id is not None:
                query += " AND order_id=?"
                params.append(order_id)
            n = await one(db, query + " ORDER BY id LIMIT 1", params)
            if n:
                await db.execute("UPDATE notifications SET next_attempt=? WHERE id=?", (int(time.time()) + 120, n["id"]))
            await db.commit()
        return n

    async def finish_notification(self, n, error=None, delay=None):
        async with self.db.connect() as db:
            if error:
                await db.execute("UPDATE notifications SET attempts=attempts+1,last_error=?,next_attempt=? WHERE id=?",
                                 (error, int(time.time()) + (delay or min(3600, 30 * 2 ** min(n["attempts"], 7))), n["id"]))
            else:
                await db.execute("UPDATE notifications SET done=1,last_error=NULL WHERE id=?", (n["id"],))
                if n["kind"] == "new":
                    await db.execute("UPDATE orders SET admin_notified=1 WHERE id=?", (n["order_id"],))
            await db.commit()

    async def retry_notifications(self, actor_id):
        require_admin(actor_id)
        async with self.db.connect() as db:
            await db.execute("UPDATE notifications SET next_attempt=0 WHERE done=0")
            await db.commit()

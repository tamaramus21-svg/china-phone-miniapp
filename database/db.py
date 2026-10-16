from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE users (
 id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, username TEXT, created_at TEXT NOT NULL
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE products (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL, brand TEXT NOT NULL, model TEXT NOT NULL,
 short_description TEXT NOT NULL, description TEXT NOT NULL,
 price INTEGER NOT NULL CHECK(price > 0), colors TEXT NOT NULL, memories TEXT NOT NULL,
 specs TEXT NOT NULL, availability TEXT NOT NULL CHECK(availability IN ('in_stock','preorder','out')),
 quantity INTEGER CHECK(quantity >= 0), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE product_images (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
 file_id TEXT NOT NULL, position INTEGER NOT NULL
);
CREATE TABLE product_variants (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
 color TEXT NOT NULL, memory TEXT NOT NULL, price INTEGER NOT NULL CHECK(price > 0),
 UNIQUE(product_id,color,memory)
);
CREATE TABLE checkouts (
 token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 product_id INTEGER NOT NULL, revision INTEGER NOT NULL,
 color TEXT, memory TEXT, expires_at INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','cancelled','confirmed'))
);
CREATE TABLE orders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT NOT NULL UNIQUE,
 checkout_token TEXT NOT NULL UNIQUE REFERENCES checkouts(token),
 user_id INTEGER NOT NULL REFERENCES users(id), buyer_name TEXT NOT NULL, buyer_username TEXT,
 product_id INTEGER NOT NULL, product_name TEXT NOT NULL,
 color TEXT NOT NULL, memory TEXT NOT NULL, price INTEGER NOT NULL CHECK(price > 0),
 created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
 admin_notified INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE notifications (
 id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
 kind TEXT NOT NULL, target_id INTEGER NOT NULL, status TEXT,
 attempts INTEGER NOT NULL DEFAULT 0, next_attempt INTEGER NOT NULL DEFAULT 0,
 done INTEGER NOT NULL DEFAULT 0, last_error TEXT
);
CREATE INDEX orders_user ON orders(user_id,id);
CREATE INDEX notifications_due ON notifications(done,next_attempt);
CREATE INDEX checkouts_user ON checkouts(user_id,state);
"""


class Database:
    def __init__(self, path):
        self.path = Path(path)

    @asynccontextmanager
    async def connect(self):
        async with aiosqlite.connect(self.path, timeout=15) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA busy_timeout=15000")
            await db.create_function("casefold", 1, lambda value: (value or "").casefold(), deterministic=True)
            yield db

    async def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute("PRAGMA user_version")).fetchone()
            version = row[0]
            if version > 2:
                raise RuntimeError("База создана более новой версией. Обновите приложение.")
            if version == 0:
                # Individual statements preserve the migration transaction (executescript commits).
                for sql in SCHEMA.split(";"):
                    if sql.strip():
                        await db.execute(sql)
                await db.execute("PRAGMA user_version=1")
            if version < 2:
                await db.execute("ALTER TABLE checkouts ADD COLUMN request_key TEXT")
                await db.execute("CREATE UNIQUE INDEX checkout_request ON checkouts(user_id,request_key) WHERE request_key IS NOT NULL")
                await db.execute("PRAGMA user_version=2")
            await db.commit()

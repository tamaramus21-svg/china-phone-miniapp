from copy import deepcopy

import pytest
import pytest_asyncio
from aiogram.types import User

from config import ADMIN_ID
from database.db import Database
from database.repository import Repository


@pytest.fixture
def product_data():
    # Synthetic fixtures live only in temporary test databases, never the shop.
    return deepcopy({
        "name": "Тестовый смартфон", "brand": "ТестБренд", "model": "Model T",
        "short_description": "Тестовое краткое описание", "description": "Тестовое полное описание <без HTML>",
        "price": 10000, "images": ["test_photo_1"], "colors": ["Чёрный", "Белый"],
        "memories": ["128 ГБ", "256 ГБ"], "variants": [], "specs": "Тестовые характеристики",
        "quantity": 5, "availability": "in_stock",
    })


@pytest_asyncio.fixture
async def repo(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    await db.initialize()
    repo = Repository(db)
    await repo.upsert_user(User(id=12345, is_bot=False, first_name="Тест", username="test_buyer"))
    await repo.upsert_user(User(id=ADMIN_ID, is_bot=False, first_name="Продавец"))
    return repo


async def ready_checkout(repo, product, user_id=12345):
    token = await repo.begin_checkout(user_id, product["id"])
    d, _ = await repo.checkout(user_id, token)
    if d["color"] is None:
        await repo.checkout(user_id, token, "color", 0)
    if d["memory"] is None:
        await repo.checkout(user_id, token, "memory", 0)
    return token

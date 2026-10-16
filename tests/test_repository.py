import asyncio

import pytest
from aiogram.types import User

from config import ADMIN_ID
from database.db import Database
from database.repository import Repository, effective_price
from bot.services.catalog import checkout_step
from tests.conftest import ready_checkout
from utils.validators import variant_prices


async def test_initialization_is_empty_and_idempotent(repo):
    await repo.db.initialize()
    assert (await repo.products())[1] == 0
    async with repo.db.connect() as db:
        tables = {r[0] for r in await (await db.execute("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
        assert {"products", "product_images", "product_variants", "orders", "users", "settings", "checkouts", "notifications"} <= tables
        assert (await (await db.execute("PRAGMA integrity_check")).fetchone())[0] == "ok"


async def test_reject_newer_schema(repo):
    async with repo.db.connect() as db:
        await db.execute("PRAGMA user_version=999")
    with pytest.raises(RuntimeError):
        await repo.db.initialize()


async def test_product_create_update_delete(repo, product_data):
    p = await repo.save_product(ADMIN_ID, product_data)
    assert p["id"] > 0 and len(p["variants"]) == 4
    assert p["images"] == ["test_photo_1"]
    await repo.db.initialize()
    p["name"] = "Обновлённый товар"
    p = await repo.save_product(ADMIN_ID, p, p["id"], p["revision"])
    assert p["name"] == "Обновлённый товар" and p["revision"] == 2
    with pytest.raises(ValueError):
        await repo.save_product(ADMIN_ID, p, p["id"], 1)
    with pytest.raises(ValueError):
        await repo.delete_product(ADMIN_ID, p["id"], 1)
    await repo.delete_product(ADMIN_ID, p["id"], p["revision"])
    assert (await repo.products())[1] == 0
    async with repo.db.connect() as db:
        assert (await (await db.execute("SELECT count(*) FROM product_images")).fetchone())[0] == 0
        assert (await (await db.execute("SELECT count(*) FROM product_variants")).fetchone())[0] == 0


async def test_admin_permissions_every_mutation(repo, product_data):
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await ready_checkout(repo, p)
    o, _ = await repo.confirm_order(12345, token)
    calls = [repo.save_product(12345, product_data), repo.save_product(12345, p, p["id"]),
             repo.delete_product(12345, p["id"], p["revision"]), repo.set_setting(12345, "about", "bad"),
             repo.change_status(12345, o["id"], "completed"), repo.statistics(12345),
             repo.orders(12345, admin=True), repo.get_order(12345, o["id"], admin=True), repo.retry_notifications(12345)]
    for call in calls:
        with pytest.raises(PermissionError):
            await call


async def test_search_filters_unicode_and_sql_literals(repo, product_data):
    for i in range(7):
        await repo.save_product(ADMIN_ID, dict(product_data, name=f"Товар {i}", price=10000 + i))
    rows, total, page = await repo.products(0, query="тЕсТбРеНд")
    assert len(rows) == 5 and total == 7 and page == 0
    assert len((await repo.products(1))[0]) == 2
    assert (await repo.products(99))[2] == 1
    assert (await repo.products(-2))[2] == 0
    assert (await repo.products(query="MODEL t"))[1] == 7
    assert (await repo.products(query="%' OR 1=1 --"))[1] == 0
    assert (await repo.products(query="%"))[1] == 0
    assert (await repo.products(brand="тестбренд", minimum=10002, maximum=10003))[1] == 2
    p = await repo.save_product(ADMIN_ID, dict(product_data, availability="out", quantity=0))
    assert (await repo.products(available=True))[1] == 7
    with pytest.raises(ValueError):
        await repo.begin_checkout(12345, p["id"])


async def test_memory_and_combination_prices(repo, product_data):
    product_data["variants"] = variant_prices("256 ГБ = 12000\nБелый | 256 ГБ = 13000", product_data["colors"], product_data["memories"])
    p = await repo.save_product(ADMIN_ID, product_data)
    assert effective_price(p, "Чёрный", "128 ГБ") == 10000
    assert effective_price(p, "Чёрный", "256 ГБ") == 12000
    assert effective_price(p, "Белый", "256 ГБ") == 13000
    with pytest.raises(ValueError):
        effective_price(p, "неизвестный", "128 ГБ")
    token = await repo.begin_checkout(12345, p["id"])
    d, p = await repo.checkout(12345, token)
    assert checkout_step(d, p)[0] == "color"
    await repo.checkout(12345, token, "color", 1)
    d, p = await repo.checkout(12345, token)
    assert checkout_step(d, p)[0] == "memory"
    d, p = await repo.checkout(12345, token, "memory", 1)
    assert checkout_step(d, p) == ("confirm", 13000)
    o, _ = await repo.confirm_order(12345, token)
    assert o["price"] == 13000 and o["color"] == "Белый"


async def test_single_options_autoselect_and_no_order_before_confirm(repo, product_data):
    p = await repo.save_product(ADMIN_ID, dict(product_data, colors=["Один цвет"], memories=["Одна память"]))
    token = await repo.begin_checkout(12345, p["id"])
    d, p = await repo.checkout(12345, token)
    assert checkout_step(d, p) == ("confirm", 10000)
    assert (await repo.orders(12345))[1] == 0


async def test_incomplete_selection_cannot_confirm(repo, product_data):
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await repo.begin_checkout(12345, p["id"])
    with pytest.raises(ValueError):
        await repo.confirm_order(12345, token)
    with pytest.raises(ValueError):
        await repo.checkout(12345, token, "memory", 0)
    with pytest.raises(ValueError):
        await repo.checkout(12345, token, "color", -1)
    with pytest.raises(ValueError):
        await repo.checkout(12345, token, "color", 99)


async def test_order_snapshot_survives_changes_and_delete(repo, product_data):
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await ready_checkout(repo, p)
    o, _ = await repo.confirm_order(12345, token)
    p.update(name="Другое название", price=90000)
    p = await repo.save_product(ADMIN_ID, p, p["id"], p["revision"])
    await repo.delete_product(ADMIN_ID, p["id"], p["revision"])
    snapshot = await repo.get_order(12345, o["id"])
    assert snapshot["product_name"] == product_data["name"]
    assert snapshot["price"] == 10000 and snapshot["product_id"] == p["id"]
    repeated, created = await repo.confirm_order(12345, token)
    assert not created and repeated["id"] == o["id"]


async def test_concurrent_duplicate_confirmation(repo, product_data):
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await ready_checkout(repo, p)
    results = await asyncio.gather(*(repo.confirm_order(12345, token) for _ in range(8)))
    assert sum(created for _, created in results) == 1
    assert len({o["number"] for o, _ in results}) == 1
    assert (await repo.orders(12345))[1] == 1
    async with repo.db.connect() as db:
        assert (await (await db.execute("SELECT count(*) FROM notifications")).fetchone())[0] == 1


async def test_stale_cancel_does_not_misrepresent_confirmed_order(repo, product_data):
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await ready_checkout(repo, p)
    o, _ = await repo.confirm_order(12345, token)
    with pytest.raises(ValueError, match="уже оформлен"):
        await repo.cancel_checkout(12345, token)
    assert (await repo.get_order(12345, o["id"]))["status"] == "new"


async def test_ownership_stale_selection_cancel_and_expiry(repo, product_data):
    await repo.upsert_user(User(id=67890, first_name="Другой", is_bot=False))
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await ready_checkout(repo, p)
    with pytest.raises(ValueError):
        await repo.confirm_order(67890, token)
    with pytest.raises(ValueError):
        await repo.checkout(67890, token)
    with pytest.raises(ValueError):
        await repo.checkout(12345, token, "color", 1)
    await repo.cancel_checkout(67890, token)
    await repo.checkout(12345, token)  # Other users cannot cancel it.
    await repo.cancel_checkout(12345, token)
    with pytest.raises(ValueError):
        await repo.confirm_order(12345, token)
    token = await ready_checkout(repo, p)
    async with repo.db.connect() as db:
        await db.execute("UPDATE checkouts SET expires_at=0 WHERE token=?", (token,))
        await db.commit()
    with pytest.raises(ValueError):
        await repo.confirm_order(12345, token)


async def test_product_revision_and_new_checkout_invalidate_old(repo, product_data):
    p = await repo.save_product(ADMIN_ID, product_data)
    old = await ready_checkout(repo, p)
    token = await ready_checkout(repo, p)
    with pytest.raises(ValueError):
        await repo.confirm_order(12345, old)
    p = await repo.save_product(ADMIN_ID, dict(p, price=11000), p["id"], p["revision"])
    with pytest.raises(ValueError, match="изменились"):
        await repo.confirm_order(12345, token)
    token = await ready_checkout(repo, p)
    await repo.delete_product(ADMIN_ID, p["id"], p["revision"])
    with pytest.raises(ValueError):
        await repo.confirm_order(12345, token)


async def test_status_update_and_privacy(repo, product_data):
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await ready_checkout(repo, p)
    o, _ = await repo.confirm_order(12345, token)
    with pytest.raises(ValueError):
        await repo.get_order(67890, o["id"])
    with pytest.raises(ValueError):
        await repo.change_status(ADMIN_ID, o["id"], "paid")
    assert await repo.change_status(ADMIN_ID, o["id"], "confirmed")
    assert not await repo.change_status(ADMIN_ID, o["id"], "confirmed")
    assert (await repo.get_order(12345, o["id"]))["status"] == "confirmed"
    async with repo.db.connect() as db:
        assert (await (await db.execute("SELECT count(*) FROM notifications WHERE kind='status'")).fetchone())[0] == 1


async def test_settings_persist_and_no_stock_reservation(repo, product_data):
    await repo.set_setting(ADMIN_ID, "admin_username", "test_seller")
    assert await Repository(repo.db).get_setting("admin_username") == "test_seller"
    assert await repo.get_setting("about", "default") == "default"
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await ready_checkout(repo, p)
    await repo.confirm_order(12345, token)
    assert (await repo.get_product(p["id"]))["quantity"] == 5


async def test_confirmation_persists_across_repository_restart(repo, product_data):
    p = await repo.save_product(ADMIN_ID, product_data)
    token = await ready_checkout(repo, p)
    new_repo = Repository(Database(repo.db.path))
    await new_repo.db.initialize()
    o, created = await new_repo.confirm_order(12345, token)
    assert created and o["status"] == "new"

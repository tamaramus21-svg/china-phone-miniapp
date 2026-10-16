import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import replace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from bot.keyboards.main import main_menu
from bot.services.order_service import OrderService
from config import ADMIN_ID, Config, webapp_url
from database.db import Database, SCHEMA
from webapp.auth import AuthError, validate_init_data
from webapp.server import ShopApi

TEST_TOKEN = "000000:synthetic-test-secret-never-used-with-telegram"


def signed(user_id=12345, timestamp=None, extra=None):
    fields = {"auth_date": str(int(time.time()) if timestamp is None else timestamp),
              "user": json.dumps({"id": user_id, "first_name": "Тест", "username": "test_user"}, ensure_ascii=False),
              "query_id": "test-query"}
    fields.update(extra or {})
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def headers(user_id=12345, **kwargs):
    return {"Authorization": "tma " + signed(user_id), **kwargs}


@pytest.fixture
def api_config(tmp_path):
    return Config(TEST_TOKEN, tmp_path / "unused", webapp_url="https://test-owner.github.io/china-phone")


@pytest.fixture
async def api_client(aiohttp_client, repo, api_config, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Shop</title>", encoding="utf-8")
    bot = AsyncMock()
    service = OrderService(repo, bot)
    api = ShopApi(repo, api_config, bot, service, dist)
    client = await aiohttp_client(api.app())
    return client, api, bot


def test_valid_hmac_including_unicode_and_signature_field():
    assert validate_init_data(signed(extra={"signature": "some-ed25519-value"}), TEST_TOKEN).id == 12345
    assert validate_init_data(signed(), TEST_TOKEN).first_name == "Тест"


@pytest.mark.parametrize("raw", ["", "a=1", "hash=bad&user={}", "x"*17000,
                                 signed(timestamp=1), signed(timestamp=int(time.time())+100),
                                 signed().replace("12345", "8543142739"), signed()+"&auth_date=0",
                                 signed(user_id=-1), signed(user_id=True)])
def test_reject_invalid_auth(raw):
    with pytest.raises(AuthError):
        validate_init_data(raw, TEST_TOKEN)


def test_reject_other_bot_token():
    with pytest.raises(AuthError):
        validate_init_data(signed(), "another-bot-token")


def test_webapp_buttons_and_https():
    kb = main_menu("https://example.com/shop")
    assert all(b.web_app and b.web_app.url.startswith("https://example.com/shop/#") for row in kb.inline_keyboard for b in row)
    assert webapp_url("https://example.com/shop/") == "https://example.com/shop"
    for value in ["http://example.com", "https://localhost", "https://user:password@example.com", "https://example.com?token=x"]:
        with pytest.raises(ValueError):
            webapp_url(value)


async def test_old_database_migration_preserves_every_table(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    c.execute("INSERT INTO users VALUES(12345,'Old buyer',NULL,'old')")
    c.execute("INSERT INTO settings VALUES('shop_name','Existing store')")
    c.execute("PRAGMA user_version=1")
    c.commit(); c.close()
    db = Database(path)
    await db.initialize(); await db.initialize()
    async with db.connect() as conn:
        assert (await (await conn.execute("PRAGMA user_version")).fetchone())[0] == 2
        assert (await (await conn.execute("SELECT value FROM settings")).fetchone())[0] == "Existing store"
        assert (await (await conn.execute("SELECT full_name FROM users")).fetchone())[0] == "Old buyer"
        assert (await (await conn.execute("PRAGMA integrity_check")).fetchone())[0] == "ok"


async def test_api_auth_ownership_and_private_data(api_client):
    client, _, _ = api_client
    assert (await client.get('/healthz')).status == 200
    assert (await client.get('/api/products')).status == 401
    assert (await client.get('/api/me',headers={"Authorization":"tma "+signed(timestamp=1)})).status == 401
    r = await client.get('/api/me',headers=headers())
    assert (await r.json())["id"] == 12345
    r = await client.get('/api/shop',headers=headers())
    assert (await r.json())["admin_username"] is None
    assert r.headers['Cache-Control'] == 'no-store'
    r = await client.get('/api/products',headers=headers())
    assert (await r.json())["total"] == 0
    assert (await client.get('/api/admin/stats',headers=headers())).status == 403
    assert (await client.get('/api/admin/orders',headers=headers())).status == 403
    assert (await client.patch('/api/admin/orders/1/status',headers=headers(),json={"status":"completed"})).status == 403


async def test_api_catalog_variants_and_media_proxy(api_client, repo, product_data):
    client, _, bot = api_client
    product_data["variants"] = [{"color":"Белый","memory":"256 ГБ","price":13000}]
    p = await repo.save_product(ADMIN_ID, product_data)
    r = await client.get('/api/products?query=ТЕСТ&minimum=12000&maximum=14000',headers=headers())
    result = await r.json()
    assert result["total"] == 1 and "file_id" not in json.dumps(result)
    detail = await (await client.get('/api/products/'+str(p['id']),headers=headers())).json()
    assert detail['images'][0].startswith('/media/products/')
    assert 'test_photo_1' not in json.dumps(detail)
    r = await client.post(f"/api/products/{p['id']}/price",headers=headers(),json={"color":"Белый","memory":"256 ГБ","revision":p['revision']})
    assert (await r.json())['price'] == 13000
    bot.get_file.return_value.file_size = 3
    bot.get_file.return_value.file_path = 'photos/test.jpg'
    async def download(path,destination,timeout):
        destination.write(b'jpg')
    bot.download_file.side_effect = download
    r = await client.get(detail['images'][0])
    assert await r.read() == b'jpg' and r.content_type == 'image/jpeg'
    await client.get(detail['images'][0])
    assert bot.download_file.await_count == 1
    assert (await client.get(f"/media/products/{p['id']}/9")).status == 404


async def quote(client, p, user_id=12345, key='test-request-00000001'):
    return await client.post('/api/quotes', headers=headers(user_id), json={"product_id":p['id'],"revision":p['revision'],"color":"Чёрный","memory":"128 ГБ","request_key":key})


async def test_api_order_concurrency_snapshot_notification_and_status(api_client, repo, product_data):
    client, _, bot = api_client
    p = await repo.save_product(ADMIN_ID, product_data)
    responses = await asyncio.gather(*(quote(client,p) for _ in range(4)))
    quotes = [await r.json() for r in responses]
    assert len({q['token'] for q in quotes}) == 1
    token = quotes[0]['token']
    assert (await repo.orders(12345))[1] == 0
    assert (await client.post('/api/orders',headers=headers(),json={"quote_token":token,"price":1})).status == 400
    assert (await client.post('/api/orders',headers=headers(777),json={"quote_token":token})).status == 409
    bot.send_message.side_effect = TelegramForbiddenError(method=SendMessage(chat_id=ADMIN_ID,text='x'),message='cannot deliver')
    results = await asyncio.gather(*(client.post('/api/orders',headers=headers(),json={"quote_token":token}) for _ in range(4)))
    assert sorted(r.status for r in results) == [200,200,200,201]
    orders = [(await r.json())['order'] for r in results]
    assert len({o['number'] for o in orders}) == 1
    o = orders[0]
    assert not o['admin_notified'] and o['price'] == 10000
    assert 'user_id' not in o and 'checkout_token' not in o
    assert (await client.get('/api/orders/'+str(o['id']),headers=headers(777))).status == 409
    assert (await (await client.get('/api/orders',headers=headers(777))).json())['total'] == 0
    await repo.delete_product(ADMIN_ID,p['id'],p['revision'])
    snapshot = await (await client.get('/api/orders/'+str(o['id']),headers=headers())).json()
    assert snapshot['product_name'] == product_data['name']
    bot.send_message.side_effect = None
    r = await client.patch(f"/api/admin/orders/{o['id']}/status",headers=headers(ADMIN_ID),json={'status':'shipped'})
    assert (await r.json())['status'] == 'shipped'


async def test_api_detects_changed_product_and_invalid_parameters(api_client, repo, product_data):
    client, _, _ = api_client
    p = await repo.save_product(ADMIN_ID,product_data)
    q = await (await quote(client,p)).json()
    await repo.save_product(ADMIN_ID,dict(p,price=15000),p['id'],p['revision'])
    assert (await client.post('/api/orders',headers=headers(),json={'quote_token':q['token']})).status == 409
    assert (await quote(client,p,key='test-request-00000002')).status == 409
    for query in ['page=-1','minimum=0','available=oops','user_id=8543142739','minimum=100&maximum=10','sort=bad']:
        assert (await client.get('/api/products?'+query,headers=headers())).status in {400,409}
    assert (await client.post('/api/quotes',headers=headers(),data='x')).status == 415
    assert (await client.post('/api/orders',headers=headers(),data='{'+'x'*40000,skip_auto_headers=['Content-Type'])).status == 415
    assert (await client.post('/api/orders',headers={**headers(),'Content-Type':'application/json'},data='x'*40000)).status == 413
    assert (await client.get('/api/products',headers={"Authorization":"tma "+signed().replace('auth_date','auth_dato')})).status == 401


async def test_cors_only_configured_pages_origin_and_static(api_client):
    client, _, _ = api_client
    r = await client.options('/api/orders',headers={'Origin':'https://test-owner.github.io','Access-Control-Request-Headers':'Authorization,Content-Type'})
    assert r.status == 204 and r.headers['Access-Control-Allow-Origin'] == 'https://test-owner.github.io'
    assert (await client.options('/api/orders',headers={'Origin':'https://evil.example'})).status == 403
    r = await client.get('/api/me',headers=headers(Origin='https://test-owner.github.io'))
    assert r.status == 200 and r.headers['Access-Control-Allow-Origin'] == 'https://test-owner.github.io'
    assert (await client.get('/api/me',headers=headers(Origin='https://evil.example'))).status == 403
    assert (await client.get('/')).status == 200
    assert (await client.get('/config.py')).status == 404
    assert (await client.get('/.env')).status == 404


async def test_rate_limit(api_client):
    client, api, _ = api_client
    api.rate[('user',12345)] = (time.monotonic(),181)
    assert (await client.get('/api/me',headers=headers())).status == 429

import logging
from copy import deepcopy

import pytest

from bot.handlers.admin import parse_field
from bot.keyboards.main import contact_keyboard
from main import SecretFilter
from utils.validators import price, options, stock, username, variant_prices, validate_product


@pytest.mark.parametrize("value", ["", "0", "-1", "12.5", "1e3", "NaN", "inf", "1_000", "1000000001", None, "９９"])
def test_invalid_price(value):
    with pytest.raises(ValueError):
        price(value)


@pytest.mark.parametrize("value,expected", [("85 000", 85000), (1, 1), ("1000000000", 1000000000)])
def test_valid_price(value, expected):
    assert price(value) == expected


@pytest.mark.parametrize("value", ["", "Красный,красный", "a|b", "x=y", "a,,b", ",".join(str(i) for i in range(13))])
def test_invalid_options(value):
    with pytest.raises(ValueError):
        options(value)


def test_stock():
    assert stock("0") == {"availability": "out", "quantity": 0}
    assert stock("7")["quantity"] == 7
    assert stock("под заказ") == {"availability": "preorder", "quantity": None}
    with pytest.raises(ValueError):
        stock("-1")
    with pytest.raises(ValueError):
        stock("много")


@pytest.mark.parametrize("value", ["https://t.me/test_seller", "8543142739", "a", "wrong user", "тестовый"])
def test_invalid_username(value):
    with pytest.raises(ValueError):
        username(value)


def test_username_and_contact_links():
    assert username("@test_seller") == "test_seller"
    assert username("") == ""
    none = contact_keyboard("", "x" * 400)
    assert all(b.url is None for r in none.inline_keyboard for b in r)
    kb = contact_keyboard("test_seller", "текст & ?")
    assert kb.inline_keyboard[0][0].url.startswith("https://t.me/test_seller?text=")
    assert "%26" in kb.inline_keyboard[0][0].url
    short = contact_keyboard("", "коротко")
    assert short.inline_keyboard[0][0].copy_text.text == "коротко"


@pytest.mark.parametrize("field,value", [("name", ""), ("description", "x" * 1601), ("images", []), ("images", ["x"] * 11),
                                        ("price", 0), ("quantity", -1), ("availability", "unknown"), ("colors", [])])
def test_invalid_product(field, value, product_data):
    product_data[field] = value
    with pytest.raises(ValueError):
        validate_product(product_data)


@pytest.mark.parametrize("value", ["Unknown = 1", "Красный | 128 ГБ = 1", "128 ГБ = 1\n128 ГБ = 2", "128 ГБ = -1", "bad"])
def test_invalid_variant_prices(value):
    with pytest.raises(ValueError):
        variant_prices(value, ["Чёрный"], ["128 ГБ"])


def test_editing_options_clears_old_prices(product_data):
    assert parse_field("colors", "Зелёный", product_data) == {"colors": ["Зелёный"], "variants": []}


def test_log_filter_redacts_secrets():
    secret = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"
    record = logging.LogRecord("test", logging.ERROR, "", 0, "failure %s", (secret,), None)
    assert SecretFilter(secret).filter(record)
    assert secret not in record.getMessage() and "REDACTED" in record.getMessage()

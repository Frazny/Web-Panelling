"""Güvenlik düzeltmeleri için testler.

- ``_safe_eval``: /hesapla komutundaki eval açığının kapatıldığını doğrular.
- ``database.get_user_open_ticket``: açık ticket sınırı mantığını doğrular.
"""

import pytest

from conftest import run
from cogs.utility import _safe_eval


# ---------------------------------------------------------------------------
# _safe_eval — güvenli hesap makinesi
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("2+3", 5),
        ("2*3+4", 10),
        ("(1+2)**2", 9),
        ("-5+3", -2),
        ("10/4", 2.5),
        ("7//2", 3),
        ("7%2", 1),
        ("2**10", 1024),
        ("1.5*2", 3.0),
        ("(10-2)/4", 2.0),
    ],
)
def test_safe_eval_valid(expr, expected):
    assert _safe_eval(expr) == expected


@pytest.mark.parametrize(
    "expr",
    [
        'open("config.json")',
        "().__class__",
        "[].__class__.__mro__",
        "__import__('os')",
        "1/0",
        "10**100000",
        "2**1000000",
        "'a'*100",
        "True+1",
        "len([])",
        "sum([1,2])",
        "9**9**9",
    ],
)
def test_safe_eval_rejects_dangerous(expr):
    with pytest.raises(Exception):
        _safe_eval(expr)


def test_safe_eval_rejects_names():
    with pytest.raises(Exception):
        _safe_eval("x + 1")


def test_safe_eval_rejects_syntax():
    with pytest.raises(Exception):
        _safe_eval("2 +")


# ---------------------------------------------------------------------------
# get_user_open_ticket — açık ticket sınırı
# ---------------------------------------------------------------------------


def test_open_ticket_limit(db):
    gid, uid = 111, 222
    assert run(db.get_user_open_ticket(gid, uid)) is None

    run(db.create_ticket(gid, 555, uid))
    assert run(db.get_user_open_ticket(gid, uid)) == 555

    run(db.close_ticket(gid, 555))
    assert run(db.get_user_open_ticket(gid, uid)) is None

    # Kullanıcı A'nın açık ticket'ı kullanıcı B'yi etkilememeli
    run(db.create_ticket(gid, 555, uid))
    run(db.create_ticket(gid, 666, uid + 1))
    assert run(db.get_user_open_ticket(gid, uid)) == 555

"""pytest ortak kurulumu (fixture'lar).

Bu dosya botun kök dizinini sys.path'e ekler ve her test için
*geçici* bir SQLite veritabanı kurar. Böylece gerçek ``data/bot.db``
dosyasına asla dokunulmaz.
"""

import asyncio
import sys
from pathlib import Path

import pytest

BOT_ROOT = Path(__file__).resolve().parents[1]
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

import database  # noqa: E402


def run(coro):
    """Kısayol: async fonksiyonu senkron test içinde çalıştırır."""
    return asyncio.run(coro)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Geçici veritabanını kurar ve ``database`` modülünü döndürür."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    run(database.init_db())
    return database

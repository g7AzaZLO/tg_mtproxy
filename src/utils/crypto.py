"""Утилиты для генерации секретов и формирования прокси-ссылок.

Секреты хранятся в БД и конфиге mtprotoproxy как чистые 32 hex-символа (16 байт).
Префикс ``dd`` (secure-режим) добавляется при формировании ссылки для пользователя.
"""

import secrets
from urllib.parse import urlencode

DD_PREFIX = "dd"


def generate_secret() -> str:
    """Генерирует случайный секрет для MTProxy.

    Формат: 32 hex-символа (16 случайных байт).
    Этот секрет записывается в конфиг mtprotoproxy и в БД.

    Returns:
        Строка секрета длиной 32 символа (например, a1b2c3d4...).
    """
    return secrets.token_hex(16)


def build_proxy_link(host: str, port: int, secret: str) -> str:
    """Формирует deep-link для автоматического добавления прокси в Telegram.

    Использует dd-префикс (secure-режим с random padding).

    Args:
        host: IP-адрес или домен сервера.
        port: Порт MTProxy.
        secret: Чистый секрет (32 hex, без dd-префикса).

    Returns:
        Ссылка вида ``tg://proxy?server=HOST&port=PORT&secret=ddSECRET``.
    """
    dd_secret = f"{DD_PREFIX}{secret}"
    params = urlencode({"server": host, "port": port, "secret": dd_secret})
    return f"tg://proxy?{params}"


def build_proxy_link_https(host: str, port: int, secret: str) -> str:
    """Формирует HTTPS-ссылку для добавления прокси в Telegram.

    Эта ссылка работает как fallback, если ``tg://`` не открывается.

    Args:
        host: IP-адрес или домен сервера.
        port: Порт MTProxy.
        secret: Чистый секрет (32 hex, без dd-префикса).

    Returns:
        Ссылка вида ``https://t.me/proxy?server=HOST&port=PORT&secret=ddSECRET``.
    """
    dd_secret = f"{DD_PREFIX}{secret}"
    params = urlencode({"server": host, "port": port, "secret": dd_secret})
    return f"https://t.me/proxy?{params}"

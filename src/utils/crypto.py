"""Утилиты для генерации секретов и формирования прокси-ссылок.

Секреты формата fake-TLS (dd-prefix) обеспечивают маскировку
MTProto-трафика под HTTPS, что помогает обходить DPI.
"""

import secrets
from urllib.parse import urlencode


def generate_secret() -> str:
    """Генерирует случайный dd-секрет для fake-TLS MTProxy.

    Формат: dd + 32 hex-символа (16 случайных байт).
    Префикс dd указывает mtprotoproxy использовать fake-TLS.

    Returns:
        Строка секрета длиной 34 символа (например, dd1234abcd...).
    """
    random_bytes = secrets.token_hex(16)
    return f"dd{random_bytes}"


def build_proxy_link(host: str, port: int, secret: str) -> str:
    """Формирует deep-link для автоматического добавления прокси в Telegram.

    Args:
        host: IP-адрес или домен сервера.
        port: Порт MTProxy.
        secret: Секрет (dd-формат).

    Returns:
        Ссылка вида tg://proxy?server=HOST&port=PORT&secret=SECRET.
    """
    params = urlencode({"server": host, "port": port, "secret": secret})
    return f"tg://proxy?{params}"


def build_proxy_link_https(host: str, port: int, secret: str) -> str:
    """Формирует HTTPS-ссылку для добавления прокси в Telegram.

    Эта ссылка работает как fallback, если tg:// не открывается.

    Args:
        host: IP-адрес или домен сервера.
        port: Порт MTProxy.
        secret: Секрет (dd-формат).

    Returns:
        Ссылка вида https://t.me/proxy?server=HOST&port=PORT&secret=SECRET.
    """
    params = urlencode({"server": host, "port": port, "secret": secret})
    return f"https://t.me/proxy?{params}"

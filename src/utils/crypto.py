"""Утилиты для генерации секретов и формирования прокси-ссылок.

Секреты хранятся в БД и конфиге mtprotoproxy как чистые 32 hex-символа (16 байт).
Префикс ``ee`` (FakeTLS-режим) + hex-кодировка TLS-домена добавляются
при формировании ссылки для пользователя.
"""

import secrets
from urllib.parse import urlencode

EE_PREFIX = "ee"
DEFAULT_TLS_DOMAIN = "ya.ru"


def generate_secret() -> str:
    """Генерирует случайный секрет для MTProxy.

    Формат: 32 hex-символа (16 случайных байт).
    Этот секрет записывается в конфиг mtprotoproxy и в БД.

    Returns:
        Строка секрета длиной 32 символа (например, a1b2c3d4...).
    """
    return secrets.token_hex(16)


def _make_ee_secret(secret: str, tls_domain: str = DEFAULT_TLS_DOMAIN) -> str:
    """Формирует ee-секрет для ссылки: ``ee`` + hex(secret) + hex(domain).

    Args:
        secret: Чистый секрет (32 hex).
        tls_domain: Домен для FakeTLS-маскировки.

    Returns:
        Полный ee-секрет для использования в прокси-ссылке.
    """
    domain_hex = tls_domain.encode().hex()
    return f"{EE_PREFIX}{secret}{domain_hex}"


def build_proxy_link(
    host: str,
    port: int,
    secret: str,
    tls_domain: str = DEFAULT_TLS_DOMAIN,
) -> str:
    """Формирует deep-link для автоматического добавления прокси в Telegram.

    Использует ee-префикс (FakeTLS-режим).

    Args:
        host: IP-адрес или домен сервера.
        port: Порт MTProxy.
        secret: Чистый секрет (32 hex, без префикса).
        tls_domain: Домен для FakeTLS-маскировки.

    Returns:
        Ссылка вида ``tg://proxy?server=HOST&port=PORT&secret=eeSECRET+DOMAIN``.
    """
    ee_secret = _make_ee_secret(secret, tls_domain)
    params = urlencode({"server": host, "port": port, "secret": ee_secret})
    return f"tg://proxy?{params}"


def build_proxy_link_https(
    host: str,
    port: int,
    secret: str,
    tls_domain: str = DEFAULT_TLS_DOMAIN,
) -> str:
    """Формирует HTTPS-ссылку для добавления прокси в Telegram.

    Эта ссылка работает как fallback, если ``tg://`` не открывается.

    Args:
        host: IP-адрес или домен сервера.
        port: Порт MTProxy.
        secret: Чистый секрет (32 hex, без префикса).
        tls_domain: Домен для FakeTLS-маскировки.

    Returns:
        Ссылка вида ``https://t.me/proxy?server=HOST&port=PORT&secret=eeSECRET+DOMAIN``.
    """
    ee_secret = _make_ee_secret(secret, tls_domain)
    params = urlencode({"server": host, "port": port, "secret": ee_secret})
    return f"https://t.me/proxy?{params}"

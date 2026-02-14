"""Сервис прокси — генерация секретов и формирование ссылок."""

from src.utils.crypto import (
    DEFAULT_TLS_DOMAIN,
    build_proxy_link,
    build_proxy_link_https,
    generate_secret,
)


def create_proxy_credentials(
    host: str,
    port: int,
    tls_domain: str = DEFAULT_TLS_DOMAIN,
) -> dict[str, str]:
    """Генерирует секрет и формирует все ссылки для прокси.

    Args:
        host: IP-адрес или домен сервера MTProxy.
        port: Порт MTProxy.
        tls_domain: Домен-маскировка для fake-TLS.

    Returns:
        Словарь с ключами secret, tg_link, https_link.
    """
    secret = generate_secret()
    return {
        "secret": secret,
        "tg_link": build_proxy_link(host, port, secret, tls_domain),
        "https_link": build_proxy_link_https(host, port, secret, tls_domain),
    }


def format_proxy_message(
    *,
    node_name: str,
    country_flag: str,
    plan_name: str,
    expires_at: str,
    tg_link: str,
    https_link: str,
) -> str:
    """Формирует текстовое сообщение с данными прокси для пользователя.

    Args:
        node_name: Имя ноды.
        country_flag: Эмодзи-флаг страны.
        plan_name: Название тарифного плана.
        expires_at: Дата окончания подписки (строка).
        tg_link: Deep-link tg://proxy?...
        https_link: HTTPS-ссылка https://t.me/proxy?...

    Returns:
        Отформатированное сообщение для отправки в Telegram.
    """
    return (
        f"{country_flag} <b>Прокси готов!</b>\n\n"
        f"Сервер: <b>{node_name}</b>\n"
        f"Тариф: <b>{plan_name}</b>\n"
        f"Действует до: <b>{expires_at}</b>\n\n"
        f"Нажмите кнопку ниже для автоматического подключения, "
        f"или скопируйте ссылку:\n\n"
        f"<code>{https_link}</code>"
    )

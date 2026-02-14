"""Сервис прокси — генерация секретов и формирование сообщений."""

from src.utils.crypto import build_proxy_link, build_proxy_link_https, generate_secret


def create_proxy_credentials(host: str, port: int) -> dict[str, str]:
    """Генерирует секрет и формирует ссылки для подключения прокси.

    Args:
        host: IP-адрес или домен сервера MTProxy.
        port: Порт MTProxy.

    Returns:
        Словарь с ключами ``secret``, ``tg_link`` и ``https_link``.
    """
    secret = generate_secret()
    return {
        "secret": secret,
        "tg_link": build_proxy_link(host, port, secret),
        "https_link": build_proxy_link_https(host, port, secret),
    }


def get_proxy_usage_rules() -> str:
    """Возвращает правила использования прокси для пользователя.

    Returns:
        HTML-текст с правилами использования.
    """
    return (
        "<b>Правила использования прокси:</b>\n"
        "• Не используйте этот прокси одновременно с VPN на всю систему.\n"
        "• Первое подключение может занимать до 1 минуты.\n"
        "• Смена ключа и страны доступна не чаще 1 раза в 24 часа.\n"
        "• Перед сменой ключа отключите текущее прокси в Telegram.\n"
        "• Используйте один активный прокси-профиль в Telegram.\n"
        "• Если после смены не работает, удалите старый профиль "
        "и добавьте новый по свежей ссылке."
    )


def format_proxy_message(
    *,
    node_name: str,
    country_flag: str,
    plan_name: str,
    expires_at: str,
    tg_link: str,
    https_link: str,
) -> str:
    """Формирует сообщение с параметрами активированного прокси.

    Args:
        node_name: Имя ноды.
        country_flag: Флаг страны ноды.
        plan_name: Название тарифа.
        expires_at: Дата окончания подписки.
        tg_link: Deep-link ``tg://proxy?...`` (не используется в тексте).
        https_link: HTTPS-ссылка ``https://t.me/proxy?...``.

    Returns:
        Готовый HTML-текст для отправки пользователю.
    """
    _ = tg_link
    return (
        f"{country_flag} <b>Прокси готов!</b>\n\n"
        f"Сервер: <b>{node_name}</b>\n"
        f"Тариф: <b>{plan_name}</b>\n"
        f"Действует до: <b>{expires_at}</b>\n\n"
        "Нажмите кнопку ниже для автоматического подключения, "
        "или скопируйте ссылку:\n\n"
        f"<code>{https_link}</code>"
    )

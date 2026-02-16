"""CallbackData factories для inline-кнопок бота.

Каждая фабрика определяет структуру данных,
передаваемых через callback_data в inline-кнопках.
"""

from aiogram.filters.callback_data import CallbackData


class ProxyTypeCallback(CallbackData, prefix="ptype"):
    """Выбор типа прокси (MTProto / SOCKS5).

    Attributes:
        proxy_type: Тип прокси — ``mtproto`` или ``socks5``.
    """

    proxy_type: str


class LocationCallback(CallbackData, prefix="loc"):
    """Выбор локации (страны) для прокси.

    Attributes:
        country: Название страны.
        proxy_type: Тип прокси.
    """

    country: str
    proxy_type: str = "mtproto"


class PlanCallback(CallbackData, prefix="plan"):
    """Выбор тарифного плана.

    Attributes:
        plan_id: ID тарифного плана.
        country: Выбранная страна.
        proxy_type: Тип прокси.
    """

    plan_id: int
    country: str
    proxy_type: str = "mtproto"


class ConfirmPurchaseCallback(CallbackData, prefix="buy"):
    """Подтверждение покупки.

    Attributes:
        plan_id: ID тарифного плана.
        node_id: ID выбранной ноды.
        proxy_type: Тип прокси.
    """

    plan_id: int
    node_id: int
    proxy_type: str = "mtproto"


class MyProxiesCallback(CallbackData, prefix="proxy"):
    """Навигация в разделе «Мои прокси».

    Attributes:
        action: Действие (list, detail, refresh, rotate).
        subscription_id: ID подписки (для detail / rotate).
    """

    action: str
    subscription_id: int = 0


class AdminCallback(CallbackData, prefix="adm"):
    """Навигация в админ-разделе бота.

    Attributes:
        action: Действие (users, nodes, stats, ban, unban).
        target_id: ID целевого объекта.
    """

    action: str
    target_id: int = 0


class RotateCallback(CallbackData, prefix="rot"):
    """Выбор страны при ротации ключа.

    Attributes:
        subscription_id: ID подписки для ротации.
        country: Новая страна.
    """

    subscription_id: int
    country: str


class BackCallback(CallbackData, prefix="back"):
    """Кнопка «Назад» для возврата в предыдущее меню.

    Attributes:
        to: Куда вернуться (main, locations, plans).
    """

    to: str

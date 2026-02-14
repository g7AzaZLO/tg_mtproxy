"""CallbackData factories для inline-кнопок бота.

Каждая фабрика определяет структуру данных,
передаваемых через callback_data в inline-кнопках.
"""

from aiogram.filters.callback_data import CallbackData


class LocationCallback(CallbackData, prefix="loc"):
    """Выбор локации (страны) для прокси.

    Attributes:
        country: Название страны.
    """

    country: str


class PlanCallback(CallbackData, prefix="plan"):
    """Выбор тарифного плана.

    Attributes:
        plan_id: ID тарифного плана.
        country: Выбранная страна.
    """

    plan_id: int
    country: str


class ConfirmPurchaseCallback(CallbackData, prefix="buy"):
    """Подтверждение покупки.

    Attributes:
        plan_id: ID тарифного плана.
        node_id: ID выбранной ноды.
    """

    plan_id: int
    node_id: int


class MyProxiesCallback(CallbackData, prefix="proxy"):
    """Навигация в разделе «Мои прокси».

    Attributes:
        action: Действие (list, detail, refresh).
        subscription_id: ID подписки (для detail).
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

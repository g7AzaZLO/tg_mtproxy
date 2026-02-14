"""Inline-клавиатуры для навигации бота.

Все клавиатуры формируются динамически на основе данных из БД.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.bot.callbacks.factories import (
    BackCallback,
    ConfirmPurchaseCallback,
    LocationCallback,
    MyProxiesCallback,
    PlanCallback,
    RotateCallback,
)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню бота.

    Returns:
        Клавиатура с основными действиями.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Купить прокси", callback_data="buy_start"),
    )
    builder.row(
        InlineKeyboardButton(
            text="Мои прокси",
            callback_data=MyProxiesCallback(action="list").pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(text="Пробный период", callback_data="trial_start"),
    )
    builder.row(
        InlineKeyboardButton(text="Правила использования", callback_data="proxy_rules"),
    )
    return builder.as_markup()


def locations_keyboard(countries: list[dict]) -> InlineKeyboardMarkup:
    """Клавиатура выбора локации (страны).

    Args:
        countries: Список словарей с полями country и country_flag.

    Returns:
        Клавиатура с кнопками стран.
    """
    builder = InlineKeyboardBuilder()
    for item in countries:
        text = f"{item['country_flag']} {item['country']}"
        builder.row(
            InlineKeyboardButton(
                text=text,
                callback_data=LocationCallback(country=item["country"]).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="« Назад",
            callback_data=BackCallback(to="main").pack(),
        )
    )
    return builder.as_markup()


def plans_keyboard(
    plans: list[dict],
    country: str,
    *,
    show_trial: bool = False,
) -> InlineKeyboardMarkup:
    """Клавиатура выбора тарифного плана.

    Args:
        plans: Список тарифных планов.
        country: Выбранная страна (для передачи в callback).
        show_trial: Показывать ли пробный тариф.

    Returns:
        Клавиатура с кнопками планов.
    """
    builder = InlineKeyboardBuilder()
    for plan in plans:
        if plan["is_trial"] and not show_trial:
            continue
        price_text = "Бесплатно" if plan["is_trial"] else f"${plan['price_usd']}"
        text = f"{plan['name']} — {price_text}"
        builder.row(
            InlineKeyboardButton(
                text=text,
                callback_data=PlanCallback(
                    plan_id=plan["id"],
                    country=country,
                ).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="« Назад к локациям",
            callback_data=BackCallback(to="locations").pack(),
        )
    )
    return builder.as_markup()


def confirm_purchase_keyboard(
    plan_id: int,
    node_id: int,
) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения покупки.

    Args:
        plan_id: ID тарифного плана.
        node_id: ID выбранной ноды.

    Returns:
        Клавиатура с кнопками подтверждения и отмены.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Подтвердить",
            callback_data=ConfirmPurchaseCallback(
                plan_id=plan_id,
                node_id=node_id,
            ).pack(),
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="« Отмена",
            callback_data=BackCallback(to="main").pack(),
        )
    )
    return builder.as_markup()


def payment_keyboard(payment_link: str) -> InlineKeyboardMarkup:
    """Клавиатура со ссылкой на оплату.

    Args:
        payment_link: URL страницы оплаты CryptoCloud.

    Returns:
        Клавиатура с кнопкой-ссылкой на оплату.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Оплатить", url=payment_link),
    )
    builder.row(
        InlineKeyboardButton(
            text="« Главное меню",
            callback_data=BackCallback(to="main").pack(),
        )
    )
    return builder.as_markup()


def proxy_link_keyboard(tg_link: str) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой подключения прокси.

    Args:
        tg_link: Deep-link tg://proxy?...

    Returns:
        Клавиатура с кнопкой-ссылкой для автоподключения.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Подключить прокси", url=tg_link),
    )
    builder.row(
        InlineKeyboardButton(
            text="Мои прокси",
            callback_data=MyProxiesCallback(action="list").pack(),
        ),
    )
    return builder.as_markup()


def my_proxies_keyboard(subscriptions: list[dict]) -> InlineKeyboardMarkup:
    """Клавиатура со списком активных прокси пользователя.

    Для каждой подписки: кнопка-ссылка на подключение
    и кнопка «Сменить ключ» для ротации секрета / смены локации.

    Args:
        subscriptions: Список активных подписок.

    Returns:
        Клавиатура с кнопками для каждого прокси.
    """
    builder = InlineKeyboardBuilder()
    for sub in subscriptions:
        flag = sub.get("country_flag", "")
        name = sub.get("node_name", "Сервер")
        expires = sub["expires_at"].strftime("%d.%m.%Y")
        builder.row(
            InlineKeyboardButton(
                text=f"{flag} {name} (до {expires})",
                url=sub["https_link"],
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="🔄 Сменить ключ",
                callback_data=MyProxiesCallback(
                    action="rotate",
                    subscription_id=sub["id"],
                ).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="« Главное меню",
            callback_data=BackCallback(to="main").pack(),
        )
    )
    return builder.as_markup()


def rotate_locations_keyboard(
    countries: list[dict],
    subscription_id: int,
    current_country: str,
) -> InlineKeyboardMarkup:
    """Клавиатура выбора страны при ротации ключа.

    Текущая страна помечается галочкой.

    Args:
        countries: Список словарей с полями country и country_flag.
        subscription_id: ID подписки.
        current_country: Текущая страна подписки.

    Returns:
        Клавиатура с кнопками стран для ротации.
    """
    builder = InlineKeyboardBuilder()
    for item in countries:
        mark = " ✓" if item["country"] == current_country else ""
        text = f"{item['country_flag']} {item['country']}{mark}"
        builder.row(
            InlineKeyboardButton(
                text=text,
                callback_data=RotateCallback(
                    subscription_id=subscription_id,
                    country=item["country"],
                ).pack(),
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="« Назад к прокси",
            callback_data=MyProxiesCallback(action="list").pack(),
        )
    )
    return builder.as_markup()

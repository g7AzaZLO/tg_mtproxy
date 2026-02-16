"""Хэндлеры процесса покупки прокси.

Пайплайн: выбор типа -> выбор локации -> выбор тарифа -> подтверждение -> оплата.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.bot.callbacks.factories import (
    BackCallback,
    ConfirmPurchaseCallback,
    LocationCallback,
    PlanCallback,
    ProxyTypeCallback,
)
from src.bot.keyboards.menus import (
    confirm_purchase_keyboard,
    locations_keyboard,
    payment_keyboard,
    plans_keyboard,
    proxy_link_keyboard,
    proxy_type_keyboard,
    socks5_credentials_keyboard,
)
from src.db import repositories as repo
from src.services.payment import PaymentError, PaymentService
from src.services.proxy import build_socks5_link, format_proxy_message, format_socks5_message
from src.services.subscription import SubscriptionService

logger = logging.getLogger(__name__)

router = Router(name="buy")


# ------------------------------------------------------------------
# Шаг 0: выбор типа прокси
# ------------------------------------------------------------------

@router.callback_query(F.data == "buy_start")
async def start_purchase(callback: CallbackQuery) -> None:
    """Начало процесса покупки — выбор типа прокси.

    Args:
        callback: Callback-запрос.
    """
    await callback.message.edit_text(
        "<b>Выберите тип прокси:</b>\n\n"
        "🔒 <b>MTProto</b>\n"
        "• Внутренний протокол Telegram.\n"
        "• Высокая надежность и шифрование.\n"
        "• Рекомендуется для ПК с проводным интернетом.\n"
        "• <b>Не рекомендуется для использования на телефоне</b> (медленное соединение).\n\n"
        "🧦 <b>SOCKS5</b>\n"
        "• Универсальный скоростной протокол.\n"
        "• Отлично подходит для телефонов и любых устройств.\n"
        "• Быстрое подключение и высокая скорость.",
        reply_markup=proxy_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(BackCallback.filter(F.to == "proxy_type"))
async def back_to_proxy_type(callback: CallbackQuery) -> None:
    """Возврат к выбору типа прокси.

    Args:
        callback: Callback-запрос.
    """
    await callback.message.edit_text(
        "<b>Выберите тип прокси:</b>\n\n"
        "🔒 <b>MTProto</b>\n"
        "• Внутренний протокол Telegram.\n"
        "• Высокая надежность и шифрование.\n"
        "• Рекомендуется для ПК с проводным интернетом.\n"
        "• <b>Не рекомендуется для использования на телефоне</b> (медленное соединение).\n\n"
        "🧦 <b>SOCKS5</b>\n"
        "• Универсальный скоростной протокол.\n"
        "• Отлично подходит для телефонов и любых устройств.\n"
        "• Быстрое подключение и высокая скорость.",
        reply_markup=proxy_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ------------------------------------------------------------------
# Шаг 1: выбор локации
# ------------------------------------------------------------------

@router.callback_query(ProxyTypeCallback.filter())
async def select_proxy_type(
    callback: CallbackQuery,
    callback_data: ProxyTypeCallback,
) -> None:
    """Выбор типа прокси — показ доступных локаций.

    Args:
        callback: Callback-запрос.
        callback_data: Данные выбранного типа прокси.
    """
    countries = await repo.node.get_available_countries()
    if not countries:
        await callback.answer("Нет доступных серверов. Попробуйте позже.", show_alert=True)
        return

    type_label = "SOCKS5" if callback_data.proxy_type == "socks5" else "MTProto"
    await callback.message.edit_text(
        f"Тип: <b>{type_label}</b>\n\n"
        "Выберите локацию прокси-сервера:",
        reply_markup=locations_keyboard(countries, proxy_type=callback_data.proxy_type),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(BackCallback.filter(F.to == "locations"))
async def back_to_locations(callback: CallbackQuery) -> None:
    """Возврат к выбору типа прокси (из выбора тарифа).

    Args:
        callback: Callback-запрос.
    """
    await callback.message.edit_text(
        "<b>Выберите тип прокси:</b>\n\n"
        "🔒 <b>MTProto</b>\n"
        "• Внутренний протокол Telegram.\n"
        "• Высокая надежность и шифрование.\n"
        "• Рекомендуется для ПК с проводным интернетом.\n"
        "• <b>Не рекомендуется для использования на телефоне</b> (медленное соединение).\n\n"
        "🧦 <b>SOCKS5</b>\n"
        "• Универсальный скоростной протокол.\n"
        "• Отлично подходит для телефонов и любых устройств.\n"
        "• Быстрое подключение и высокая скорость.",
        reply_markup=proxy_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ------------------------------------------------------------------
# Шаг 2: выбор тарифа
# ------------------------------------------------------------------

@router.callback_query(LocationCallback.filter())
async def select_location(
    callback: CallbackQuery,
    callback_data: LocationCallback,
    db_user: dict,
) -> None:
    """Выбор локации — показ тарифных планов.

    Args:
        callback: Callback-запрос.
        callback_data: Данные выбранной локации.
        db_user: Данные пользователя из БД.
    """
    plans = await repo.plan.get_active_plans(include_trial=True)
    show_trial = not db_user.get("used_trial", False)

    type_label = "SOCKS5" if callback_data.proxy_type == "socks5" else "MTProto"
    await callback.message.edit_text(
        f"Тип: <b>{type_label}</b>\n"
        f"Локация: <b>{callback_data.country}</b>\n\n"
        "Выберите тарифный план:",
        reply_markup=plans_keyboard(
            plans,
            callback_data.country,
            show_trial=show_trial,
            proxy_type=callback_data.proxy_type,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ------------------------------------------------------------------
# Шаг 3: подтверждение
# ------------------------------------------------------------------

@router.callback_query(PlanCallback.filter())
async def select_plan(
    callback: CallbackQuery,
    callback_data: PlanCallback,
    db_user: dict,
) -> None:
    """Выбор тарифа — показ подтверждения с деталями.

    Args:
        callback: Callback-запрос.
        callback_data: Данные выбранного плана и страны.
        db_user: Данные пользователя из БД.
    """
    plan = await repo.plan.get_by_id(callback_data.plan_id)
    if not plan:
        await callback.answer("Тариф не найден.", show_alert=True)
        return

    if plan["is_trial"] and db_user.get("used_trial"):
        await callback.answer("Вы уже использовали пробный период.", show_alert=True)
        return

    node = await repo.node.get_least_loaded_node(callback_data.country)
    if not node:
        await callback.answer(
            "Нет свободных серверов в этой локации. Попробуйте другую.",
            show_alert=True,
        )
        return

    type_label = "SOCKS5" if callback_data.proxy_type == "socks5" else "MTProto"
    price_text = "Бесплатно" if plan["is_trial"] else f"${plan['price_usd']}"
    await callback.message.edit_text(
        f"<b>Подтверждение заказа</b>\n\n"
        f"Тип: {type_label}\n"
        f"Тариф: {plan['name']}\n"
        f"Локация: {callback_data.country}\n"
        f"Сервер: {node['name']}\n"
        f"Стоимость: {price_text}\n\n"
        f"Подтвердите покупку:",
        reply_markup=confirm_purchase_keyboard(
            plan["id"], node["id"], proxy_type=callback_data.proxy_type,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ------------------------------------------------------------------
# Шаг 4: подтверждение и оплата
# ------------------------------------------------------------------

@router.callback_query(ConfirmPurchaseCallback.filter())
async def confirm_purchase(
    callback: CallbackQuery,
    callback_data: ConfirmPurchaseCallback,
    db_user: dict,
    payment_service: PaymentService,
    subscription_service: SubscriptionService,
) -> None:
    """Подтверждение покупки — создание платежа и редирект на оплату.

    Для trial-тарифа оплата не требуется, подписка активируется сразу.

    Args:
        callback: Callback-запрос.
        callback_data: Данные подтверждения (plan_id, node_id, proxy_type).
        db_user: Данные пользователя из БД.
        payment_service: Сервис оплаты CryptoCloud.
        subscription_service: Сервис управления подписками.
    """
    plan = await repo.plan.get_by_id(callback_data.plan_id)
    if not plan:
        await callback.answer("Тариф не найден.", show_alert=True)
        return

    if plan["is_trial"]:
        await _handle_trial(
            callback, callback_data, db_user, plan, subscription_service,
        )
        return

    await _handle_paid_purchase(callback, callback_data, db_user, plan, payment_service)


async def _handle_trial(
    callback: CallbackQuery,
    callback_data: ConfirmPurchaseCallback,
    db_user: dict,
    plan: dict,
    subscription_service: SubscriptionService,
) -> None:
    """Обрабатывает активацию пробного периода.

    Args:
        callback: Callback-запрос.
        callback_data: Данные подтверждения.
        db_user: Данные пользователя из БД.
        plan: Данные тарифного плана.
        subscription_service: Сервис подписок.
    """
    if db_user.get("used_trial"):
        await callback.answer("Вы уже использовали пробный период.", show_alert=True)
        return

    await callback.message.edit_text("Активирую пробный период...")

    from src.db.pool import acquire

    async with acquire() as conn:
        payment = await repo.payment.create(
            conn,
            user_id=db_user["id"],
            plan_id=plan["id"],
            node_id=callback_data.node_id,
            amount_usd=0,
            access_type=callback_data.proxy_type,
        )
    await repo.payment.set_status(payment["id"], "success")

    result = await subscription_service.activate_subscription(
        payment_id=payment["id"],
        user_id=db_user["id"],
        plan_id=plan["id"],
        node_id=callback_data.node_id,
        duration_days=plan["duration_days"],
        is_trial=True,
        access_type=callback_data.proxy_type,
    )

    if not result:
        await callback.message.edit_text(
            "Произошла ошибка при активации. Попробуйте позже или обратитесь в поддержку."
        )
        return

    await _send_activation_message(callback, result, plan)
    await callback.answer()


async def _send_activation_message(
    callback: CallbackQuery,
    result: dict,
    plan: dict,
) -> None:
    """Отправляет пользователю сообщение об активации подписки.

    Args:
        callback: Callback-запрос.
        result: Данные активированной подписки.
        plan: Данные тарифного плана.
    """
    access_type = result.get("access_type", "mtproto")

    if access_type == "socks5" and result.get("socks5_host"):
        socks5_link = result.get("socks5_link") or build_socks5_link(
            result["socks5_host"],
            result["socks5_port"],
            result["socks5_username"],
            result["socks5_password"],
        )
        text = format_socks5_message(
            node_name=result["node_name"],
            country_flag=result["country_flag"],
            plan_name=plan["name"],
            expires_at=result["expires_at"].strftime("%d.%m.%Y %H:%M"),
            host=result["socks5_host"],
            port=result["socks5_port"],
            username=result["socks5_username"],
            password=result["socks5_password"],
            socks5_link=socks5_link,
        )
        await callback.message.edit_text(
            text,
            reply_markup=socks5_credentials_keyboard(socks5_link),
            parse_mode="HTML",
        )
    else:
        text = format_proxy_message(
            node_name=result["node_name"],
            country_flag=result["country_flag"],
            plan_name=plan["name"],
            expires_at=result["expires_at"].strftime("%d.%m.%Y %H:%M"),
            tg_link=result["tg_link"],
            https_link=result["https_link"],
        )
        await callback.message.edit_text(
            text,
            reply_markup=proxy_link_keyboard(result["https_link"]),
            parse_mode="HTML",
        )


async def _handle_paid_purchase(
    callback: CallbackQuery,
    callback_data: ConfirmPurchaseCallback,
    db_user: dict,
    plan: dict,
    payment_service: PaymentService,
) -> None:
    """Обрабатывает платную покупку — создание инвойса CryptoCloud.

    Args:
        callback: Callback-запрос.
        callback_data: Данные подтверждения.
        db_user: Данные пользователя из БД.
        plan: Данные тарифного плана.
        payment_service: Сервис оплаты.
    """
    from src.db.pool import acquire

    async with acquire() as conn:
        payment = await repo.payment.create(
            conn,
            user_id=db_user["id"],
            plan_id=plan["id"],
            node_id=callback_data.node_id,
            amount_usd=float(plan["price_usd"]),
            access_type=callback_data.proxy_type,
        )

    try:
        invoice = await payment_service.create_invoice(
            amount=float(plan["price_usd"]),
            order_id=str(payment["id"]),
        )
    except PaymentError:
        logger.exception("Ошибка создания инвойса для payment_id=%d", payment["id"])
        await callback.message.edit_text(
            "Ошибка при создании счёта. Попробуйте позже."
        )
        return

    await repo.payment.update_cryptocloud_data(
        payment["id"],
        cryptocloud_uuid=invoice["uuid"],
        cryptocloud_link=invoice["link"],
    )

    await callback.message.edit_text(
        f"Счёт создан!\n\n"
        f"Тариф: <b>{plan['name']}</b>\n"
        f"Сумма: <b>${plan['price_usd']}</b>\n\n"
        f"Нажмите кнопку для перехода к оплате.\n"
        f"После оплаты прокси будет автоматически активирован.\n\n"
        f"<i>Для минимальной комиссии используйте сети "
        f"ARB, BNB, SOL, TON. В других сетях сервис может "
        f"взимать дополнительную комиссию.</i>",
        reply_markup=payment_keyboard(invoice["link"]),
        parse_mode="HTML",
    )
    await callback.answer()


# ------------------------------------------------------------------
# Пробный период
# ------------------------------------------------------------------

@router.callback_query(F.data == "trial_start")
async def trial_start(callback: CallbackQuery, db_user: dict) -> None:
    """Начало получения пробного периода — выбор типа прокси.

    Args:
        callback: Callback-запрос.
        db_user: Данные пользователя из БД.
    """
    if db_user.get("used_trial"):
        await callback.answer("Вы уже использовали пробный период.", show_alert=True)
        return

    trial_plan = await repo.plan.get_trial_plan()
    if not trial_plan:
        await callback.answer("Пробный период сейчас недоступен.", show_alert=True)
        return

    countries = await repo.node.get_available_countries()
    if not countries:
        await callback.answer("Нет доступных серверов.", show_alert=True)
        return

    await callback.message.edit_text(
        "<b>Выберите тип прокси для пробного периода:</b>\n\n"
        "🔒 <b>MTProto</b>\n"
        "• Внутренний протокол Telegram.\n"
        "• Высокая надежность и шифрование.\n"
        "• Рекомендуется для ПК с проводным интернетом.\n"
        "• <b>Не рекомендуется для использования на телефоне</b> (медленное соединение).\n\n"
        "🧦 <b>SOCKS5</b>\n"
        "• Универсальный скоростной протокол.\n"
        "• Отлично подходит для телефонов и любых устройств.\n"
        "• Быстрое подключение и высокая скорость.",
        reply_markup=proxy_type_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()

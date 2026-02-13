"""Хэндлеры процесса покупки прокси.

Пайплайн: выбор локации -> выбор тарифа -> подтверждение -> оплата.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.bot.callbacks.factories import (
    BackCallback,
    ConfirmPurchaseCallback,
    LocationCallback,
    PlanCallback,
)
from src.bot.keyboards.menus import (
    confirm_purchase_keyboard,
    locations_keyboard,
    payment_keyboard,
    plans_keyboard,
    proxy_link_keyboard,
)
from src.db import repositories as repo
from src.services.payment import PaymentError, PaymentService
from src.services.subscription import SubscriptionService

logger = logging.getLogger(__name__)

router = Router(name="buy")


@router.callback_query(F.data == "buy_start")
async def start_purchase(callback: CallbackQuery) -> None:
    """Начало процесса покупки — показ доступных локаций.

    Args:
        callback: Callback-запрос.
    """
    countries = await repo.node.get_available_countries()
    if not countries:
        await callback.answer("Нет доступных серверов. Попробуйте позже.", show_alert=True)
        return

    await callback.message.edit_text(
        "Выберите локацию прокси-сервера:",
        reply_markup=locations_keyboard(countries),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(BackCallback.filter(F.to == "locations"))
async def back_to_locations(callback: CallbackQuery) -> None:
    """Возврат к выбору локации.

    Args:
        callback: Callback-запрос.
    """
    countries = await repo.node.get_available_countries()
    await callback.message.edit_text(
        "Выберите локацию прокси-сервера:",
        reply_markup=locations_keyboard(countries),
        parse_mode="HTML",
    )
    await callback.answer()


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

    await callback.message.edit_text(
        f"Локация: <b>{callback_data.country}</b>\n\n"
        "Выберите тарифный план:",
        reply_markup=plans_keyboard(plans, callback_data.country, show_trial=show_trial),
        parse_mode="HTML",
    )
    await callback.answer()


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

    # Проверка trial
    if plan["is_trial"] and db_user.get("used_trial"):
        await callback.answer("Вы уже использовали пробный период.", show_alert=True)
        return

    # Находим лучшую ноду
    node = await repo.node.get_least_loaded_node(callback_data.country)
    if not node:
        await callback.answer(
            "Нет свободных серверов в этой локации. Попробуйте другую.",
            show_alert=True,
        )
        return

    price_text = "Бесплатно" if plan["is_trial"] else f"${plan['price_usd']}"
    await callback.message.edit_text(
        f"<b>Подтверждение заказа</b>\n\n"
        f"Тариф: {plan['name']}\n"
        f"Локация: {callback_data.country}\n"
        f"Сервер: {node['name']}\n"
        f"Стоимость: {price_text}\n\n"
        f"Подтвердите покупку:",
        reply_markup=confirm_purchase_keyboard(plan["id"], node["id"]),
        parse_mode="HTML",
    )
    await callback.answer()


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
        callback_data: Данные подтверждения (plan_id, node_id).
        db_user: Данные пользователя из БД.
        payment_service: Сервис оплаты CryptoCloud.
        subscription_service: Сервис управления подписками.
    """
    plan = await repo.plan.get_by_id(callback_data.plan_id)
    if not plan:
        await callback.answer("Тариф не найден.", show_alert=True)
        return

    # Обработка пробного периода (бесплатно)
    if plan["is_trial"]:
        await _handle_trial(callback, callback_data, db_user, plan, subscription_service)
        return

    # Платный тариф — создаём платёж
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

    # Создаём фиктивный платёж для trial
    from src.db.pool import acquire

    async with acquire() as conn:
        payment = await repo.payment.create(
            conn,
            user_id=db_user["id"],
            plan_id=plan["id"],
            node_id=callback_data.node_id,
            amount_usd=0,
        )
    await repo.payment.set_status(payment["id"], "success")

    result = await subscription_service.activate_subscription(
        payment_id=payment["id"],
        user_id=db_user["id"],
        plan_id=plan["id"],
        node_id=callback_data.node_id,
        duration_days=plan["duration_days"],
        is_trial=True,
    )

    if not result:
        await callback.message.edit_text(
            "Произошла ошибка при активации. Попробуйте позже или обратитесь в поддержку."
        )
        return

    from src.services.proxy import format_proxy_message

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
        reply_markup=proxy_link_keyboard(result["tg_link"]),
        parse_mode="HTML",
    )
    await callback.answer()


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
        )

    try:
        invoice = await payment_service.create_invoice(
            amount=float(plan["price_usd"]),
            order_id=str(payment["id"]),
        )
    except PaymentError as exc:
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
        f"После оплаты прокси будет автоматически активирован.",
        reply_markup=payment_keyboard(invoice["link"]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "trial_start")
async def trial_start(callback: CallbackQuery, db_user: dict) -> None:
    """Начало получения пробного периода — перенаправление в выбор локации.

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
        "Выберите локацию для пробного прокси:",
        reply_markup=locations_keyboard(countries),
        parse_mode="HTML",
    )
    await callback.answer()

"""Webhook-эндпоинт для обработки postback от CryptoCloud.

CryptoCloud отправляет POST с x-www-form-urlencoded данными:
- status: "success"
- invoice_id: идентификатор платежа CryptoCloud
- amount_crypto: сумма в крипте
- currency: код криптовалюты
- order_id: наш payment.id
- token: JWT подписанный SECRET KEY проекта (HS256, валиден 5 минут)

Верификация: декодируем JWT с помощью SECRET KEY из настроек CryptoCloud.
Если подпись невалидна или токен истёк — отклоняем запрос.
"""

import logging

import jwt
from fastapi import APIRouter, Form, HTTPException, Request
from starlette import status as http_status

from src.config import Settings
from src.db import repositories as repo
from src.services.proxy import format_proxy_message
from src.services.subscription import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_cryptocloud_token(token: str, secret_key: str) -> dict | None:
    """Верифицирует JWT-токен из postback CryptoCloud.

    Args:
        token: JWT-строка из поля token postback-а.
        secret_key: SECRET KEY проекта из настроек CryptoCloud.

    Returns:
        Payload токена при успешной верификации, None при ошибке.
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("CryptoCloud postback: JWT токен истёк")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning("CryptoCloud postback: невалидный JWT токен: %s", exc)
        return None


@router.post("/cryptocloud")
async def cryptocloud_postback(
    request: Request,
    status: str = Form(...),
    invoice_id: str = Form(default=""),
    amount_crypto: str = Form(default=""),
    currency: str = Form(default=""),
    order_id: str = Form(default=""),
    token: str = Form(default=""),
) -> dict:
    """Обрабатывает postback от CryptoCloud при успешной оплате.

    Пайплайн:
    1. Верифицируем JWT-подпись postback-а
    2. Находим payment по order_id
    3. Обновляем статус на success
    4. Активируем подписку (генерация секрета, добавление на ноду)
    5. Обновляем статус на paid
    6. Уведомляем пользователя через бота

    Args:
        request: Объект FastAPI Request (содержит app.state со ссылками на сервисы).
        status: Статус платежа от CryptoCloud (ожидаем "success").
        invoice_id: ID инвойса в CryptoCloud.
        amount_crypto: Сумма в криптовалюте.
        currency: Код криптовалюты.
        order_id: Наш payment.id.
        token: JWT-подпись (HS256, подписана SECRET KEY проекта).

    Returns:
        Словарь с результатом обработки.

    Raises:
        HTTPException: 403 при невалидной подписи JWT.
    """
    logger.info(
        "CryptoCloud postback: status=%s, invoice_id=%s, order_id=%s",
        status,
        invoice_id,
        order_id,
    )

    # === Верификация подписи ===
    settings: Settings = request.app.state.settings
    if not token:
        logger.error("CryptoCloud postback: JWT токен отсутствует")
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Missing token",
        )

    payload = _verify_cryptocloud_token(token, settings.cryptocloud.secret_key)
    if payload is None:
        logger.error("CryptoCloud postback: верификация JWT провалена")
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Invalid token",
        )

    logger.info("CryptoCloud JWT верифицирован: %s", payload)

    if status != "success":
        logger.warning("Неожиданный статус postback: %s", status)
        return {"ok": True}

    # Находим платёж
    if not order_id or not order_id.isdigit():
        logger.error("Невалидный order_id: %s", order_id)
        return {"ok": False, "error": "invalid order_id"}

    payment = await repo.payment.get_by_id(int(order_id))
    if not payment:
        logger.error("Платёж не найден: order_id=%s", order_id)
        return {"ok": False, "error": "payment not found"}

    if payment["status"] in ("paid", "success"):
        logger.info("Платёж #%d уже обработан (status=%s)", payment["id"], payment["status"])
        return {"ok": True}

    # Обновляем статус на success
    await repo.payment.set_status(payment["id"], "success")

    # Активируем подписку
    try:
        result = await _activate_from_payment(request, payment)
        if result:
            await _notify_user(request, payment, result)
    except Exception:
        logger.exception("Ошибка активации подписки для payment_id=%d", payment["id"])
        # Оставляем status=success — планировщик подберёт

    return {"ok": True}


async def _activate_from_payment(
    request: Request,
    payment: dict,
) -> dict | None:
    """Активирует подписку на основе данных платежа.

    Args:
        request: FastAPI Request с доступом к сервисам.
        payment: Данные платежа из БД.

    Returns:
        Данные активированной подписки или None.
    """
    subscription_service: SubscriptionService = request.app.state.subscription_service

    # Получаем полные данные платежа с планом
    full_payment = await repo.payment.get_by_cryptocloud_uuid(
        payment.get("cryptocloud_uuid", "")
    )
    if not full_payment:
        full_payment = payment

    # Определяем ноду
    node_id = payment.get("node_id")
    if not node_id:
        logger.error("node_id не указан для payment_id=%d", payment["id"])
        return None

    plan = await repo.plan.get_by_id(payment["plan_id"])
    if not plan:
        logger.error("План не найден для payment_id=%d", payment["id"])
        return None

    result = await subscription_service.activate_subscription(
        payment_id=payment["id"],
        user_id=payment["user_id"],
        plan_id=plan["id"],
        node_id=node_id,
        duration_days=plan["duration_days"],
        is_trial=plan["is_trial"],
    )
    return result


async def _notify_user(
    request: Request,
    payment: dict,
    subscription_data: dict,
) -> None:
    """Отправляет уведомление пользователю через Telegram-бота.

    Args:
        request: FastAPI Request с доступом к боту.
        payment: Данные платежа.
        subscription_data: Данные активированной подписки.
    """
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    bot = request.app.state.bot

    user = await repo.user.get_by_id(payment["user_id"])
    if not user:
        return

    plan = await repo.plan.get_by_id(payment["plan_id"])
    plan_name = plan["name"] if plan else "—"

    text = format_proxy_message(
        node_name=subscription_data.get("node_name", "Сервер"),
        country_flag=subscription_data.get("country_flag", ""),
        plan_name=plan_name,
        expires_at=subscription_data["expires_at"].strftime("%d.%m.%Y %H:%M"),
        tg_link=subscription_data["tg_link"],
        https_link=subscription_data["https_link"],
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подключить прокси", url=subscription_data["tg_link"])],
    ])

    try:
        await bot.send_message(
            chat_id=user["telegram_id"],
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception:
        logger.exception(
            "Не удалось отправить уведомление user telegram_id=%d", user["telegram_id"]
        )

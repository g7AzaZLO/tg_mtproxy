"""Webhook-эндпоинт для обработки postback от CryptoCloud.

CryptoCloud отправляет POST с x-www-form-urlencoded данными.
Данные парсятся из request.form() без строгой валидации,
так как CryptoCloud может присылать дополнительные поля.

Верификация: декодируем JWT из поля token с помощью SECRET KEY.
"""

import logging

import jwt
from fastapi import APIRouter, HTTPException, Request
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


async def _parse_postback_data(request: Request) -> dict:
    """Парсит данные postback из CryptoCloud (form-urlencoded или JSON).

    Args:
        request: Объект FastAPI Request.

    Returns:
        Словарь с полями postback-а.
    """
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        return await request.json()

    # По умолчанию пробуем form-urlencoded
    try:
        form_data = await request.form()
        return {k: v for k, v in form_data.items()}
    except Exception:
        # Fallback на JSON если form не парсится
        try:
            return await request.json()
        except Exception:
            # Последняя попытка — сырое тело
            body = await request.body()
            logger.error("Не удалось распарсить postback body: %s", body[:500])
            return {}


@router.post("/cryptocloud")
async def cryptocloud_postback(request: Request) -> dict:
    """Обрабатывает postback от CryptoCloud при успешной оплате.

    Принимает данные в любом формате (JSON или form-urlencoded),
    так как CryptoCloud может менять формат.

    Пайплайн:
    1. Парсим данные (JSON / form)
    2. Верифицируем JWT-подпись
    3. Находим payment по order_id
    4. Обновляем статус на success
    5. Активируем подписку
    6. Обновляем статус на paid
    7. Уведомляем пользователя

    Args:
        request: Объект FastAPI Request.

    Returns:
        Словарь с результатом обработки.

    Raises:
        HTTPException: 403 при невалидной подписи JWT.
    """
    data = await _parse_postback_data(request)

    status = str(data.get("status", ""))
    invoice_id = str(data.get("invoice_id", ""))
    order_id = str(data.get("order_id", ""))
    token = str(data.get("token", ""))

    logger.info(
        "CryptoCloud postback: status=%s, invoice_id=%s, order_id=%s, fields=%s",
        status,
        invoice_id,
        order_id,
        list(form_data.keys()),
    )

    # === Верификация подписи ===
    settings: Settings = request.app.state.settings
    if not token:
        logger.error("CryptoCloud postback: JWT токен отсутствует")
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Missing token",
        )

    payload = _verify_cryptocloud_token(str(token), settings.cryptocloud.secret_key)
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
    order_id_str = str(order_id)
    if not order_id_str or not order_id_str.isdigit():
        logger.error("Невалидный order_id: %s", order_id_str)
        return {"ok": False, "error": "invalid order_id"}

    payment = await repo.payment.get_by_id(int(order_id_str))
    if not payment:
        logger.error("Платёж не найден: order_id=%s", order_id_str)
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

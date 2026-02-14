"""Фоновые задачи — планировщик на APScheduler.

Задачи:
- Проверка истекающих подписок и отправка напоминаний (3 дня, 1 день)
- Деактивация истекших подписок
- Повторная активация «зависших» платежей (status=success без подписки)
- Health-check нод
"""

import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.db import repositories as repo
from src.services.node_manager import NodeManagerService
from src.services.subscription import SubscriptionService

logger = logging.getLogger(__name__)


def create_scheduler(
    *,
    bot: Bot,
    subscription_service: SubscriptionService,
    node_manager: NodeManagerService,
) -> AsyncIOScheduler:
    """Создаёт и конфигурирует планировщик фоновых задач.

    Args:
        bot: Экземпляр Telegram-бота для отправки уведомлений.
        subscription_service: Сервис подписок.
        node_manager: Сервис управления нодами.

    Returns:
        Настроенный AsyncIOScheduler (не запущен).
    """
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        _check_expiring_3d,
        "interval",
        hours=1,
        kwargs={"bot": bot},
        id="check_expiring_3d",
        replace_existing=True,
    )
    scheduler.add_job(
        _check_expiring_1d,
        "interval",
        hours=1,
        kwargs={"bot": bot},
        id="check_expiring_1d",
        replace_existing=True,
    )
    scheduler.add_job(
        _deactivate_expired,
        "interval",
        minutes=15,
        kwargs={"bot": bot, "subscription_service": subscription_service},
        id="deactivate_expired",
        replace_existing=True,
    )
    scheduler.add_job(
        _retry_stuck_payments,
        "interval",
        minutes=5,
        kwargs={"bot": bot, "subscription_service": subscription_service},
        id="retry_stuck_payments",
        replace_existing=True,
    )
    scheduler.add_job(
        _health_check_nodes,
        "interval",
        minutes=5,
        kwargs={"node_manager": node_manager},
        id="health_check_nodes",
        replace_existing=True,
    )

    return scheduler


async def _check_expiring_3d(bot: Bot) -> None:
    """Уведомляет пользователей о подписках, истекающих через 3 дня."""
    try:
        subs = await repo.subscription.get_expiring(3, already_notified_field="notified_3d")
        for sub in subs:
            await _send_expiry_notification(bot, sub, days_left=3)
            await repo.subscription.mark_notified(sub["id"], field="notified_3d")
        if subs:
            logger.info("Отправлено %d уведомлений (3 дня до окончания)", len(subs))
    except Exception:
        logger.exception("Ошибка в задаче check_expiring_3d")


async def _check_expiring_1d(bot: Bot) -> None:
    """Уведомляет пользователей о подписках, истекающих через 1 день."""
    try:
        subs = await repo.subscription.get_expiring(1, already_notified_field="notified_1d")
        for sub in subs:
            await _send_expiry_notification(bot, sub, days_left=1)
            await repo.subscription.mark_notified(sub["id"], field="notified_1d")
        if subs:
            logger.info("Отправлено %d уведомлений (1 день до окончания)", len(subs))
    except Exception:
        logger.exception("Ошибка в задаче check_expiring_1d")


async def _deactivate_expired(
    bot: Bot,
    subscription_service: SubscriptionService,
) -> None:
    """Деактивирует все истекшие подписки."""
    try:
        expired = await repo.subscription.get_expired()
        for sub in expired:
            await subscription_service.deactivate_subscription(sub["id"])
            await _send_expired_notification(bot, sub)
        if expired:
            logger.info("Деактивировано %d истекших подписок", len(expired))
    except Exception:
        logger.exception("Ошибка в задаче deactivate_expired")


async def _retry_stuck_payments(
    bot: Bot,
    subscription_service: SubscriptionService,
) -> None:
    """Повторно пытается активировать «зависшие» платежи в статусе success."""
    try:
        stuck = await repo.payment.get_stuck_success_payments()
        for payment in stuck:
            logger.info(
                "Повторная активация для payment_id=%d", payment["id"]
            )
            plan = await repo.plan.get_by_id(payment["plan_id"])
            if not plan:
                continue

            result = await subscription_service.activate_subscription(
                payment_id=payment["id"],
                user_id=payment["user_id"],
                plan_id=plan["id"],
                node_id=payment["node_id"],
                duration_days=plan["duration_days"],
                is_trial=plan["is_trial"],
            )
            if result:
                user = await repo.user.get_by_id(payment["user_id"])
                if user:
                    await _send_activation_notification(bot, user, result)
        if stuck:
            logger.info("Обработано %d зависших платежей", len(stuck))
    except Exception:
        logger.exception("Ошибка в задаче retry_stuck_payments")


async def _health_check_nodes(node_manager: NodeManagerService) -> None:
    """Проверяет доступность всех активных нод."""
    try:
        nodes = await repo.node.get_active_nodes()
        for node in nodes:
            health = await node_manager.health_check(
                agent_url=node["agent_url"],
                agent_api_key=node["agent_api_key"],
            )
            if health is None:
                logger.warning("Нода %s (%s) недоступна!", node["name"], node["host"])
            else:
                logger.debug("Нода %s OK", node["name"])
    except Exception:
        logger.exception("Ошибка в задаче health_check_nodes")


async def _send_expiry_notification(bot: Bot, sub: dict, *, days_left: int) -> None:
    """Отправляет уведомление об истечении подписки.

    Args:
        bot: Экземпляр бота.
        sub: Данные подписки (с telegram_id из JOIN).
        days_left: Количество дней до окончания.
    """
    day_word = _pluralize_days(days_left)
    text = (
        f"Ваша подписка <b>{sub.get('plan_name', '')}</b> на сервере "
        f"<b>{sub.get('node_name', '')}</b> истекает через <b>{days_left} {day_word}</b>.\n\n"
        f"Продлите подписку, чтобы не потерять доступ!"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Продлить", callback_data="buy_start")],
    ])
    try:
        await bot.send_message(
            chat_id=sub["telegram_id"],
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception:
        logger.warning("Не удалось отправить уведомление tg_id=%d", sub["telegram_id"])


async def _send_expired_notification(bot: Bot, sub: dict) -> None:
    """Отправляет уведомление об окончании подписки.

    Args:
        bot: Экземпляр бота.
        sub: Данные подписки.
    """
    text = (
        "Ваша подписка истекла и прокси был отключён.\n\n"
        "Приобретите новую подписку для возобновления доступа."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Купить прокси", callback_data="buy_start")],
    ])
    try:
        await bot.send_message(
            chat_id=sub["telegram_id"],
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception:
        logger.warning("Не удалось отправить уведомление tg_id=%d", sub["telegram_id"])


async def _send_activation_notification(
    bot: Bot,
    user: dict,
    subscription_data: dict,
) -> None:
    """Отправляет уведомление об успешной активации (для retry).

    Args:
        bot: Экземпляр бота.
        user: Данные пользователя.
        subscription_data: Данные подписки с ссылками.
    """
    from src.services.proxy import format_proxy_message

    plan = await repo.plan.get_by_id(subscription_data["plan_id"])
    text = format_proxy_message(
        node_name=subscription_data.get("node_name", "Сервер"),
        country_flag=subscription_data.get("country_flag", ""),
        plan_name=plan["name"] if plan else "—",
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
        logger.warning("Не удалось уведомить user tg_id=%d", user["telegram_id"])


def _pluralize_days(n: int) -> str:
    """Склоняет слово «день» для русского языка.

    Args:
        n: Количество дней.

    Returns:
        Правильная форма слова (день/дня/дней).
    """
    if 11 <= n % 100 <= 19:
        return "дней"
    remainder = n % 10
    if remainder == 1:
        return "день"
    if 2 <= remainder <= 4:
        return "дня"
    return "дней"

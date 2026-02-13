"""Middleware для rate-limiting и автоматической регистрации пользователей.

ThrottleMiddleware ограничивает частоту обращений к боту.
UserMiddleware автоматически получает/создаёт пользователя при каждом обращении.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from src.db.repositories import user as user_repo

logger = logging.getLogger(__name__)


class ThrottleMiddleware(BaseMiddleware):
    """Ограничивает частоту сообщений от одного пользователя.

    Attributes:
        _rate_limit: Минимальный интервал между обработками (секунды).
        _user_last_time: Словарь {user_id: timestamp последнего обращения}.
    """

    def __init__(self, rate_limit: float = 0.5) -> None:
        """Инициализирует middleware.

        Args:
            rate_limit: Минимальный интервал между обработками в секундах.
        """
        self._rate_limit = rate_limit
        self._user_last_time: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Проверяет rate-limit перед передачей события в handler.

        Args:
            handler: Следующий обработчик в цепочке.
            event: Входящее событие Telegram.
            data: Контекст middleware.

        Returns:
            Результат handler или None при превышении лимита.
        """
        user_id = self._extract_user_id(event)
        if user_id is None:
            return await handler(event, data)

        now = time.monotonic()
        last_time = self._user_last_time.get(user_id, 0.0)

        if now - last_time < self._rate_limit:
            logger.debug("Throttled user_id=%d", user_id)
            return None

        self._user_last_time[user_id] = now
        return await handler(event, data)

    @staticmethod
    def _extract_user_id(event: TelegramObject) -> int | None:
        """Извлекает user_id из события.

        Args:
            event: Событие Telegram.

        Returns:
            ID пользователя или None.
        """
        if isinstance(event, Message) and event.from_user:
            return event.from_user.id
        if isinstance(event, CallbackQuery) and event.from_user:
            return event.from_user.id
        return None


class UserMiddleware(BaseMiddleware):
    """Автоматически получает или создаёт пользователя в БД при каждом обращении.

    Добавляет в data['db_user'] словарь с данными пользователя из БД.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Загружает пользователя из БД и передаёт в контекст.

        Args:
            handler: Следующий обработчик в цепочке.
            event: Входящее событие Telegram.
            data: Контекст middleware.

        Returns:
            Результат handler.
        """
        tg_user = None
        if isinstance(event, Message) and event.from_user:
            tg_user = event.from_user
        elif isinstance(event, CallbackQuery) and event.from_user:
            tg_user = event.from_user

        if tg_user:
            db_user = await user_repo.get_or_create(
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
            )
            data["db_user"] = db_user

        return await handler(event, data)


class BanCheckMiddleware(BaseMiddleware):
    """Проверяет, не заблокирован ли пользователь, и отклоняет запросы забаненных."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Проверяет бан-статус и блокирует обработку, если пользователь забанен.

        Args:
            handler: Следующий обработчик в цепочке.
            event: Входящее событие Telegram.
            data: Контекст middleware.

        Returns:
            Результат handler или None, если пользователь забанен.
        """
        db_user = data.get("db_user")
        if db_user and db_user.get("is_banned"):
            if isinstance(event, Message):
                await event.answer("Ваш аккаунт заблокирован.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Ваш аккаунт заблокирован.", show_alert=True)
            return None
        return await handler(event, data)

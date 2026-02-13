"""Управление пулом соединений asyncpg.

Глобальный пул создаётся при старте приложения и закрывается при завершении.
Все репозитории получают соединения через acquire().
"""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import asyncpg

from src.config import DatabaseSettings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool(settings: DatabaseSettings) -> asyncpg.Pool:
    """Инициализирует глобальный пул соединений к PostgreSQL.

    Args:
        settings: Настройки подключения к базе данных.

    Returns:
        Созданный пул соединений.

    Raises:
        RuntimeError: Если пул уже инициализирован.
    """
    global _pool  # noqa: PLW0603

    if _pool is not None:
        raise RuntimeError("Пул соединений уже инициализирован")

    _pool = await asyncpg.create_pool(
        dsn=settings.dsn,
        min_size=settings.min_pool_size,
        max_size=settings.max_pool_size,
    )
    logger.info(
        "Пул соединений создан: %s:%d/%s (pool: %d-%d)",
        settings.host,
        settings.port,
        settings.name,
        settings.min_pool_size,
        settings.max_pool_size,
    )
    return _pool


async def close_pool() -> None:
    """Закрывает глобальный пул соединений."""
    global _pool  # noqa: PLW0603

    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Пул соединений закрыт")


def get_pool() -> asyncpg.Pool:
    """Возвращает текущий глобальный пул соединений.

    Returns:
        Активный пул соединений.

    Raises:
        RuntimeError: Если пул не инициализирован.
    """
    if _pool is None:
        raise RuntimeError("Пул соединений не инициализирован, вызовите init_pool()")
    return _pool


@asynccontextmanager
async def acquire() -> AsyncIterator[asyncpg.Connection]:
    """Контекстный менеджер для получения соединения из пула.

    Yields:
        Соединение asyncpg, автоматически возвращаемое в пул при выходе.

    Raises:
        RuntimeError: Если пул не инициализирован.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction() -> AsyncIterator[asyncpg.Connection]:
    """Контекстный менеджер для выполнения запросов в транзакции.

    Yields:
        Соединение asyncpg внутри активной транзакции.
        При ошибке транзакция откатывается автоматически.

    Raises:
        RuntimeError: Если пул не инициализирован.
    """
    async with acquire() as conn:
        async with conn.transaction():
            yield conn

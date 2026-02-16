"""Репозиторий пользователей — raw SQL запросы через asyncpg."""

import asyncpg

from src.db.pool import acquire


async def get_or_create(
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> dict:
    """Находит пользователя по telegram_id или создаёт нового.

    Args:
        telegram_id: Уникальный идентификатор пользователя в Telegram.
        username: Имя пользователя Telegram (без @).
        first_name: Имя пользователя.

    Returns:
        Словарь с данными пользователя.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id = $1",
            telegram_id,
        )
        if row is not None:
            # Обновляем username/first_name при каждом обращении
            if row["username"] != username or row["first_name"] != first_name:
                await conn.execute(
                    "UPDATE users SET username = $1, first_name = $2 WHERE id = $3",
                    username,
                    first_name,
                    row["id"],
                )
            return dict(row)

        row = await conn.fetchrow(
            "INSERT INTO users (telegram_id, username, first_name) "
            "VALUES ($1, $2, $3) RETURNING *",
            telegram_id,
            username,
            first_name,
        )
        return dict(row)


async def get_by_telegram_id(telegram_id: int) -> dict | None:
    """Находит пользователя по Telegram ID.

    Args:
        telegram_id: Уникальный идентификатор пользователя в Telegram.

    Returns:
        Словарь с данными пользователя или None, если не найден.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id = $1",
            telegram_id,
        )
        return dict(row) if row else None


async def get_by_id(user_id: int) -> dict | None:
    """Находит пользователя по внутреннему ID.

    Args:
        user_id: Внутренний ID пользователя.

    Returns:
        Словарь с данными пользователя или None.
    """
    async with acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        return dict(row) if row else None


async def mark_trial_used(user_id: int) -> None:
    """Помечает, что пользователь использовал пробный период.

    Args:
        user_id: Внутренний ID пользователя.
    """
    async with acquire() as conn:
        await conn.execute(
            "UPDATE users SET used_trial = TRUE WHERE id = $1",
            user_id,
        )


async def try_mark_trial_used(
    conn: asyncpg.Connection,
    *,
    user_id: int,
) -> bool:
    """Пытается атомарно пометить триал как использованный.

    Args:
        conn: Активное соединение asyncpg (обычно внутри транзакции).
        user_id: Внутренний ID пользователя.

    Returns:
        True, если флаг был выставлен в этом вызове.
        False, если триал уже был использован ранее.
    """
    row = await conn.fetchrow(
        """
        UPDATE users
        SET used_trial = TRUE
        WHERE id = $1
          AND used_trial = FALSE
        RETURNING id
        """,
        user_id,
    )
    return row is not None


async def set_banned(user_id: int, *, is_banned: bool) -> None:
    """Устанавливает или снимает бан пользователя.

    Args:
        user_id: Внутренний ID пользователя.
        is_banned: True для бана, False для разбана.
    """
    async with acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_banned = $1 WHERE id = $2",
            is_banned,
            user_id,
        )


async def get_all(
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Возвращает список пользователей с пагинацией.

    Args:
        limit: Максимальное количество записей.
        offset: Смещение от начала.

    Returns:
        Список словарей с данными пользователей.
    """
    async with acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            limit,
            offset,
        )
        return [dict(r) for r in rows]


async def count() -> int:
    """Возвращает общее количество пользователей.

    Returns:
        Количество записей в таблице users.
    """
    async with acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users")


async def search_by_username(query: str, limit: int = 20) -> list[dict]:
    """Ищет пользователей по username (ILIKE).

    Args:
        query: Подстрока для поиска.
        limit: Максимальное количество результатов.

    Returns:
        Список найденных пользователей.
    """
    async with acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM users WHERE username ILIKE $1 ORDER BY created_at DESC LIMIT $2",
            f"%{query}%",
            limit,
        )
        return [dict(r) for r in rows]


async def update_user(
    user_id: int,
    *,
    username: str | None,
    first_name: str | None,
    is_banned: bool,
    used_trial: bool,
) -> dict | None:
    """Обновляет профиль пользователя.

    Args:
        user_id: Внутренний ID пользователя.
        username: Новый username.
        first_name: Новое имя.
        is_banned: Флаг блокировки.
        used_trial: Флаг использованного триала.

    Returns:
        Обновлённый пользователь или None, если не найден.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
            SET username = $1,
                first_name = $2,
                is_banned = $3,
                used_trial = $4
            WHERE id = $5
            RETURNING *
            """,
            username,
            first_name,
            is_banned,
            used_trial,
            user_id,
        )
        return dict(row) if row else None


async def delete_user(user_id: int) -> bool:
    """Удаляет пользователя по ID.

    Args:
        user_id: Внутренний ID пользователя.

    Returns:
        True, если пользователь был удалён.
    """
    async with acquire() as conn:
        result = await conn.execute("DELETE FROM users WHERE id = $1", user_id)
        return result.endswith("1")

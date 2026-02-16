"""Репозиторий подписок — raw SQL запросы через asyncpg."""

from datetime import datetime, timedelta, timezone

import asyncpg

from src.db.pool import acquire, transaction


async def create(
    conn: asyncpg.Connection,
    *,
    user_id: int,
    node_id: int,
    plan_id: int,
    secret: str,
    duration_days: int,
    is_trial: bool = False,
    access_type: str = "mtproto",
    marzban_username: str | None = None,
) -> dict:
    """Создаёт новую подписку в рамках существующей транзакции.

    Args:
        conn: Соединение с активной транзакцией.
        user_id: Внутренний ID пользователя.
        node_id: ID ноды.
        plan_id: ID тарифного плана.
        secret: Сгенерированный dd-секрет (пустая строка для SOCKS5).
        duration_days: Длительность подписки в днях.
        is_trial: Пробная подписка — сразу помечается как notified_3d.
        access_type: Тип доступа — ``mtproto`` или ``socks5``.
        marzban_username: Username в Marzban (только для socks5).

    Returns:
        Словарь с данными созданной подписки.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=duration_days)

    row = await conn.fetchrow(
        "INSERT INTO subscriptions "
        "(user_id, node_id, plan_id, secret, starts_at, expires_at, "
        "status, notified_3d, access_type, marzban_username) "
        "VALUES ($1, $2, $3, $4, $5, $6, 'active', $7, $8, $9) RETURNING *",
        user_id,
        node_id,
        plan_id,
        secret,
        now,
        expires_at,
        is_trial,
        access_type,
        marzban_username,
    )
    return dict(row)


async def get_by_id(subscription_id: int) -> dict | None:
    """Находит подписку по ID.

    Args:
        subscription_id: Идентификатор подписки.

    Returns:
        Словарь с данными подписки или None.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM subscriptions WHERE id = $1",
            subscription_id,
        )
        return dict(row) if row else None


async def get_active_by_user(user_id: int) -> list[dict]:
    """Возвращает все активные подписки пользователя с данными ноды.

    Args:
        user_id: Внутренний ID пользователя.

    Returns:
        Список активных подписок с присоединёнными данными ноды.
    """
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.*, n.host, n.port, n.name AS node_name,
                   n.country, n.country_flag, p.name AS plan_name
            FROM subscriptions s
            JOIN nodes n ON n.id = s.node_id
            JOIN plans p ON p.id = s.plan_id
            WHERE s.user_id = $1
              AND s.status IN ('active', 'expiring')
            ORDER BY s.expires_at DESC
            """,
            user_id,
        )
        return [dict(r) for r in rows]


async def get_expiring(days: int, *, already_notified_field: str) -> list[dict]:
    """Находит подписки, истекающие через указанное количество дней.

    Args:
        days: Количество дней до истечения.
        already_notified_field: Имя булевого поля (notified_3d или notified_1d).

    Returns:
        Список подписок, требующих уведомления.
    """
    if already_notified_field not in ("notified_3d", "notified_1d"):
        raise ValueError(f"Недопустимое поле: {already_notified_field}")

    async with acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT s.*, u.telegram_id, n.host, n.port,
                   n.name AS node_name, p.name AS plan_name
            FROM subscriptions s
            JOIN users u ON u.id = s.user_id
            JOIN nodes n ON n.id = s.node_id
            JOIN plans p ON p.id = s.plan_id
            WHERE s.status = 'active'
              AND s.{already_notified_field} = FALSE
              AND s.expires_at <= NOW() + INTERVAL '{days} days'
              AND s.expires_at > NOW()
            """,  # noqa: S608
        )
        return [dict(r) for r in rows]


async def mark_notified(subscription_id: int, *, field: str) -> None:
    """Помечает подписку как уведомлённую.

    Args:
        subscription_id: ID подписки.
        field: Имя булевого поля (notified_3d или notified_1d).
    """
    if field not in ("notified_3d", "notified_1d"):
        raise ValueError(f"Недопустимое поле: {field}")

    async with acquire() as conn:
        await conn.execute(
            f"UPDATE subscriptions SET {field} = TRUE WHERE id = $1",  # noqa: S608
            subscription_id,
        )


async def get_expired() -> list[dict]:
    """Находит все просроченные подписки, которые ещё не отмечены как expired.

    Returns:
        Список просроченных подписок с данными ноды и пользователя.
    """
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.*, u.telegram_id, n.host, n.port,
                   n.agent_url, n.agent_api_key
            FROM subscriptions s
            JOIN users u ON u.id = s.user_id
            JOIN nodes n ON n.id = s.node_id
            WHERE s.status IN ('active', 'expiring')
              AND s.expires_at <= NOW()
            """
        )
        return [dict(r) for r in rows]


async def set_status(subscription_id: int, status: str) -> None:
    """Обновляет статус подписки.

    Args:
        subscription_id: ID подписки.
        status: Новый статус (pending, active, expiring, expired, cancelled).
    """
    async with acquire() as conn:
        await conn.execute(
            "UPDATE subscriptions SET status = $1::subscription_status WHERE id = $2",
            status,
            subscription_id,
        )


async def count_active() -> int:
    """Возвращает количество активных подписок.

    Returns:
        Число активных подписок.
    """
    async with acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM subscriptions WHERE status IN ('active', 'expiring')"
        )


async def update_secret_and_node(
    subscription_id: int,
    *,
    new_secret: str,
    new_node_id: int,
) -> dict | None:
    """Обновляет секрет, ноду и время последней смены ключа.

    Args:
        subscription_id: ID подписки.
        new_secret: Новый dd-секрет.
        new_node_id: ID новой ноды.

    Returns:
        Обновлённая подписка или None.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE subscriptions
            SET secret = $1, node_id = $2, last_key_change = NOW()
            WHERE id = $3
            RETURNING *
            """,
            new_secret,
            new_node_id,
            subscription_id,
        )
        return dict(row) if row else None


async def get_all(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
) -> list[dict]:
    """Возвращает подписки с пагинацией и фильтрацией (для админки).

    Args:
        limit: Максимальное количество записей.
        offset: Смещение.
        status: Фильтр по статусу (опционально).

    Returns:
        Список подписок.
    """
    async with acquire() as conn:
        if status:
            rows = await conn.fetch(
                """
                SELECT s.*, u.telegram_id, u.username,
                       n.name AS node_name, p.name AS plan_name
                FROM subscriptions s
                JOIN users u ON u.id = s.user_id
                JOIN nodes n ON n.id = s.node_id
                JOIN plans p ON p.id = s.plan_id
                WHERE s.status = $1::subscription_status
                ORDER BY s.created_at DESC LIMIT $2 OFFSET $3
                """,
                status,
                limit,
                offset,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT s.*, u.telegram_id, u.username,
                       n.name AS node_name, p.name AS plan_name
                FROM subscriptions s
                JOIN users u ON u.id = s.user_id
                JOIN nodes n ON n.id = s.node_id
                JOIN plans p ON p.id = s.plan_id
                ORDER BY s.created_at DESC LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
        return [dict(r) for r in rows]

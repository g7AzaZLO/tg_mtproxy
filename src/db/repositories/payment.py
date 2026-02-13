"""Репозиторий платежей — raw SQL запросы через asyncpg."""

from datetime import datetime, timezone

import asyncpg

from src.db.pool import acquire


async def create(
    conn: asyncpg.Connection,
    *,
    user_id: int,
    plan_id: int,
    node_id: int,
    amount_usd: float,
) -> dict:
    """Создаёт запись о платеже в рамках существующего соединения.

    Args:
        conn: Соединение asyncpg (может быть в транзакции).
        user_id: Внутренний ID пользователя.
        plan_id: ID тарифного плана.
        node_id: ID выбранной ноды.
        amount_usd: Сумма в USD.

    Returns:
        Словарь с данными созданного платежа.
    """
    row = await conn.fetchrow(
        "INSERT INTO payments (user_id, plan_id, node_id, amount_usd) "
        "VALUES ($1, $2, $3, $4) RETURNING *",
        user_id,
        plan_id,
        node_id,
        amount_usd,
    )
    return dict(row)


async def update_cryptocloud_data(
    payment_id: int,
    *,
    cryptocloud_uuid: str,
    cryptocloud_link: str,
) -> None:
    """Обновляет данные CryptoCloud после создания инвойса.

    Args:
        payment_id: ID платежа.
        cryptocloud_uuid: UUID инвойса в CryptoCloud.
        cryptocloud_link: Ссылка на страницу оплаты.
    """
    async with acquire() as conn:
        await conn.execute(
            "UPDATE payments SET cryptocloud_uuid = $1, cryptocloud_link = $2 WHERE id = $3",
            cryptocloud_uuid,
            cryptocloud_link,
            payment_id,
        )


async def get_by_cryptocloud_uuid(uuid: str) -> dict | None:
    """Находит платёж по UUID инвойса CryptoCloud.

    Args:
        uuid: UUID инвойса CryptoCloud (формат INV-XXXXXXXX).

    Returns:
        Словарь с данными платежа или None.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.*, pl.duration_days, pl.name AS plan_name, pl.is_trial
            FROM payments p
            JOIN plans pl ON pl.id = p.plan_id
            WHERE p.cryptocloud_uuid = $1
            """,
            uuid,
        )
        return dict(row) if row else None


async def set_status(
    payment_id: int,
    status: str,
    *,
    conn: asyncpg.Connection | None = None,
) -> None:
    """Обновляет статус платежа.

    Args:
        payment_id: ID платежа.
        status: Новый статус (created, success, paid, expired, cancelled).
        conn: Опциональное соединение для использования в транзакции.
    """
    query = "UPDATE payments SET status = $1::payment_status WHERE id = $2"
    if conn:
        await conn.execute(query, status, payment_id)
    else:
        async with acquire() as c:
            await c.execute(query, status, payment_id)


async def set_paid(
    payment_id: int,
    *,
    subscription_id: int,
    conn: asyncpg.Connection | None = None,
) -> None:
    """Помечает платёж как завершённый (paid) и привязывает подписку.

    Args:
        payment_id: ID платежа.
        subscription_id: ID созданной подписки.
        conn: Опциональное соединение для использования в транзакции.
    """
    query = (
        "UPDATE payments SET status = 'paid', subscription_id = $1, "
        "paid_at = $2 WHERE id = $3"
    )
    now = datetime.now(timezone.utc)
    if conn:
        await conn.execute(query, subscription_id, now, payment_id)
    else:
        async with acquire() as c:
            await c.execute(query, subscription_id, now, payment_id)


async def get_by_id(payment_id: int) -> dict | None:
    """Находит платёж по ID.

    Args:
        payment_id: Идентификатор платежа.

    Returns:
        Словарь с данными платежа или None.
    """
    async with acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM payments WHERE id = $1", payment_id)
        return dict(row) if row else None


async def get_stuck_success_payments() -> list[dict]:
    """Находит платежи в статусе success без привязанной подписки.

    Используется планировщиком для повторной попытки активации.

    Returns:
        Список «зависших» платежей.
    """
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.*, pl.duration_days, pl.name AS plan_name, pl.is_trial,
                   n.host, n.port, n.agent_url, n.agent_api_key,
                   n.country, n.country_flag
            FROM payments p
            JOIN plans pl ON pl.id = p.plan_id
            LEFT JOIN nodes n ON n.id = p.node_id
            WHERE p.status = 'success'
              AND p.subscription_id IS NULL
              AND p.created_at > NOW() - INTERVAL '24 hours'
            """
        )
        return [dict(r) for r in rows]


async def get_user_payments(
    user_id: int,
    limit: int = 20,
) -> list[dict]:
    """Возвращает историю платежей пользователя.

    Args:
        user_id: Внутренний ID пользователя.
        limit: Максимальное количество записей.

    Returns:
        Список платежей пользователя.
    """
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.*, pl.name AS plan_name
            FROM payments p
            JOIN plans pl ON pl.id = p.plan_id
            WHERE p.user_id = $1
            ORDER BY p.created_at DESC LIMIT $2
            """,
            user_id,
            limit,
        )
        return [dict(r) for r in rows]


async def get_revenue_stats() -> dict:
    """Возвращает статистику доходов (для админки).

    Returns:
        Словарь с total_revenue, month_revenue, week_revenue, today_revenue.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(amount_usd), 0) AS total_revenue,
                COALESCE(SUM(amount_usd) FILTER (
                    WHERE paid_at >= DATE_TRUNC('month', NOW())
                ), 0) AS month_revenue,
                COALESCE(SUM(amount_usd) FILTER (
                    WHERE paid_at >= NOW() - INTERVAL '7 days'
                ), 0) AS week_revenue,
                COALESCE(SUM(amount_usd) FILTER (
                    WHERE paid_at >= DATE_TRUNC('day', NOW())
                ), 0) AS today_revenue
            FROM payments
            WHERE status = 'paid'
            """
        )
        return dict(row)

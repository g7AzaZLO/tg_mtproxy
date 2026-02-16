"""Репозиторий тарифных планов — raw SQL запросы через asyncpg."""

from src.db.pool import acquire


async def get_active_plans(*, include_trial: bool = True) -> list[dict]:
    """Возвращает все активные тарифные планы.

    Args:
        include_trial: Включать ли пробный план в результат.

    Returns:
        Список активных тарифных планов.
    """
    async with acquire() as conn:
        if include_trial:
            rows = await conn.fetch(
                "SELECT * FROM plans WHERE is_active = TRUE ORDER BY duration_days"
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM plans WHERE is_active = TRUE AND is_trial = FALSE "
                "ORDER BY duration_days"
            )
        return [dict(r) for r in rows]


async def get_by_id(plan_id: int) -> dict | None:
    """Находит тарифный план по ID.

    Args:
        plan_id: Идентификатор плана.

    Returns:
        Словарь с данными плана или None.
    """
    async with acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM plans WHERE id = $1", plan_id)
        return dict(row) if row else None


async def get_trial_plan() -> dict | None:
    """Возвращает активный пробный план.

    Returns:
        Словарь с данными пробного плана или None, если отключён.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM plans WHERE is_trial = TRUE AND is_active = TRUE LIMIT 1"
        )
        return dict(row) if row else None


async def get_all() -> list[dict]:
    """Возвращает все тарифные планы.

    Returns:
        Список всех планов, включая неактивные.
    """
    async with acquire() as conn:
        rows = await conn.fetch("SELECT * FROM plans ORDER BY duration_days, id")
        return [dict(r) for r in rows]


async def create(
    *,
    name: str,
    duration_days: int,
    price_usd: float,
    is_trial: bool,
    is_active: bool,
) -> dict:
    """Создаёт новый тарифный план.

    Args:
        name: Название плана.
        duration_days: Длительность в днях.
        price_usd: Стоимость в USD.
        is_trial: Пробный ли план.
        is_active: Активен ли план.

    Returns:
        Созданный план.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO plans (name, duration_days, price_usd, is_trial, is_active)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            name,
            duration_days,
            price_usd,
            is_trial,
            is_active,
        )
        return dict(row)


async def update_plan(
    plan_id: int,
    *,
    name: str,
    duration_days: int,
    price_usd: float,
    is_trial: bool,
    is_active: bool,
) -> dict | None:
    """Обновляет тарифный план.

    Args:
        plan_id: ID плана.
        name: Название.
        duration_days: Длительность.
        price_usd: Цена.
        is_trial: Пробный план.
        is_active: Активность.

    Returns:
        Обновлённый план или None.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE plans
            SET name = $1,
                duration_days = $2,
                price_usd = $3,
                is_trial = $4,
                is_active = $5
            WHERE id = $6
            RETURNING *
            """,
            name,
            duration_days,
            price_usd,
            is_trial,
            is_active,
            plan_id,
        )
        return dict(row) if row else None


async def set_active(plan_id: int, *, is_active: bool) -> bool:
    """Включает или отключает тариф.

    Args:
        plan_id: ID плана.
        is_active: Флаг активности.

    Returns:
        True при успешном обновлении.
    """
    async with acquire() as conn:
        result = await conn.execute(
            "UPDATE plans SET is_active = $1 WHERE id = $2",
            is_active,
            plan_id,
        )
        return result.endswith("1")


async def delete_plan(plan_id: int) -> bool:
    """Удаляет тарифный план.

    Args:
        plan_id: ID плана.

    Returns:
        True, если план удалён.
    """
    async with acquire() as conn:
        result = await conn.execute("DELETE FROM plans WHERE id = $1", plan_id)
        return result.endswith("1")

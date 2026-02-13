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

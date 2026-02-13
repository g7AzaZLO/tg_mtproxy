"""Репозиторий серверных нод — raw SQL запросы через asyncpg."""

from src.db.pool import acquire


async def get_active_nodes() -> list[dict]:
    """Возвращает все активные ноды.

    Returns:
        Список словарей с данными активных нод.
    """
    async with acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM nodes WHERE is_active = TRUE ORDER BY country, name"
        )
        return [dict(r) for r in rows]


async def get_by_id(node_id: int) -> dict | None:
    """Находит ноду по ID.

    Args:
        node_id: Идентификатор ноды.

    Returns:
        Словарь с данными ноды или None.
    """
    async with acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM nodes WHERE id = $1", node_id)
        return dict(row) if row else None


async def get_available_countries() -> list[dict]:
    """Возвращает уникальные страны с активными нодами.

    Returns:
        Список словарей с полями country и country_flag.
    """
    async with acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT country, country_flag FROM nodes "
            "WHERE is_active = TRUE ORDER BY country"
        )
        return [dict(r) for r in rows]


async def get_least_loaded_node(country: str) -> dict | None:
    """Находит наименее загруженную ноду в указанной стране.

    Загруженность определяется по количеству активных подписок
    относительно max_users ноды.

    Args:
        country: Название страны.

    Returns:
        Словарь с данными ноды или None, если свободных нет.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT n.*, COALESCE(sub_count, 0) AS current_users
            FROM nodes n
            LEFT JOIN (
                SELECT node_id, COUNT(*) AS sub_count
                FROM subscriptions
                WHERE status IN ('active', 'expiring')
                GROUP BY node_id
            ) s ON s.node_id = n.id
            WHERE n.is_active = TRUE
              AND n.country = $1
              AND COALESCE(s.sub_count, 0) < n.max_users
            ORDER BY COALESCE(s.sub_count, 0) ASC
            LIMIT 1
            """,
            country,
        )
        return dict(row) if row else None


async def get_nodes_with_load() -> list[dict]:
    """Возвращает все ноды с текущей загрузкой (для админки).

    Returns:
        Список нод с дополнительным полем current_users.
    """
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT n.*, COALESCE(sub_count, 0) AS current_users
            FROM nodes n
            LEFT JOIN (
                SELECT node_id, COUNT(*) AS sub_count
                FROM subscriptions
                WHERE status IN ('active', 'expiring')
                GROUP BY node_id
            ) s ON s.node_id = n.id
            ORDER BY n.country, n.name
            """
        )
        return [dict(r) for r in rows]


async def create(
    name: str,
    host: str,
    port: int,
    country: str,
    country_flag: str,
    agent_url: str,
    agent_api_key: str,
    max_users: int = 500,
) -> dict:
    """Создаёт новую ноду.

    Args:
        name: Человекочитаемое имя ноды.
        host: IP-адрес или доменное имя сервера.
        port: Порт MTProxy.
        country: Страна расположения.
        country_flag: Эмодзи-флаг страны.
        agent_url: URL API-агента на ноде.
        agent_api_key: API-ключ для агента.
        max_users: Максимальное количество пользователей.

    Returns:
        Словарь с данными созданной ноды.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO nodes (name, host, port, country, country_flag, "
            "agent_url, agent_api_key, max_users) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *",
            name,
            host,
            port,
            country,
            country_flag,
            agent_url,
            agent_api_key,
            max_users,
        )
        return dict(row)


async def update_active(node_id: int, *, is_active: bool) -> None:
    """Включает или отключает ноду.

    Args:
        node_id: Идентификатор ноды.
        is_active: True для активации, False для отключения.
    """
    async with acquire() as conn:
        await conn.execute(
            "UPDATE nodes SET is_active = $1 WHERE id = $2",
            is_active,
            node_id,
        )

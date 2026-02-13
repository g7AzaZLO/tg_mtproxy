"""Скрипт применения SQL-миграций к базе данных.

Запуск:
    python -m migrations.run

Скрипт читает все .sql файлы из директории migrations/ в порядке сортировки,
проверяет, были ли они уже применены, и выполняет новые.
"""

import asyncio
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings


MIGRATIONS_DIR = Path(__file__).resolve().parent


async def get_applied_versions(conn: asyncpg.Connection) -> set[str]:
    """Получает множество уже применённых версий миграций.

    Args:
        conn: Активное соединение с БД.

    Returns:
        Множество строк-версий, которые уже были применены.
    """
    table_exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'schema_migrations')"
    )
    if not table_exists:
        return set()
    rows = await conn.fetch("SELECT version FROM schema_migrations")
    return {row["version"] for row in rows}


async def run_migrations() -> None:
    """Применяет все неприменённые SQL-миграции в порядке их номеров."""
    settings = get_settings()
    conn = await asyncpg.connect(dsn=settings.db.dsn)

    try:
        applied = await get_applied_versions(conn)
        sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

        for sql_file in sql_files:
            version = sql_file.stem
            if version in applied:
                print(f"  [skip] {sql_file.name} — уже применена")
                continue

            print(f"  [apply] {sql_file.name} ...")
            sql = sql_file.read_text(encoding="utf-8")
            await conn.execute(sql)
            print(f"  [done] {sql_file.name}")

        print("Все миграции применены.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
